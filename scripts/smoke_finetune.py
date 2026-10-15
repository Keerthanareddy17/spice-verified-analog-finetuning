"""Local end-to-end smoke test of fine-tuning + evaluation on tiny data (CPU/MPS). Outputs go to a temp dir.

Usage (needs the Phase 3 libraries, see requirements-colab.txt):
  python scripts/smoke_finetune.py [--root DIR]
"""
import argparse
import shutil
import tempfile
import time
from pathlib import Path

from analogft.finetune import FTConfig, evaluate_model, train


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=None)
    ap.add_argument("--keep", action="store_true")
    args = ap.parse_args()
    root = Path(args.root) if args.root else Path(tempfile.mkdtemp(prefix="analogft_smoke_"))
    cfg = FTConfig(run_name="smoke", root=str(root), max_steps=10, max_train_examples=32, max_eval_examples=5,
                   per_device_batch=4, grad_accum=1, logging_steps=2, eval_steps=5, save_steps=5,
                   eval_batch_size=5)
    t0 = time.time()
    summary = train(cfg)
    res = evaluate_model(cfg, "finetuned", cfg.run_dir / "adapter")
    print(f"\nSMOKE OK in {time.time() - t0:.0f}s; summary={summary}")
    print("outputs:", sorted(str(p.relative_to(cfg.run_dir)) for p in cfg.run_dir.rglob("*") if p.is_file() and "checkpoints" not in str(p))[:20])
    print("first raw outputs:", [__import__("json").loads(l)["raw"][:80] for l in (cfg.run_dir / "eval/finetuned/subset/predictions.jsonl").read_text().splitlines()[:3]])
    if not args.keep:
        shutil.rmtree(root, ignore_errors=True)
        print("deleted", root)


if __name__ == "__main__":
    main()
