"""Build results/phase3_results.md and results/phase3_results.json from pulled runs and committed Groq results.

Usage: python scripts/make_results_table.py [--runs qwen25_05b_lora [qwen25_15b_lora ...]]
Needs runs/phase3/<run>/eval/ (unpack a results archive with scripts/import_results_zip.py).
"""
import argparse
import json
from pathlib import Path

from analogft import paths
from analogft.evaluation import breakdown
from analogft.harness import score_method, select
from analogft.report import (NAMES, groq_runs, load_phase2, markdown_table,
                             non_model_summaries, run_methods, subset_ids)


def short_model(run_dir: Path) -> str:
    cfg = json.loads((run_dir / "config.json").read_text())
    return cfg["base_model"].split("/")[-1].replace("-Instruct", "")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", nargs="+", default=["qwen25_05b_lora"])
    args = ap.parse_args()
    train, _, test = load_phase2()
    sub = select(test, subset_ids())
    sub_ids = [r["id"] for r in sub]

    subset_methods = non_model_summaries(train, sub)
    subset_methods.update(groq_runs())
    test_methods = non_model_summaries(train, test)
    rows_for_breakdown = {NAMES["textbook_rules"]: score_method("textbook_rules", train, sub)[0],
                          NAMES["majority"]: score_method("majority", train, sub)[0]}
    for run in args.runs:
        rd = paths.RUNS_DIR / "phase3" / run
        if not (rd / "config.json").exists():
            print(f"(skipping {run}: not found in {rd}; unpack <run>_results.zip with scripts/import_results_zip.py)")
            continue
        tag = short_model(rd)
        subset_methods.update(run_methods(rd, "subset", prefix=f"{tag} "))
        test_methods.update(run_methods(rd, "test", prefix=f"{tag} "))
        for lab, nice in (("base", "base"), ("finetuned", "fine-tuned")):
            p = rd / "eval" / lab / "subset" / "predictions.jsonl"
            if p.exists():
                preds = {json.loads(l)["id"]: json.loads(l) for l in p.read_text().splitlines()}
                rows_for_breakdown[f"{tag} {nice}"] = [preds[i]["scores"] for i in sub_ids]
    for d in sorted((paths.REPO_ROOT / "results" / "phase3").glob("groq_*")):
        p = d / "predictions.jsonl"
        if p.exists():
            preds = {json.loads(l)["id"]: json.loads(l) for l in p.read_text().splitlines()}
            if all(i in preds for i in sub_ids):
                rows_for_breakdown[f"Groq {d.name.removeprefix('groq_').replace('_', '/', 1)}"] = [preds[i]["scores"] for i in sub_ids]

    def bd_md(by: str, title: str) -> str:
        per = {name: breakdown(sub, rows, by) for name, rows in rows_for_breakdown.items()}
        keys = sorted(next(iter(per.values())))
        n = {k: next(iter(per.values()))[k]["n"] for k in keys}
        lines = [f"**{title}** (cells: tie-aware top-1 / improvement rate / mean regret)", "",
                 "| method | " + " | ".join(f"{k} (n={n[k]})" for k in keys) + " |", "|" + "---|" * (len(keys) + 1)]
        for name, b in per.items():
            lines.append(f"| {name} | " + " | ".join(f"{b[k]['top1']:.2f} / {b[k]['improve_rate']:.2f} / {b[k]['mean_regret']:.3f}" for k in keys) + " |")
        return "\n".join(lines)

    md = ["# Phase 3 results", "",
          "All numbers are lookups into the simulator-precomputed outcomes of every action (no model is ever re-simulated). "
          "95% CIs are bootstrap intervals over states (2000 resamples).", "",
          f"## 1. Eval subset ({len(sub)} test examples, stratified by step; the main comparison)", "",
          markdown_table(subset_methods), "",
          f"## 2. Full test split ({len(test)} examples; no Groq)", "", markdown_table(test_methods), "",
          "## 3. Where does each method win or lose? (eval subset)", "",
          bd_md("step_index", "By step index (0 = the first failing design, 1-3 = after greedy moves)"), "",
          bd_md("largest_shortfall", "By largest shortfall of the state"), ""]
    out = paths.REPO_ROOT / "results"
    (out / "phase3_results.md").write_text("\n".join(md))
    (out / "phase3_results.json").write_text(json.dumps({"eval_subset": subset_methods, "full_test": test_methods,
                                                          "n_subset": len(sub), "n_test": len(test)}, indent=1) + "\n")
    print("\n".join(md))


if __name__ == "__main__":
    main()
