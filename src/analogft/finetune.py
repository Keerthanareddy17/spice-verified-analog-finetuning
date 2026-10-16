"""LoRA supervised fine-tuning (TRL + PEFT) and the Phase 3 evaluation of base vs fine-tuned models.

Used by notebooks/01_finetune_eval.ipynb and by the local smoke test (scripts/smoke_finetune.py).

Run layout (all under runs/phase3/<run_name>/):
    config.json            the settings used
    checkpoints/           resumable Trainer checkpoints (large; excluded from results archives)
    adapter/               final LoRA adapter
    logs/train_log.json    loss history;  figures/loss_curve.png
    eval/<base|finetuned>/<val|test|subset>/{predictions.jsonl,metrics.json}
"""
from __future__ import annotations

import json
import math
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import paths
from .dataset import read_jsonl
from .harness import SUBSET_FILE, fmt_metrics, save_evaluation, select
from .predict import HFBackend, Predictor


@dataclass
class FTConfig:
    base_model: str = "Qwen/Qwen2.5-0.5B-Instruct"
    run_name: str = "qwen25_05b_lora"
    data_name: str = "phase2"
    # LoRA
    lora_r: int = 16
    lora_alpha: int = 32
    lora_dropout: float = 0.05
    # optimisation
    learning_rate: float = 2e-4
    warmup_ratio: float = 0.05
    lr_scheduler: str = "cosine"
    epochs: float = 2
    per_device_batch: int = 16
    grad_accum: int = 1               # effective batch = per_device_batch * grad_accum = 16
    max_length: int = 640             # real max is 550 Qwen tokens (prompt <= 502, reply <= 49); 512 would cut off replies
    seed: int = 0
    precision: str = "auto"           # "auto" = fp16 on GPU with fp32 fallback if the loss is not finite; "fp16" | "fp32"
    # bookkeeping
    logging_steps: int = 10
    eval_steps: int = 50
    save_steps: int = 50
    # limits for the smoke test
    max_steps: int = -1
    max_train_examples: int | None = None
    max_eval_examples: int | None = None
    eval_batch_size: int = 32
    max_new_tokens: int = 64
    root: str | None = None           # override of the runs/ parent (smoke test)
    phase: str = "phase3"             # runs/<phase>/<run_name>/ (expert iteration uses phase4)
    init_adapter: str | None = None   # continue training this LoRA adapter instead of a fresh one (expert iteration)
    train_file: str | None = None     # jsonl of chat records to train on instead of data/<data_name>/train.jsonl

    @property
    def run_dir(self) -> Path:
        base = Path(self.root) if self.root else paths.RUNS_DIR / self.phase
        return base / self.run_name


# ----- data ---------------------------------------------------------------------------------

def to_prompt_completion(rec: dict) -> dict:
    """Conversational prompt/completion pair: TRL puts the loss on the completion (assistant reply) only."""
    msgs = rec["messages"]
    assert [m["role"] for m in msgs] == ["system", "user", "assistant"]
    return {"prompt": msgs[:2], "completion": [msgs[2]]}


def load_sft_data(cfg: FTConfig):
    from datasets import Dataset
    d = paths.DATA_DIR / cfg.data_name
    train = read_jsonl(Path(cfg.train_file)) if cfg.train_file else read_jsonl(d / "train.jsonl")
    val = read_jsonl(d / "val.jsonl")
    if cfg.max_train_examples:
        train = train[: cfg.max_train_examples]
    if cfg.max_eval_examples:
        val = val[: cfg.max_eval_examples]
    return Dataset.from_list([to_prompt_completion(r) for r in train]), Dataset.from_list([to_prompt_completion(r) for r in val])


def token_length_report(tok, records: list[dict]) -> dict:
    """Length in tokens of the full conversations (must stay below max_length or the reply gets cut off)."""
    lens = [len(tok(tok.apply_chat_template(r["messages"], tokenize=False)).input_ids) for r in records]
    return {"n": len(lens), "max": max(lens), "mean": sum(lens) / len(lens)}


# ----- training -----------------------------------------------------------------------------

def _load_model(cfg: FTConfig, fp16: bool):
    import torch
    from transformers import AutoModelForCausalLM
    return AutoModelForCausalLM.from_pretrained(cfg.base_model, dtype=torch.float16 if fp16 else torch.float32)


def _make_trainer(cfg: FTConfig, model, tok, train_ds, val_ds, use_fp16: bool):
    from peft import LoraConfig
    from trl import SFTConfig, SFTTrainer
    run = cfg.run_dir
    args = SFTConfig(
        output_dir=str(run / "checkpoints"),
        num_train_epochs=cfg.epochs, max_steps=cfg.max_steps,
        per_device_train_batch_size=cfg.per_device_batch, per_device_eval_batch_size=cfg.per_device_batch,
        gradient_accumulation_steps=cfg.grad_accum,
        learning_rate=cfg.learning_rate, lr_scheduler_type=cfg.lr_scheduler, warmup_steps=cfg.warmup_ratio,  # a float in [0,1) means a fraction of total steps (transformers 5)
        fp16=use_fp16, bf16=False,           # T4 has no bf16
        max_length=cfg.max_length, seed=cfg.seed, data_seed=cfg.seed,
        completion_only_loss=True,           # loss on the assistant reply only
        logging_steps=cfg.logging_steps, eval_strategy="steps", eval_steps=cfg.eval_steps,
        save_strategy="steps", save_steps=cfg.save_steps, save_total_limit=2,
        report_to="none", dataloader_num_workers=0,
    )
    peft_cfg = LoraConfig(r=cfg.lora_r, lora_alpha=cfg.lora_alpha, lora_dropout=cfg.lora_dropout, bias="none",
                          task_type="CAUSAL_LM",
                          target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"])
    if cfg.init_adapter:                    # expert iteration: keep training the Phase 3 adapter
        from peft import PeftModel
        model = PeftModel.from_pretrained(model, cfg.init_adapter, is_trainable=True)
        peft_cfg = None
    return SFTTrainer(model=model, args=args, train_dataset=train_ds, eval_dataset=val_ds,
                      processing_class=tok, peft_config=peft_cfg)


def show_masking(trainer, tok, index: int = 0, log=print) -> dict:
    """Print which tokens of one training example carry loss. Returns counts."""
    ex = trainer.train_dataset[index]
    ids = ex["input_ids"]
    if "labels" in ex:                       # TRL >= 1.x: prompt positions are -100
        mask = [int(l != -100) for l in ex["labels"]]
    else:                                    # older TRL: completion_mask
        mask = list(ex["completion_mask"])
    n_loss = int(sum(mask))
    first = mask.index(1) if 1 in mask else len(mask)
    log(f"masking check (example {index}): {len(ids)} tokens, {n_loss} with loss, {len(ids) - n_loss} masked")
    log("  masked tail of prompt : " + repr(tok.decode(ids[max(0, first - 8):first])))
    log("  tokens WITH loss      : " + repr(tok.decode([t for t, m in zip(ids, mask) if m])))
    assert 0 < n_loss < len(ids) and all(m == 0 for m in mask[:first]), "prompt must be fully masked"
    return {"tokens": len(ids), "loss_tokens": n_loss}


class TimingCallback:
    """Prints a time estimate after `at_step` optimisation steps."""
    def __new__(cls, at_step: int = 20, log=print):
        from transformers import TrainerCallback

        class _CB(TrainerCallback):
            def on_train_begin(self, args, state, control, **kw):
                self.t0, self.s0, self.done = time.time(), state.global_step, False

            def on_step_end(self, args, state, control, **kw):
                n = state.global_step - self.s0
                if not self.done and n >= at_step:
                    per = (time.time() - self.t0) / n
                    left = state.max_steps - state.global_step
                    log(f"[timing] {per:.2f} s/step -> about {per * left / 60:.1f} min of training left "
                        f"({state.max_steps} steps total, evals/checkpoints extra)")
                    self.done = True
        return _CB()


def _finite_first_loss(trainer) -> bool:
    """One forward pass on a training batch: is the loss finite? (fp16 can overflow.)"""
    import torch
    batch = next(iter(trainer.get_train_dataloader()))
    batch = {k: v.to(trainer.args.device) for k, v in batch.items() if hasattr(v, "to")}
    trainer.model.eval()
    with torch.no_grad(), torch.autocast(device_type=trainer.args.device.type, dtype=torch.float16,
                                         enabled=trainer.args.fp16):
        loss = trainer.model(**{k: v for k, v in batch.items() if k in ("input_ids", "attention_mask", "labels")}).loss
    trainer.model.train()
    return bool(torch.isfinite(loss))


def train(cfg: FTConfig, log=print) -> dict:
    """Fine-tune with LoRA; resumes from the last checkpoint if one exists. Returns a summary dict."""
    import torch
    from transformers import AutoTokenizer
    from transformers.trainer_utils import get_last_checkpoint

    run = cfg.run_dir
    for sub in ("checkpoints", "logs", "figures", "eval"):
        (run / sub).mkdir(parents=True, exist_ok=True)
    (run / "config.json").write_text(json.dumps(asdict(cfg), indent=2) + "\n")
    tok = AutoTokenizer.from_pretrained(cfg.base_model)
    train_ds, val_ds = load_sft_data(cfg)
    lens = token_length_report(tok, [{"messages": p["prompt"] + p["completion"]} for p in list(train_ds) + list(val_ds)])
    log(f"conversation length in tokens: {lens}")
    assert lens["max"] <= cfg.max_length, f"longest example ({lens['max']} tokens) exceeds max_length={cfg.max_length}: replies would be truncated"
    gpu = torch.cuda.is_available()
    want_fp16 = gpu and cfg.precision in ("auto", "fp16")
    log(f"train={len(train_ds)} val={len(val_ds)} precision={'fp16' if want_fp16 else 'fp32'} (requested {cfg.precision})")

    trainer = _make_trainer(cfg, _load_model(cfg, want_fp16), tok, train_ds, val_ds, want_fp16)
    if want_fp16 and cfg.precision == "auto" and not _finite_first_loss(trainer):
        log("fp16 loss is not finite on the first batch; falling back to fp32")
        want_fp16 = False
        trainer = _make_trainer(cfg, _load_model(cfg, False), tok, train_ds, val_ds, False)
    n_train = sum(p.numel() for p in trainer.model.parameters() if p.requires_grad)
    log(f"trainable parameters: {n_train:,}")
    assert n_train > 0, "no trainable parameters (adapter loaded frozen?)"
    mask_info = show_masking(trainer, tok, log=log)
    trainer.add_callback(TimingCallback(20, log))

    ckpt = get_last_checkpoint(str(run / "checkpoints")) if (run / "checkpoints").exists() else None
    if ckpt:
        log(f"resuming from {ckpt}")
    t0 = time.time()
    out = trainer.train(resume_from_checkpoint=ckpt)
    minutes = (time.time() - t0) / 60
    nan_logged = [h for h in trainer.state.log_history if "loss" in h and not math.isfinite(h["loss"])]
    assert not nan_logged, "NaN/inf training loss: rerun with precision='fp32'"
    trainer.save_model(str(run / "adapter"))
    tok.save_pretrained(str(run / "adapter"))
    (run / "logs" / "train_log.json").write_text(json.dumps(trainer.state.log_history, indent=1) + "\n")
    plot_loss_curve(trainer.state.log_history, run / "figures" / "loss_curve.png", cfg.run_name)
    summary = {"train_minutes": round(minutes, 2), "final_train_loss": out.training_loss,
               "fp16": want_fp16, "global_step": trainer.state.global_step, **mask_info,
               "final_eval_loss": next((h["eval_loss"] for h in reversed(trainer.state.log_history) if "eval_loss" in h), None)}
    (run / "logs" / "train_summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    log("training done:", summary)
    del trainer
    if gpu:
        torch.cuda.empty_cache()
    return summary


def plot_loss_curve(history: list[dict], out: Path, title: str = "") -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    tr = [(h["step"], h["loss"]) for h in history if "loss" in h]
    ev = [(h["step"], h["eval_loss"]) for h in history if "eval_loss" in h]
    fig, ax = plt.subplots(figsize=(6, 3.6))
    if tr:
        ax.plot(*zip(*tr), label="train loss", lw=1.5)
    if ev:
        ax.plot(*zip(*ev), label="val loss", marker="o", lw=1.5)
    ax.set_xlabel("optimizer step"); ax.set_ylabel("loss (reply tokens only)"); ax.set_title(title)
    ax.grid(alpha=0.3); ax.legend()
    fig.tight_layout(); out.parent.mkdir(parents=True, exist_ok=True); fig.savefig(out, dpi=150); plt.close(fig)


# ----- evaluation ---------------------------------------------------------------------------

def evaluate_model(cfg: FTConfig, label: str, adapter: Path | None, log=print, skip_if_done: bool = False) -> dict:
    """Generate for val and test, score with the shared harness, save val/test/subset results.

    The 150-example subset is a subset of test, so test is generated once and the subset rows are selected.
    """
    out_root = cfg.run_dir / "eval" / label
    if skip_if_done and all((out_root / s / "metrics.json").exists() for s in ("val", "test", "subset")):
        log(f"[{label}] evaluation already saved in {out_root}, skipping")
        return {s: json.loads((out_root / s / "metrics.json").read_text()) for s in ("val", "test", "subset")}
    d = paths.DATA_DIR / cfg.data_name
    val, test = read_jsonl(d / "val.jsonl"), read_jsonl(d / "test.jsonl")
    subset_ids = json.loads((paths.REPO_ROOT / "results" / "phase3" / SUBSET_FILE).read_text())["ids"]  # committed file
    if cfg.max_eval_examples:  # smoke test: a few val examples and a few test examples from the subset
        val = val[: cfg.max_eval_examples]
        test = [r for r in test if r["id"] in set(subset_ids)][: cfg.max_eval_examples]
    backend = HFBackend(cfg.base_model, adapter, max_new_tokens=cfg.max_new_tokens, batch_size=cfg.eval_batch_size)
    pred = Predictor(backend)
    results = {}
    t0 = time.time()
    test_preds = None
    for split, recs in (("val", val), ("test", test)):
        preds = pred.predict_batch(recs)
        results[split] = save_evaluation(out_root / split, recs, preds, f"{label} {split}")
        log(f"[{label}] {split}: {fmt_metrics(results[split])}")
        if split == "test":
            test_preds = preds
    in_subset = [i for i, r in enumerate(test) if r["id"] in set(subset_ids)]
    if in_subset:
        sub_recs, sub_preds = [test[i] for i in in_subset], [test_preds[i] for i in in_subset]
        results["subset"] = save_evaluation(out_root / "subset", sub_recs, sub_preds, f"{label} subset")
        log(f"[{label}] subset: {fmt_metrics(results['subset'])}")
    log(f"[{label}] evaluation took {(time.time() - t0) / 60:.1f} min")
    del backend, pred
    try:
        import torch
        torch.cuda.empty_cache()
    except Exception:
        pass
    return results
