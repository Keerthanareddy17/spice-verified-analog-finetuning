"""One round of expert iteration (a simple policy-improvement RL step with the simulator as the reward).

1. Roll the current policy out (sampling, temperature > 0) on training episodes.
2. The simulator decides success: keep only episodes that reached the spec.
3. From those, keep only steps that improved spec_distance (no detours), that the model chose itself (no rules
   fallback), and that are new (not an exact duplicate of a Phase 2 training example).
4. Mix with the original Phase 2 train set (prevents forgetting) and fine-tune further, from the Phase 3 adapter.
"""
from __future__ import annotations

import json
import random
from collections import Counter
from pathlib import Path

from .dataset import read_jsonl, write_jsonl
from .prompting import SYSTEM_PROMPT, format_prompt, format_response
from .shortfall import n_unsaturated, unsaturated


def _example(step: dict, ep_id: str) -> dict:
    st = step["state_full"]
    before = {"metrics": st["metrics"], "n_unsat": n_unsaturated(st["regions"]), "unsat": unsaturated(st["regions"])}
    after = step["after"]
    return {"id": f"rl_{ep_id}_k{step['step']}", "source": "expert_iteration", "step_index": step["step"],
            "label_action": step["action"], "improvement": step["improvement"],
            "messages": [{"role": "system", "content": SYSTEM_PROMPT},
                         {"role": "user", "content": format_prompt(st)},
                         {"role": "assistant", "content": format_response(step["action"], before, after, st["spec"])}]}


def select_steps(steps: list[dict], episodes: list[dict]) -> tuple[list[dict], dict]:
    """Candidate examples from rollout traces plus a breakdown of why steps were dropped."""
    solved = {e["episode_id"] for e in episodes if e["solved"]}
    drops: Counter = Counter()
    out = []
    for s in steps:
        if s["episode_id"] not in solved:
            drops["episode_not_solved"] += 1
        elif s["action"] is None or s["after"] is None:
            drops["no_applied_action"] += 1
        elif s["used_fallback"]:
            drops["rules_fallback_step"] += 1
        elif s["improvement"] <= 0:
            drops["no_improvement_detour"] += 1
        elif "state_full" not in s:
            drops["no_state_saved"] += 1
        else:
            out.append(_example(s, s["episode_id"]))
    return out, dict(drops)


def build_rl_dataset(train_records: list[dict], rollout_steps: list[dict], rollout_episodes: list[dict],
                     out_path: Path | None = None, seed: int = 0) -> tuple[list[dict], dict]:
    """Returns (mixed training records, stats). Writes the mixed set to out_path if given."""
    cand, drops = select_steps(rollout_steps, rollout_episodes)
    train_pairs = {(r["messages"][1]["content"], r["label_action"]) for r in train_records}
    seen_prompt: dict[str, dict] = {}
    n_dup_train = 0
    for ex in cand:
        key = ex["messages"][1]["content"]
        if (key, ex["label_action"]) in train_pairs:
            n_dup_train += 1
            continue
        best = seen_prompt.get(key)                 # one label per prompt: the largest improvement
        if best is None or ex["improvement"] > best["improvement"]:
            seen_prompt[key] = ex
    new = list(seen_prompt.values())
    mixed = list(train_records) + new
    random.Random(seed).shuffle(mixed)
    n_ep = len(rollout_episodes)
    n_solved = sum(e["solved"] for e in rollout_episodes)
    stats = {"rollouts": n_ep, "rollouts_solved": n_solved, "rollout_success_rate": n_solved / n_ep if n_ep else None,
             "steps_total": len(rollout_steps), "candidate_steps": len(cand), "dropped": drops,
             "duplicates_of_phase2_train": n_dup_train, "new_examples": len(new),
             "train_examples_before": len(train_records), "train_examples_after": len(mixed),
             "new_by_step_index": dict(sorted(Counter(e["step_index"] for e in new).items())),
             "new_by_action": dict(Counter(e["label_action"] for e in new).most_common())}
    if out_path:
        write_jsonl(Path(out_path), mixed)
        Path(out_path).with_suffix(".stats.json").write_text(json.dumps(stats, indent=1) + "\n")
    return mixed, stats
