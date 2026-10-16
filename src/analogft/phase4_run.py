"""Helpers for the Phase 4 Colab notebook: chunked, resumable expert-iteration rollouts."""
from __future__ import annotations

import json
import time
from pathlib import Path

from .agent import SimPool, run_agent
from .policies import Policy
from .tracing import TraceWriter, read_traces


def run_rollouts(policy: Policy, episodes: list[dict], out_dir: Path, sim: SimPool, *, samples: int,
                 chunk_size: int = 176, log=print) -> None:
    """Sampling rollouts with recovery, in chunks of `chunk_size` episodes; finished chunks are skipped on a rerun.

    Each chunk keeps full states (needed to build training examples). Prints a time estimate after the first new chunk.
    """
    out_dir = Path(out_dir)
    chunks = [episodes[i:i + chunk_size] for i in range(0, len(episodes), chunk_size)]
    done_s, new_chunks = 0.0, 0
    for i, ch in enumerate(chunks):
        d = out_dir / f"chunk_{i:02d}"
        if (d / "episodes.jsonl").exists():     # written last, so its presence means the chunk finished
            log(f"[rollouts] chunk {i + 1}/{len(chunks)} already done, skipping")
            continue
        t0 = time.time()
        tw = TraceWriter(d, keep_state_full=True)
        run_agent(ch, policy, recovery=True, sim=sim, trace=tw, run_id=f"rollout{i:02d}", samples=samples,
                  log=lambda m: log("  " + m))
        dt = time.time() - t0
        done_s += dt
        new_chunks += 1
        left = sum(1 for j in range(i + 1, len(chunks)) if not (out_dir / f"chunk_{j:02d}" / "episodes.jsonl").exists())
        solved = sum(e["solved"] for e in tw.episodes)
        log(f"[rollouts] chunk {i + 1}/{len(chunks)}: {len(tw.episodes)} rollouts, {solved} solved, {dt:.0f}s; "
            f"about {left * done_s / new_chunks / 60:.1f} min left")


def load_rollouts(out_dir: Path) -> tuple[list[dict], list[dict]]:
    steps, eps = [], []
    for d in sorted(Path(out_dir).glob("chunk_*")):
        if (d / "episodes.jsonl").exists():
            s, e = read_traces(d)
            steps += s
            eps += e
    return steps, eps


def write_rollouts_summary(out_dir: Path, episodes: list[dict], path: Path, k: int, temperature: float) -> dict:
    n = len(episodes)
    summ = {"rollouts": n, "solved": sum(e["solved"] for e in episodes), "samples_per_episode": k,
            "temperature": temperature, "base_episodes": len({e["base_episode_id"] for e in episodes}),
            "success_rate": sum(e["solved"] for e in episodes) / n if n else None,
            "mean_steps_to_success": (sum(e["steps_to_success"] for e in episodes if e["solved"]) /
                                      max(1, sum(e["solved"] for e in episodes)))}
    Path(path).write_text(json.dumps(summ, indent=1) + "\n")
    return summ
