"""Episode loading, agent metrics (with bootstrap CIs) and saving of agent runs."""
from __future__ import annotations

import json
import random
import statistics
from pathlib import Path

from . import paths
from .agent import SimPool, run_agent
from .dataset import read_jsonl
from .evaluation import bootstrap_mean_ci
from .policies import Policy
from .tracing import TraceWriter, count_classes, count_recoveries, read_traces

MAX_STEPS = 8


def load_episodes(split: str = "test", name: str = "phase2") -> list[dict]:
    return read_jsonl(paths.DATA_DIR / name / f"episodes_{split}.jsonl")


def seeded_subset(episodes: list[dict], n: int, seed: int = 0) -> list[dict]:
    """A fixed random subset (sorted by id), for runs that cannot afford every episode (Groq)."""
    ids = sorted(e["id"] for e in episodes)
    pick = set(random.Random(seed).sample(ids, min(n, len(ids))))
    return [e for e in episodes if e["id"] in pick]


def summarize_agent(steps: list[dict], episodes: list[dict]) -> dict:
    """Metrics of one agent run. `episodes` are episode records, `steps` step records."""
    n = len(episodes)
    solved = [e for e in episodes if e["solved"]]
    succ = [float(e["solved"]) for e in episodes]
    sts = [e["steps_to_success"] for e in solved]
    ref_solved = [e["reference_len"] for e in solved]
    n_steps = len(steps)
    by_budget = {k: sum(1 for e in solved if e["steps_to_success"] <= k) / n if n else float("nan")
                 for k in range(1, MAX_STEPS + 1)}
    return {
        "n_episodes": n, "success_rate": sum(succ) / n if n else float("nan"),
        "success_ci": bootstrap_mean_ci(succ),
        "outcomes": {o: sum(e["outcome"] == o for e in episodes) for o in ("solved", "budget_exhausted", "gave_up")},
        "median_steps_to_success": statistics.median(sts) if sts else None,
        "mean_steps_to_success": sum(sts) / len(sts) if sts else None,
        "mean_reference_len_solved": sum(ref_solved) / len(ref_solved) if ref_solved else None,
        "mean_reference_len_all": sum(e["reference_len"] for e in episodes) / n if n else None,
        "steps_over_reference": (sum(sts) / sum(ref_solved)) if sts else None,
        "mean_final_distance": sum(e["final_distance"] for e in episodes) / n if n else None,
        "final_distance_ci": bootstrap_mean_ci([e["final_distance"] for e in episodes]),
        "mean_best_distance": sum(e["best_distance"] for e in episodes) / n if n else None,
        "mean_sims": sum(e["sims"] for e in episodes) / n if n else None,
        "invalid_output_rate": sum(1 for s in steps if s["error"]) / n_steps if n_steps else 0.0,
        "recoveries_per_episode": sum(sum(e["recoveries"].values()) for e in episodes) / n if n else 0.0,
        "recoveries": count_recoveries(episodes), "failure_classes": count_classes(episodes),
        "success_by_budget": by_budget,
        "mean_tokens_per_step": (sum(s["tokens"] or 0 for s in steps) / n_steps) if n_steps and any(s["tokens"] for s in steps) else None,
    }


def run_and_save(out_dir: Path, run_id: str, policy: Policy, episodes: list[dict], *, recovery: bool, sim: SimPool,
                 samples: int = 1, fallback: Policy | None = None, keep_state_full: bool = False, log=print,
                 skip_if_done: bool = False, max_steps: int = MAX_STEPS) -> dict:
    """Run an agent on episodes and write steps.jsonl, episodes.jsonl and metrics.json into out_dir."""
    out_dir = Path(out_dir)
    if skip_if_done and (out_dir / "metrics.json").exists():
        log(f"[{run_id}] already done in {out_dir}, skipping")
        return json.loads((out_dir / "metrics.json").read_text())
    tw = TraceWriter(out_dir, keep_state_full=keep_state_full)
    run_agent(episodes, policy, recovery=recovery, sim=sim, trace=tw, run_id=run_id, samples=samples,
              fallback=fallback, log=log, max_steps=max_steps)
    m = {"run_id": run_id, "policy": policy.name, "recovery": recovery, "samples": samples,
         **summarize_agent(tw.steps, tw.episodes)}
    (out_dir / "metrics.json").write_text(json.dumps(m, indent=1) + "\n")
    return m


def fmt_agent(m: dict) -> str:
    lo, hi = m["success_ci"]
    ms = m["median_steps_to_success"]
    return (f"n={m['n_episodes']} success={m['success_rate']:.3f} [{lo:.3f}, {hi:.3f}] median_steps={ms} "
            f"final_dist={m['mean_final_distance']:.3f} sims/ep={m['mean_sims']:.1f} invalid={m['invalid_output_rate']:.3f} "
            f"recoveries/ep={m['recoveries_per_episode']:.2f}")
