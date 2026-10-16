"""Lookup-based scoring of action choices (used by baselines now, models in Phase 3).

A record is a labeled state from the dataset: label_action, ranking (action ids, best
first) and action_outcomes (id -> {improvement, ...}). A pick is an action id, or None
for an invalid output. An invalid pick counts as a no-move: wrong for top-1/top-3 and
improvement rate, and improvement 0 for regret.

Ties: several actions can be equally good (typically when more than one of them
fully solves the spec). `top1` and `top3` are tie-aware: a pick is as good as the best
if its improvement equals the best improvement, and its rank is 1 + the number of
actions that are strictly better. `top1_exact` additionally requires the exact label id.
"""
from __future__ import annotations

TOL = 1e-9


def best_improvement(record: dict) -> float:
    return record["action_outcomes"][record["label_action"]]["improvement"]


def _rank(record: dict, imp: float) -> int:
    return 1 + sum(o["improvement"] > imp + TOL for o in record["action_outcomes"].values())


def score_pick(record: dict, pick: str | None) -> dict:
    """Per-state scores for one pick."""
    valid = pick is not None and pick in record["action_outcomes"]
    imp = record["action_outcomes"][pick]["improvement"] if valid else 0.0
    rank = _rank(record, imp) if valid else None
    return {"valid": valid, "top1": valid and rank == 1, "top1_exact": valid and pick == record["label_action"],
            "top3": valid and rank <= 3, "improves": valid and imp > 0,
            "regret": best_improvement(record) - imp}


def _mean(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else float("nan")


_OUT = {"valid": "valid_rate", "top1": "top1", "top1_exact": "top1_exact", "top3": "top3",
        "improves": "improve_rate", "regret": "mean_regret"}


def _aggregate(per_state: list[list[dict]]) -> dict:
    """Average each score over actions (inner list) then over states."""
    return {"n": len(per_state), **{name: _mean([_mean([x[k] for x in per]) for per in per_state])
                                    for k, name in _OUT.items()}}


def evaluate(records: list[dict], picks: list[str | None]) -> dict:
    """valid_rate, top1, top1_exact, top3, improve_rate, mean_regret over every record."""
    assert len(records) == len(picks)
    return _aggregate([[score_pick(r, p)] for r, p in zip(records, picks)])


def evaluate_random(records: list[dict]) -> dict:
    """Exact expectation of a uniform-random pick over each state's available actions."""
    return _aggregate([[score_pick(r, a) for a in r["available_actions"]] for r in records])


# ----- per-state scores, confidence intervals and error analysis (Phase 3) ---------------

import math
import random

from .shortfall import n_unsaturated, shortfall_terms

HEADLINE = ("top1", "improve_rate", "mean_regret")
SCORE_KEYS = {"valid": "valid_rate", "top1": "top1", "top1_exact": "top1_exact", "top3": "top3",
              "improves": "improve_rate", "regret": "mean_regret"}


def per_state_scores(records: list[dict], picks: list[str | None]) -> list[dict]:
    """One dict of float scores per state (keys of SCORE_KEYS values)."""
    assert len(records) == len(picks)
    return [{SCORE_KEYS[k]: float(v) for k, v in score_pick(r, p).items()} for r, p in zip(records, picks)]


def per_state_scores_random(records: list[dict]) -> list[dict]:
    """Expected scores of a uniform-random pick, per state."""
    out = []
    for r in records:
        per = [score_pick(r, a) for a in r["available_actions"]]
        out.append({SCORE_KEYS[k]: _mean([float(x[k]) for x in per]) for k in SCORE_KEYS})
    return out


def summarize_scores(rows: list[dict], n_boot: int = 2000, seed: int = 0) -> dict:
    """Mean of each score, plus a bootstrap 95% CI (resampling states) for the headline metrics.

    Result: {"n", <metric>: mean, ..., "ci": {metric: [lo, hi]}}.
    """
    n = len(rows)
    out: dict = {"n": n}
    cols = list(SCORE_KEYS.values())
    for c in cols:
        out[c] = _mean([r[c] for r in rows])
    rng = random.Random(seed)
    boots = {c: [] for c in HEADLINE}
    for _ in range(n_boot if n else 0):
        sample = [rows[rng.randrange(n)] for _ in range(n)]
        for c in HEADLINE:
            boots[c].append(sum(r[c] for r in sample) / n)
    out["ci"] = {}
    for c, xs in boots.items():
        xs.sort()
        out["ci"][c] = [xs[int(0.025 * len(xs))], xs[min(len(xs) - 1, int(0.975 * len(xs)))]] if xs else [math.nan] * 2
    return out


def largest_shortfall(record: dict) -> str:
    """Which part of the spec is furthest off: gain, ugf, pm, power or sat (device out of saturation)."""
    terms = shortfall_terms(record["spec"], record["metrics"], n_unsaturated(record["regions"]))
    return max(terms, key=terms.get)


def breakdown(records: list[dict], rows: list[dict], by: str) -> dict:
    """Mean scores per group. `by` is "step_index" or "largest_shortfall". Includes n per group."""
    groups: dict = {}
    for r, s in zip(records, rows):
        key = str(r["step_index"]) if by == "step_index" else largest_shortfall(r)
        groups.setdefault(key, []).append(s)
    out = {}
    for key in sorted(groups):
        g = groups[key]
        out[key] = {"n": len(g), **{c: _mean([x[c] for x in g]) for c in SCORE_KEYS.values()}}
    return out


def bootstrap_mean_ci(values: list[float], n_boot: int = 2000, seed: int = 0) -> list[float]:
    """Percentile 95% CI of the mean (resampling items)."""
    n = len(values)
    if not n:
        return [math.nan, math.nan]
    rng = random.Random(seed)
    means = sorted(sum(values[rng.randrange(n)] for _ in range(n)) / n for _ in range(n_boot))
    return [means[int(0.025 * n_boot)], means[min(n_boot - 1, int(0.975 * n_boot))]]
