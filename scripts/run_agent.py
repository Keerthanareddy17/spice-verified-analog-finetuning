"""Run an agent on the TEST episodes locally (no GPU needed): random, textbook rules, or Groq.

Usage:
  python scripts/run_agent.py --policy rules  [--recovery on|off|both]
  python scripts/run_agent.py --policy random --seed 0
  python scripts/run_agent.py --policy groq --model openai/gpt-oss-120b --n-episodes 30 [--budget TOKENS]
Output: results/phase4/<agent>/{steps.jsonl,episodes.jsonl,metrics.json}
"""
import argparse
import json
import time
from pathlib import Path

from analogft import paths
from analogft.agent import SimPool
from analogft.agent_eval import fmt_agent, load_episodes, run_and_save, seeded_subset
from analogft.policies import LLMPolicy, RandomPolicy, RulesPolicy

OUT = paths.REPO_ROOT / "results" / "phase4"
GROQ_IDS = OUT / "groq_episode_ids.json"


def groq_subset(test: list[dict], n: int) -> list[dict]:
    """Fixed seeded subset of test episodes for the Groq agent (ids saved so every agent can be scored on it)."""
    if GROQ_IDS.exists():
        ids = set(json.loads(GROQ_IDS.read_text())["ids"])
        return [e for e in test if e["id"] in ids]
    sub = seeded_subset(test, n, seed=0)
    OUT.mkdir(parents=True, exist_ok=True)
    GROQ_IDS.write_text(json.dumps({"n": len(sub), "seed": 0, "ids": sorted(e["id"] for e in sub)}, indent=1) + "\n")
    return sub


def preseed_groq_cache(backend, test_records: list[dict]) -> int:
    """Re-key the Phase 3 single-step responses (same prompts at step 0) so they cost no tokens."""
    from analogft.predict import build_messages, messages_key
    old = {}
    f = paths.REPO_ROOT / "results" / "phase3" / f"groq_{backend.model.replace('/', '_')}" / "cache.jsonl"
    if f.exists():
        old = {r["key"]: r for r in map(json.loads, f.read_text().splitlines()) if r["model"] == backend.model}
    n = 0
    for rec in test_records:
        if rec["id"] in old:
            backend.cache.setdefault(messages_key(build_messages(rec)), {**old[rec["id"]], "key": messages_key(build_messages(rec))})
            n += 1
    return n


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--policy", choices=["rules", "random", "groq"], required=True)
    ap.add_argument("--recovery", choices=["on", "off", "both"], default="both")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--model", default="openai/gpt-oss-120b")
    ap.add_argument("--n-episodes", type=int, default=30)
    ap.add_argument("--budget", type=int, default=None, help="Groq: stop after this many tokens")
    args = ap.parse_args()
    test = load_episodes("test")
    modes = {"on": [True], "off": [False], "both": [False, True]}[args.recovery]
    with SimPool() as sim:
        for rec in modes:
            tag = "recovery" if rec else "norecovery"
            if args.policy == "groq":
                from analogft.predict import DailyLimitReached, GroqBackend
                eps = groq_subset(test, args.n_episodes)
                slug = args.model.replace("/", "_")
                name = f"groq_{slug}_{tag}"
                backend = GroqBackend(args.model, cache_path=OUT / name / "cache.jsonl",
                                      reasoning_effort="medium" if "gpt-oss" in args.model else None,
                                      max_tokens=2048, daily_token_budget=args.budget)
                from analogft.dataset import read_jsonl
                seeded = preseed_groq_cache(backend, read_jsonl(paths.DATA_DIR / "phase2" / "test.jsonl"))
                print(f"pre-seeded {seeded} cached single-step responses from Phase 3")
                policy = LLMPolicy(backend, name=f"groq:{args.model}")
                try:
                    m = run_and_save(OUT / name, name, policy, eps, recovery=rec, sim=sim)
                except DailyLimitReached as e:
                    print("STOPPED by Groq daily limit:", e, "- nothing scored for this mode (episodes run in lock-step).")
                    raise
            else:
                eps = test
                policy = RulesPolicy() if args.policy == "rules" else RandomPolicy(args.seed)
                name = f"{args.policy}_{tag}"
                t = time.time()
                m = run_and_save(OUT / name, name, policy, eps, recovery=rec, sim=sim, log=lambda *_: None)
                print(f"({time.time() - t:.0f}s)")
            print(name, fmt_agent(m))


if __name__ == "__main__":
    main()
