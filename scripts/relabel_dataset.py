"""Re-apply the tie-break (largest margin beyond spec) to a built dataset, from stored outcomes only.

Usage: python scripts/relabel_dataset.py [--name phase2]
No simulations are run. Rewrites train|val|test.jsonl and build_stats.json["summary"] in place.
"""
import argparse
import json
from collections import Counter

from analogft import paths
from analogft.dataset import SPLITS, read_jsonl, write_jsonl
from analogft.dataset_stats import summarize
from analogft.relabel import relabel_record


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", default="phase2")
    args = ap.parse_args()
    d = paths.DATA_DIR / args.name
    new_all, changed, same_text_ok, n_same = [], 0, 0, 0
    for s in SPLITS:
        old = read_jsonl(d / f"{s}.jsonl")
        new = [relabel_record(r) for r in old]
        for o, n in zip(old, new):
            if o["label_action"] != n["label_action"]:
                changed += 1
                assert o["label_action"] in n["tied_best"], "label may only change among tied actions"
            else:
                n_same += 1
                same_text_ok += o["messages"] == n["messages"]  # regeneration must reproduce old text
        write_jsonl(d / f"{s}.jsonl", new)
        new_all += new
    assert same_text_ok == n_same, f"regenerated text differs for {n_same - same_text_ok} unchanged labels"
    stats = json.loads((d / "build_stats.json").read_text())
    episodes = [e for s in SPLITS for e in read_jsonl(d / f"episodes_{s}.jsonl")]
    stats["summary"] = summarize(new_all, episodes)
    stats["tie_break"] = "largest margin beyond spec, then action id order (D16)"
    (d / "build_stats.json").write_text(json.dumps(stats, indent=2) + "\n")
    n_tied = sum(bool(r["tied_best"]) for r in new_all)
    print(f"states={len(new_all)} tied={n_tied} labels changed={changed} (unchanged labels reproduced old text exactly: {same_text_ok}/{n_same})")
    print("new labels:", dict(Counter(r["label_action"] for r in new_all).most_common()))


if __name__ == "__main__":
    main()
