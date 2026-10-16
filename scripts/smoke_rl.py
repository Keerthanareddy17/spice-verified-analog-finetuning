"""Local end-to-end smoke test of the model-based Phase 4 parts on tiny data (CPU/MPS; needs the Phase 3 libraries).

tiny adapter -> sampling agent rollouts with the HF backend -> expert-iteration dataset -> continue training from the
adapter -> single-step eval -> agent eval with the new adapter. Outputs go to a temp dir that is deleted.
Usage: python scripts/smoke_rl.py
"""
import json
import shutil
import tempfile
import time
from pathlib import Path

from analogft import paths
from analogft.agent import SimPool
from analogft.agent_eval import fmt_agent, load_episodes, run_and_save
from analogft.dataset import read_jsonl
from analogft.expert_iteration import build_rl_dataset
from analogft.finetune import FTConfig, evaluate_model, train
from analogft.policies import LLMPolicy, RulesPolicy
from analogft.predict import HFBackend
from analogft.tracing import TraceWriter, read_traces

BASE = "Qwen/Qwen2.5-0.5B-Instruct"


def main() -> None:
    root = Path(tempfile.mkdtemp(prefix="analogft_smoke4_"))
    t0 = time.time()
    # 1. a tiny stand-in for the Phase 3 adapter
    cfg3 = FTConfig(run_name="p3", root=str(root), max_steps=6, max_train_examples=32, max_eval_examples=4,
                    per_device_batch=4, logging_steps=2, eval_steps=3, save_steps=3, eval_batch_size=4)
    train(cfg3)
    adapter3 = cfg3.run_dir / "adapter"
    train_eps = load_episodes("train")[:4]
    with SimPool() as sim:
        # 2. sampling rollouts with the HF policy + recovery, full states kept
        pol = LLMPolicy(HFBackend(BASE, adapter3, temperature=0.8, batch_size=8))
        tw = TraceWriter(root / "rollouts", keep_state_full=True)
        from analogft.agent import run_agent
        run_agent(train_eps, pol, recovery=True, sim=sim, trace=tw, run_id="rollout", samples=2, max_steps=3, log=print)
        print("HF rollouts:", len(tw.episodes), "episodes,", sum(e["solved"] for e in tw.episodes), "solved,",
              len(tw.steps), "steps; sample raw:", tw.steps[0]["raw"][:90])
        # a tiny model rarely solves anything: add rules-policy rollouts so the dataset step has data to select from
        tw2 = TraceWriter(keep_state_full=True)
        run_agent(train_eps, RulesPolicy(), recovery=True, sim=sim, trace=tw2, run_id="standin", max_steps=8)
        steps, eps = tw.steps + tw2.steps, tw.episodes + tw2.episodes
        train_recs = read_jsonl(paths.DATA_DIR / "phase2" / "train.jsonl")[:40]
        mixed, stats = build_rl_dataset(train_recs, steps, eps, root / "rl_train.jsonl")
        print("expert-iteration stats:", json.dumps({k: stats[k] for k in ("rollouts", "rollouts_solved", "candidate_steps",
              "duplicates_of_phase2_train", "new_examples", "train_examples_after")}))
        # 3. continue training from the adapter
        cfg4 = FTConfig(run_name="rl", phase="phase4", root=str(root), init_adapter=str(adapter3), learning_rate=1e-4,
                        epochs=1, train_file=str(root / "rl_train.jsonl"), max_steps=4, max_train_examples=None,
                        max_eval_examples=4, per_device_batch=4, logging_steps=2, eval_steps=2, save_steps=2,
                        eval_batch_size=4)
        cfg4.root = str(root / "p4")
        train(cfg4)
        evaluate_model(cfg4, "finetuned", cfg4.run_dir / "adapter")
        # 4. agent eval with the new adapter
        pol4 = LLMPolicy(HFBackend(BASE, cfg4.run_dir / "adapter", batch_size=8))
        m = run_and_save(root / "agent_rl", "rl-agent", pol4, load_episodes("test")[:4], recovery=True, sim=sim,
                         max_steps=3, log=lambda *_: None)
        print("RL agent:", fmt_agent(m))
    print(f"\nSMOKE OK in {time.time() - t0:.0f}s")
    shutil.rmtree(root, ignore_errors=True)
    print("deleted", root)


if __name__ == "__main__":
    main()
