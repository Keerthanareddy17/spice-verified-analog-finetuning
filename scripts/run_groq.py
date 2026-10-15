"""Score a Groq model on the fixed 150-example eval subset (resumable; every response is cached).

Usage:
  python scripts/run_groq.py --model openai/gpt-oss-120b --pilot 5     # tokens/latency, no scoring file
  python scripts/run_groq.py --model openai/gpt-oss-120b               # full subset (stops cleanly at a daily cap)
"""
import argparse
import json
import random
import time

from analogft import paths
from analogft.dataset import read_jsonl
from analogft.harness import SUBSET_FILE, fmt_metrics, make_eval_subset, save_evaluation, select
from analogft.predict import DailyLimitReached, GroqBackend, Predictor

OUT = paths.RESULTS_DIR / "phase3"


def get_subset(test: list[dict]) -> list[str]:
    f = OUT / SUBSET_FILE
    if f.exists():
        return json.loads(f.read_text())["ids"]
    ids = make_eval_subset(test, 150, seed=0)
    OUT.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps({"n": len(ids), "seed": 0, "stratified_by": "step_index", "ids": ids}, indent=1) + "\n")
    return ids


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="openai/gpt-oss-120b")
    ap.add_argument("--effort", default="medium", help="reasoning_effort, or 'none' to omit")
    ap.add_argument("--max-tokens", type=int, default=2048)
    ap.add_argument("--pilot", type=int, default=0)
    ap.add_argument("--budget", type=int, help="stop after this many tokens spent in this run")
    args = ap.parse_args()

    test = read_jsonl(paths.DATA_DIR / "phase2" / "test.jsonl")
    ids = get_subset(test)
    order = ids[:]
    random.Random(0).shuffle(order)  # fixed order so a partial run is an unbiased sample
    by_id = {r["id"]: r for r in select(test, ids)}
    slug = args.model.replace("/", "_")
    out_dir = OUT / f"groq_{slug}"
    backend = GroqBackend(args.model, cache_path=out_dir / "cache.jsonl",
                          reasoning_effort=None if args.effort == "none" else args.effort,
                          max_tokens=args.max_tokens, daily_token_budget=args.budget)
    pred = Predictor(backend)
    todo = order[: args.pilot] if args.pilot else order
    done: list[str] = []
    t0 = time.time()
    try:
        for i, eid in enumerate(todo):
            p = pred.predict_batch([by_id[eid]])[0]
            done.append(eid)
            m = p.meta
            print(f"[{i + 1}/{len(todo)}] {eid} action={p.action} err={p.error} prompt={m['prompt_tokens']} "
                  f"reasoning={m['reasoning_tokens']} completion={m['completion_tokens']} total={m['total_tokens']} "
                  f"{m['latency_s']}s finish={m['finish_reason']}", flush=True)
    except DailyLimitReached as e:
        print("STOPPED by daily limit:", e)
    print("rate limit headers:", json.dumps(backend.rate_limits))
    rows = [backend.cache[k] for k in done if k in backend.cache]
    if rows:
        n = len(rows)
        avg = lambda k: sum((r[k] or 0) for r in rows) / n
        print(f"\ntokens/example: prompt={avg('prompt_tokens'):.0f} reasoning={avg('reasoning_tokens'):.0f} "
              f"completion={avg('completion_tokens'):.0f} total={avg('total_tokens'):.0f}; latency={avg('latency_s'):.1f}s")
        print(f"projected for {len(ids)}: {avg('total_tokens') * len(ids):,.0f} tokens; "
              f"truncated: {sum(r['finish_reason'] == 'length' for r in rows)}/{n}")
    if not args.pilot and done:
        recs = [by_id[k] for k in done]
        preds = pred.predict_batch(recs)  # all cached: no API calls
        m = save_evaluation(out_dir, recs, preds, f"groq {args.model} effort={args.effort}")
        print(f"\nscored {len(done)}/{len(ids)} examples ->", out_dir)
        print(fmt_metrics(m), "| errors:", m["errors"], "| truncated:", m["n_truncated"])


if __name__ == "__main__":
    main()
