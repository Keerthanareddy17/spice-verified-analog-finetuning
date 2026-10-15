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
