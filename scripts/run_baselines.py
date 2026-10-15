"""Score the no-GPU baselines on val and test. Usage: python scripts/run_baselines.py [--name phase2]"""
import argparse
import json

from analogft import paths
from analogft.baselines import score_baselines
from analogft.dataset import read_jsonl


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", default="phase2")
    ap.add_argument("--no-write", action="store_true")
    args = ap.parse_args()
    d = paths.DATA_DIR / args.name
    train, val, test = (read_jsonl(d / f"{s}.jsonl") for s in ("train", "val", "test"))
    res = score_baselines(train, {"val": val, "test": test})
    cols = ("valid_rate", "top1", "top1_exact", "top3", "improve_rate", "mean_regret")
    print(f"majority action: {res['_majority_action']}")
    for split in ("val", "test"):
        print(f"\n{split}  (n={res['random'][split]['n']})")
        print(f"{'baseline':16s}" + "".join(f"{c:>13s}" for c in cols))
        for b in ("random", "majority", "textbook_rules"):
            print(f"{b:16s}" + "".join(f"{res[b][split][c]:13.3f}" for c in cols))
    if not args.no_write:
        out = paths.RESULTS_DIR / "phase2_baselines.json"
        out.write_text(json.dumps(res, indent=2) + "\n")
        print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
