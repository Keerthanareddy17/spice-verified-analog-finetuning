"""Summary statistics of a built dataset (printed after a build, used by the dataset card)."""
from __future__ import annotations

import json
from collections import Counter

import numpy as np

from .prompting import estimate_tokens


def _dist(xs: list[float]) -> dict:
    a = np.asarray(xs, dtype=float)
    q = np.percentile(a, [5, 25, 50, 75, 95])
    return {"min": float(a.min()), "p5": q[0], "p25": q[1], "median": q[2], "p75": q[3],
            "p95": q[4], "max": float(a.max()), "mean": float(a.mean())}


def summarize(records: list[dict], episodes: list[dict]) -> dict:
    n = len(records)
    labels = Counter(r["label_action"] for r in records)
    user_tok = [estimate_tokens(r["messages"][1]["content"]) for r in records]
    full_tok = [estimate_tokens(r["messages"][0]["content"] + r["messages"][1]["content"]) for r in records]
    reply_tok = [estimate_tokens(r["messages"][2]["content"]) for r in records]
    n_out = [len(r["action_outcomes"]) for r in records]
    outs = [o for r in records for o in r["action_outcomes"].values()]
    return {
        "n_states": n, "n_episodes": len(episodes),
        "states_per_split": dict(Counter(r["split"] for r in records)),
        "episodes_per_split": dict(Counter(e["split"] for e in episodes)),
        "groups_per_split": {s: len({r["group_id"] for r in records if r["split"] == s})
                             for s in ("train", "val", "test")},
        "label_counts": dict(labels.most_common()),
        "top_label_fraction": labels.most_common(1)[0][1] / n,
        "best_improves_fraction": sum(r["best_improves"] for r in records) / n,
        "label_solves_fraction": sum(r["label_solves"] for r in records) / n,
        "tie_fraction": sum(bool(r["tied_best"]) for r in records) / n,
        "step_index_counts": dict(sorted(Counter(r["step_index"] for r in records).items())),
        "distance": _dist([r["distance"] for r in records]),
        "start_distance": _dist([e["start_distance"] for e in episodes]),
        "actions_per_state": _dist(n_out),
        "improvement_all_actions": _dist([o["improvement"] for o in outs]),
        "failed_sim_action_fraction": sum(o["metrics"].get("pm_deg") is None for o in outs) / len(outs),
        "unsaturated_action_fraction": sum(o["failure"] == "DEVICE_NOT_SATURATED" for o in outs) / len(outs),
        "improving_action_fraction": sum(o["improvement"] > 0 for o in outs) / len(outs),
        "user_tokens": _dist(user_tok), "system_plus_user_tokens": _dist(full_tok),
        "assistant_tokens": _dist(reply_tok),
        "assistant_words_max": max(len(json.loads(r["messages"][2]["content"])["reason"].split())
                                   for r in records),
    }
