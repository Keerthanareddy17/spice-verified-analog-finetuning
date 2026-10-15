"""Tie-breaking for the training label (docs/DECISIONS.md D16).

Several actions can be equally good (typically each fully solves the spec). Instead of
taking the lowest action id, the label is the tied action whose resulting design has the
largest margin beyond the spec (`shortfall.margin`), i.e. the most robust fix. If margins
are also tied, fall back to action-id order.
"""
from __future__ import annotations

import json

from .actions import ACTION_IDS
from .prompting import SYSTEM_PROMPT, format_prompt, format_response
from .shortfall import margin, n_unsaturated, unsaturated

TIE_DECIMALS = 8  # improvements are stored rounded to 6 decimals, so equal means equal


def rank_actions(outcomes: dict[str, dict], spec: dict) -> list[str]:
    """Action ids, best first: by improvement, then larger margin, then action-id order."""
    def key(a: str):
        o = outcomes[a]
        return (-round(o["improvement"], TIE_DECIMALS), -margin(spec, o["metrics"]), ACTION_IDS.index(a))
    return sorted(outcomes, key=key)


def tied_best(outcomes: dict[str, dict], ranking: list[str]) -> list[str]:
    top = outcomes[ranking[0]]["improvement"]
    tied = [a for a in ranking if abs(outcomes[a]["improvement"] - top) < 1e-9]
    return tied if len(tied) > 1 else []


def assistant_message(rec: dict, action: str) -> str:
    """The reply text for `action`, rebuilt from the stored before/after metrics."""
    before = {"metrics": rec["metrics"], "n_unsat": n_unsaturated(rec["regions"]),
              "unsat": unsaturated(rec["regions"])}
    return format_response(action, before, rec["action_outcomes"][action], rec["spec"])


def relabel_record(rec: dict) -> dict:
    """Return a copy with ranking, label, tied_best, label_solves and the assistant message recomputed."""
    out = dict(rec)
    ranking = rank_actions(rec["action_outcomes"], rec["spec"])
    best = ranking[0]
    out.update(ranking=ranking, label_action=best, tied_best=tied_best(rec["action_outcomes"], ranking),
               best_improves=rec["action_outcomes"][best]["improvement"] > 0,
               label_solves=rec["action_outcomes"][best]["distance_after"] == 0.0)
    out["messages"] = [{"role": "system", "content": SYSTEM_PROMPT},
                       {"role": "user", "content": format_prompt(rec)},
                       {"role": "assistant", "content": assistant_message(rec, best)}]
    return out
