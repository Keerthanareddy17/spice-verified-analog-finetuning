"""Baselines that need no GPU: random, majority label, and textbook rules.

Textbook rules (rationale in docs/DECISIONS.md D12): find the largest normalized
shortfall (same units as the spec distance) and apply one fixed move for it.
"""
from __future__ import annotations

from collections import Counter

from .evaluation import evaluate, evaluate_random
from .shortfall import shortfall_terms, unsaturated

# spec shortfall -> action
SPEC_RULES = {"pm": "cc_up", "ugf": "w_in_up", "gain": "l_load_up", "power": "ibias_down"}
# unsaturated device -> action
DEVICE_RULES = {"M1": "w_in_up", "M2": "w_in_up", "M5": "w_in_up",
                "M3": "l_load_down", "M4": "l_load_down",
                "M6": "w_cs_up", "M7": "ibias_down", "M8": "ibias_down"}


def textbook_pick(state: dict) -> str | None:
    """Fix the largest shortfall with its fixed rule; fall back to the next largest if clipped."""
    terms = shortfall_terms(state["spec"], state["metrics"], len(unsaturated(state["regions"])))
    unsat = unsaturated(state["regions"])
    for term, value in sorted(terms.items(), key=lambda kv: -kv[1]):
        if value <= 0:
            break
        if term == "sat":
            cands = [DEVICE_RULES[d.upper()] for d in sorted(unsat)]
        else:
            cands = [SPEC_RULES.get(term)]
        for c in cands:
            if c in state["available_actions"]:
                return c
    return None


def majority_label(train_records: list[dict]) -> str:
    return Counter(r["label_action"] for r in train_records).most_common(1)[0][0]


def score_baselines(train: list[dict], splits: dict[str, list[dict]]) -> dict:
    """{baseline: {split: metrics}} for random / majority / textbook rules."""
    maj = majority_label(train)
    out: dict = {"_majority_action": maj}
    for name, records in splits.items():
        out.setdefault("random", {})[name] = evaluate_random(records)
        out.setdefault("majority", {})[name] = evaluate(
            records, [maj if maj in r["available_actions"] else None for r in records])
        out.setdefault("textbook_rules", {})[name] = evaluate(records, [textbook_pick(r) for r in records])
    return out
