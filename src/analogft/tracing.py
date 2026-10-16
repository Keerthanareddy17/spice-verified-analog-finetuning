"""Observability for the agent: failure taxonomy, step/episode trace records, JSONL writer.

One JSONL line per agent step (`steps.jsonl`) and one per episode (`episodes.jsonl`). The schema is
documented on `step_record` and `episode_record`; `scripts/make_phase4_table.py` and the example-trace
writer read only these files.
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

# ----- failure taxonomy -------------------------------------------------------------------
INVALID_OUTPUT = "INVALID_OUTPUT"            # not parseable JSON / unknown action id / API error
UNAVAILABLE_ACTION = "UNAVAILABLE_ACTION"    # a real action id that is not in this state's list (incl. blocked ones)
SIM_FAILURE = "SIM_FAILURE"                  # the simulation of the new design gave no complete metrics
LOOP = "LOOP"                                # the move returns to a design already visited in this episode
NO_PROGRESS = "NO_PROGRESS"                  # 3 consecutive steps without improving the best distance
BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"        # step budget used up without meeting the spec
FAILURE_CLASSES = (INVALID_OUTPUT, UNAVAILABLE_ACTION, SIM_FAILURE, LOOP, NO_PROGRESS, BUDGET_EXHAUSTED)

# ----- recovery paths ---------------------------------------------------------------------
REASK = "reask"                         # invalid/unavailable output: asked again once with the error appended
FALLBACK_RULES = "fallback_rules"       # still invalid after the re-ask: textbook-rules action for that state
LOOP_BLOCK_REASK = "loop_block_reask"   # loop: action blocked at that state, asked again without it in the list
SIM_ROLLBACK = "sim_rollback"           # simulation failed: stay at the previous design, block that action
PROGRESS_ROLLBACK = "progress_rollback" # no progress: back to the best design so far, block the action taken there
RECOVERIES = (REASK, FALLBACK_RULES, LOOP_BLOCK_REASK, SIM_ROLLBACK, PROGRESS_ROLLBACK)

OUTCOMES = ("solved", "budget_exhausted", "gave_up")

_PARSE_ERROR_CLASS = {"no_json": INVALID_OUTPUT, "unknown_action": INVALID_OUTPUT, "api_error": INVALID_OUTPUT,
                      "no_action": INVALID_OUTPUT, "unavailable_action": UNAVAILABLE_ACTION}


def failure_class_of_parse_error(err: str) -> str:
    return _PARSE_ERROR_CLASS.get(err, INVALID_OUTPUT)


def step_record(**kw) -> dict:
    """A step record. Fields:

    run_id, policy, episode_id, step (0-based), recovery (bool), sample (sampling index or 0),
    state {metrics, failing, distance, n_unsat}, raw (the model's first raw answer), error (parse error of the first
    answer or None), action (the action finally applied, None if the step was wasted), failure_classes [..],
    recoveries [{type, detail}], used_fallback (bool), attempts (policy calls this step), sim {metrics, failure, reused},
    distance_before, distance_after, improvement, best_distance, latency_ms (policy time, amortised over the batch),
    tokens (completion+prompt tokens if the backend reports them), after {metrics, n_unsat} and state_full (only when
    the writer keeps full states, used to build the expert-iteration dataset).
    """
    return kw


def episode_record(**kw) -> dict:
    """An episode record. Fields:

    run_id, policy, episode_id, group_id, sample, recovery, outcome (solved|budget_exhausted|gave_up), solved,
    steps (steps taken), steps_to_success (or None), reference_len (inverse lattice moves from start to target),
    sims (new designs simulated), start_distance, final_distance, best_distance, failure_classes {class: count},
    recoveries {type: count}, invalid_outputs, policy_calls.
    """
    return kw


class TraceWriter:
    """Collects step and episode records; writes `steps.jsonl` and `episodes.jsonl` into out_dir."""

    def __init__(self, out_dir: Path | None = None, keep_state_full: bool = False):
        self.out_dir = Path(out_dir) if out_dir else None
        self.keep_state_full = keep_state_full
        self.steps: list[dict] = []
        self.episodes: list[dict] = []

    def step(self, rec: dict) -> None:
        if not self.keep_state_full:
            rec = {k: v for k, v in rec.items() if k != "state_full"}
        self.steps.append(rec)

    def episode(self, rec: dict) -> None:
        self.episodes.append(rec)

    def flush(self) -> None:
        if not self.out_dir:
            return
        self.out_dir.mkdir(parents=True, exist_ok=True)
        for name, rows in (("steps.jsonl", self.steps), ("episodes.jsonl", self.episodes)):
            (self.out_dir / name).write_text("".join(json.dumps(r, separators=(",", ":")) + "\n" for r in rows))


def read_traces(out_dir: Path) -> tuple[list[dict], list[dict]]:
    out_dir = Path(out_dir)
    rd = lambda n: [json.loads(l) for l in (out_dir / n).read_text().splitlines() if l.strip()]
    return rd("steps.jsonl"), rd("episodes.jsonl")


def count_classes(episodes: list[dict]) -> dict[str, int]:
    """Total count of each failure class over episodes (BUDGET_EXHAUSTED counted once per exhausted episode)."""
    c: Counter = Counter()
    for e in episodes:
        c.update(e["failure_classes"])
    return {k: c.get(k, 0) for k in FAILURE_CLASSES}


def count_recoveries(episodes: list[dict]) -> dict[str, int]:
    c: Counter = Counter()
    for e in episodes:
        c.update(e["recoveries"])
    return {k: c.get(k, 0) for k in RECOVERIES}
