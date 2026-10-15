"""Model-agnostic evaluation harness: eval subset, scoring predictions, saving predictions + metrics."""
from __future__ import annotations

import json
import random
from collections import Counter
from pathlib import Path

from .baselines import majority_label, textbook_pick
from .evaluation import (breakdown, largest_shortfall, per_state_scores, per_state_scores_random,
                         summarize_scores)

SUBSET_FILE = "eval_subset_ids.json"


def make_eval_subset(records: list[dict], n: int = 150, seed: int = 0) -> list[str]:
    """Seeded sample of n record ids, stratified by step_index (proportional, largest remainder)."""
    by_step: dict[int, list[str]] = {}
    for r in sorted(records, key=lambda r: r["id"]):
        by_step.setdefault(r["step_index"], []).append(r["id"])
    total = sum(len(v) for v in by_step.values())
    quota = {s: n * len(v) / total for s, v in by_step.items()}
    alloc = {s: int(q) for s, q in quota.items()}
    for s in sorted(quota, key=lambda s: quota[s] - alloc[s], reverse=True)[: n - sum(alloc.values())]:
        alloc[s] += 1
    rng = random.Random(seed)
    ids: list[str] = []
    for s in sorted(by_step):
        ids += rng.sample(by_step[s], alloc[s])
    return sorted(ids)


def select(records: list[dict], ids: list[str]) -> list[dict]:
    want = set(ids)
    out = [r for r in records if r["id"] in want]
    assert len(out) == len(want), "some subset ids are missing from the records"
    return out


def score_picks(records: list[dict], picks: list[str | None] | None, *, random_baseline: bool = False) -> tuple[list[dict], dict]:
    """(per-state score rows, summary with CIs). picks=None with random_baseline=True gives the exact random expectation."""
    rows = per_state_scores_random(records) if random_baseline else per_state_scores(records, picks)
    return rows, summarize_scores(rows)


def method_picks(name: str, train: list[dict], records: list[dict]) -> list[str | None] | None:
    """Picks for the no-GPU methods (None for random, which is scored as an expectation)."""
    if name == "random":
        return None
    if name == "majority":
        maj = majority_label(train)
        return [maj if maj in r["available_actions"] else None for r in records]
    if name == "textbook_rules":
        return [textbook_pick(r) for r in records]
    raise ValueError(name)


def score_method(name: str, train: list[dict], records: list[dict]) -> tuple[list[dict], dict]:
    picks = method_picks(name, train, records)
    return score_picks(records, picks, random_baseline=picks is None)


def save_evaluation(out_dir: Path, records: list[dict], preds: list, label: str = "") -> dict:
    """Score Prediction objects and write predictions.jsonl + metrics.json into out_dir. Returns the metrics dict."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    rows, summary = score_picks(records, [p.action for p in preds])
    lines = []
    for r, p, s in zip(records, preds, rows):
        lines.append({"id": r["id"], "step_index": r["step_index"], "largest_shortfall": largest_shortfall(r),
                      "raw": p.raw, "action": p.action, "error": p.error, "label_action": r["label_action"],
                      "scores": s, "meta": p.meta})
    (out_dir / "predictions.jsonl").write_text("".join(json.dumps(x) + "\n" for x in lines))
    toks = [p.meta.get("total_tokens") or 0 for p in preds]
    metrics = {"label": label, **summary,
               "errors": dict(Counter(p.error or "ok" for p in preds)),
               "n_truncated": sum(bool(p.meta.get("truncated")) for p in preds),
               "mean_total_tokens": sum(toks) / len(toks) if toks and any(toks) else None,
               "by_step_index": breakdown(records, rows, "step_index"),
               "by_largest_shortfall": breakdown(records, rows, "largest_shortfall")}
    (out_dir / "metrics.json").write_text(json.dumps(metrics, indent=2) + "\n")
    return metrics


def fmt_metrics(m: dict) -> str:
    """One-line summary with CIs."""
    ci = m["ci"]
    f = lambda k: f"{m[k]:.3f} [{ci[k][0]:.3f}, {ci[k][1]:.3f}]"
    return (f"n={m['n']} valid={m['valid_rate']:.3f} top1(tie-aware)={f('top1')} exact={m['top1_exact']:.3f} "
            f"top3={m['top3']:.3f} improve={f('improve_rate')} regret={f('mean_regret')}")
