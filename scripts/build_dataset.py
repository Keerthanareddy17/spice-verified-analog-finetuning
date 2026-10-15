"""Build the Phase 2 dataset. Usage: python scripts/build_dataset.py --config configs/phase2.json [--pilot]

--pilot: ~20 targets, written to data/phase2_pilot/ so the real dataset is untouched.
"""
import argparse
import json
from dataclasses import replace
from pathlib import Path

from analogft import paths
from analogft.dataset import BuildConfig, build, save
from analogft.dataset_stats import summarize


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=str(paths.REPO_ROOT / "configs/phase2.json"))
    ap.add_argument("--pilot", action="store_true")
    ap.add_argument("--n-targets", type=int, help="override config n_targets")
    args = ap.parse_args()
    cfg = BuildConfig.from_json(Path(args.config))
    if args.pilot:
        cfg = replace(cfg, n_targets=20, out_name=cfg.out_name + "_pilot")
    if args.n_targets:
        cfg = replace(cfg, n_targets=args.n_targets)
    out_dir = paths.DATA_DIR / cfg.out_name
    built = build(cfg)
    built["stats"]["summary"] = summarize(built["records"], built["episodes"])
    save(built, out_dir)
    s, st = built["stats"]["summary"], built["stats"]
    print(f"\nwrote {out_dir}")
    print(f"states={s['n_states']} episodes={s['n_episodes']} sims={st['unique_simulations']} "
          f"({st['unique_simulations'] / s['n_states']:.1f} per state) sim_time={st['simulation_seconds']}s "
          f"total={st['total_seconds']}s cache_hits={st['cache_hits']}")
    print("labels:", json.dumps(s["label_counts"]))
    print(f"top label fraction={s['top_label_fraction']:.2f} best_improves={s['best_improves_fraction']:.2f} "
          f"failed-sim actions={s['failed_sim_action_fraction']:.3f} "
          f"distance range={s['distance']['min']:.3f}..{s['distance']['max']:.3f}")
    print(f"user tokens: median={s['user_tokens']['median']:.0f} p95={s['user_tokens']['p95']:.0f} "
          f"max={s['user_tokens']['max']:.0f}; reason words max={s['assistant_words_max']}")
    print("step counts:", s["step_index_counts"])


if __name__ == "__main__":
    main()
