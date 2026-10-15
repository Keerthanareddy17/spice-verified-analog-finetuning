"""Results tables for Phase 3: one row per method, with 95% CIs on the headline metrics.

Non-model methods are recomputed from the dataset; model methods (Groq, base, fine-tuned) are read from the
`metrics.json` / `predictions.jsonl` files written by `harness.save_evaluation`.
"""
from __future__ import annotations

import json
from pathlib import Path

from . import paths
from .dataset import read_jsonl
from .harness import SUBSET_FILE, score_method, select

PHASE3_RESULTS = paths.REPO_ROOT / "results" / "phase3"  # committed copy (also what Colab clones)
NON_MODEL = ("random", "majority", "textbook_rules")
NAMES = {"random": "random", "majority": "majority action", "textbook_rules": "textbook rules"}


def load_phase2(name: str = "phase2") -> tuple[list[dict], list[dict], list[dict]]:
    d = paths.DATA_DIR / name
    return tuple(read_jsonl(d / f"{s}.jsonl") for s in ("train", "val", "test"))  # type: ignore[return-value]


def subset_ids() -> list[str]:
    return json.loads((PHASE3_RESULTS / SUBSET_FILE).read_text())["ids"]


def non_model_summaries(train: list[dict], records: list[dict]) -> dict[str, dict]:
    return {NAMES[m]: score_method(m, train, records)[1] for m in NON_MODEL}


def _cell(m: dict, k: str, ci: bool = True) -> str:
    if ci and k in m.get("ci", {}):
        lo, hi = m["ci"][k]
        return f"{m[k]:.3f} [{lo:.3f}, {hi:.3f}]"
    return f"{m[k]:.3f}"


def markdown_table(methods: dict[str, dict]) -> str:
    """methods: name -> metrics dict (as from summarize_scores / metrics.json)."""
    head = "| method | n | valid | top-1 tie-aware (95% CI) | top-1 exact | top-3 | improvement rate (95% CI) | mean regret (95% CI) |"
    lines = [head, "|" + "---|" * 8]
    for name, m in methods.items():
        lines.append(f"| {name} | {m['n']} | {m['valid_rate']:.3f} | {_cell(m, 'top1')} | {m['top1_exact']:.3f} | "
                     f"{m['top3']:.3f} | {_cell(m, 'improve_rate')} | {_cell(m, 'mean_regret')} |")
    return "\n".join(lines)


def load_metrics(path: Path) -> dict | None:
    return json.loads(path.read_text()) if path.exists() else None


def groq_runs() -> dict[str, dict]:
    """label -> metrics for every results/phase3/groq_*/metrics.json."""
    out = {}
    for d in sorted(PHASE3_RESULTS.glob("groq_*")):
        m = load_metrics(d / "metrics.json")
        if m:
            out[f"Groq {d.name.removeprefix('groq_').replace('_', '/', 1)}" + ("" if m["n"] == len(subset_ids()) else f" (n={m['n']})")] = m
    return out


def run_methods(run_dir: Path, split: str, labels=("base", "finetuned"), prefix: str = "") -> dict[str, dict]:
    """Metrics of the model evaluations stored under run_dir/eval/<label>/<split>/metrics.json."""
    out = {}
    for lab in labels:
        m = load_metrics(Path(run_dir) / "eval" / lab / split / "metrics.json")
        if m:
            out[f"{prefix}{'base model (untrained)' if lab == 'base' else 'fine-tuned'}"] = m
    return out


def comparison_tables(run_dir: Path, run_label: str, data_name: str = "phase2") -> dict[str, str]:
    """{'subset': md, 'test': md} using the committed Groq results and the run's evals."""
    train, _, test = load_phase2(data_name)
    sub = select(test, subset_ids())
    t_sub = {**non_model_summaries(train, sub), **groq_runs(), **run_methods(run_dir, "subset", prefix=f"{run_label} ")}
    t_test = {**non_model_summaries(train, test), **run_methods(run_dir, "test", prefix=f"{run_label} ")}
    return {"subset": markdown_table(t_sub), "test": markdown_table(t_test)}
