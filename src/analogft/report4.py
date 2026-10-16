"""Phase 4 tables and figures: agent comparison, failure classes, recovery ablation, RL before/after, budget curve, traces."""
from __future__ import annotations

import json
import random
from pathlib import Path

from . import paths
from .agent_eval import MAX_STEPS, summarize_agent
from .evaluation import bootstrap_mean_ci
from .tracing import FAILURE_CLASSES, RECOVERIES, read_traces

RESULTS4 = paths.REPO_ROOT / "results" / "phase4"
# (directory name, label) in display order
AGENTS = [("random_norecovery", "random"), ("random_recovery", "random + recovery"),
          ("rules_norecovery", "textbook rules"), ("rules_recovery", "textbook rules + recovery"),
          ("groq_openai_gpt-oss-120b_norecovery", "gpt-oss-120b"), ("groq_openai_gpt-oss-120b_recovery", "gpt-oss-120b + recovery"),
          ("groq_qwen_qwen3.8-27b_norecovery", "qwen3.8-27b"), ("groq_qwen_qwen3.8-27b_recovery", "qwen3.8-27b + recovery"),
          ("ft_norecovery", "fine-tuned Qwen2.5-0.5B"), ("ft_recovery", "fine-tuned + recovery"),
          ("rl_recovery", "after expert iteration + recovery")]


def agent_dirs() -> dict[str, Path]:
    """name -> directory, from the committed results/phase4 and (if pulled) runs/phase4/agents."""
    out = {}
    for base in (paths.RUNS_DIR / "phase4" / "agents", RESULTS4):
        if base.exists():
            for d in sorted(base.iterdir()):
                if (d / "episodes.jsonl").exists():
                    out[d.name] = d
    return out


def load(name: str, dirs: dict[str, Path]) -> tuple[list[dict], list[dict]]:
    return read_traces(dirs[name])


def restrict(steps: list[dict], eps: list[dict], ids: set[str]) -> tuple[list[dict], list[dict]]:
    return [s for s in steps if s["episode_id"] in ids], [e for e in eps if e["episode_id"] in ids]


def _ci(m: dict) -> str:
    lo, hi = m["success_ci"]
    return f"{m['success_rate']:.3f} [{lo:.3f}, {hi:.3f}]"


def _f(x, nd=1):
    return "-" if x is None else f"{x:.{nd}f}"


def agent_table(rows: dict[str, dict]) -> str:
    head = ("| agent | n | success (95% CI) | median steps to success | steps / reference path (solved) | "
            "mean final distance | sims / episode | invalid-output rate | recoveries / episode |")
    lines = [head, "|" + "---|" * 9]
    for label, m in rows.items():
        lines.append(f"| {label} | {m['n_episodes']} | {_ci(m)} | {_f(m['median_steps_to_success'])} | "
                     f"{_f(m['steps_over_reference'], 2)} | {m['mean_final_distance']:.3f} | {m['mean_sims']:.1f} | "
                     f"{m['invalid_output_rate']:.3f} | {m['recoveries_per_episode']:.2f} |")
    return "\n".join(lines)


def failure_table(rows: dict[str, dict]) -> str:
    lines = ["| agent | " + " | ".join(FAILURE_CLASSES) + " | " + " | ".join(RECOVERIES) + " |",
             "|" + "---|" * (1 + len(FAILURE_CLASSES) + len(RECOVERIES))]
    for label, m in rows.items():
        lines.append(f"| {label} | " + " | ".join(str(m["failure_classes"][k]) for k in FAILURE_CLASSES) + " | "
                     + " | ".join(str(m["recoveries"][k]) for k in RECOVERIES) + " |")
    return "\n".join(lines)


def paired_diff(eps_a: list[dict], eps_b: list[dict], n_boot: int = 2000, seed: int = 0) -> tuple[float, list[float], int]:
    """success(b) - success(a) over the episodes both ran (paired), with a bootstrap 95% CI."""
    a = {e["episode_id"]: float(e["solved"]) for e in eps_a}
    b = {e["episode_id"]: float(e["solved"]) for e in eps_b}
    ids = sorted(set(a) & set(b))
    d = [b[i] - a[i] for i in ids]
    return (sum(d) / len(d) if d else float("nan")), bootstrap_mean_ci(d, n_boot, seed), len(d)


def pair_table(pairs: list[tuple[str, dict, list, dict, list]], a_name: str, b_name: str) -> str:
    """pairs: (label, metrics_a, eps_a, metrics_b, eps_b)."""
    lines = [f"| comparison | n | success: {a_name} | success: {b_name} | paired difference (95% CI) |", "|---|---|---|---|---|"]
    for label, ma, ea, mb, eb in pairs:
        d, ci, n = paired_diff(ea, eb)
        lines.append(f"| {label} | {n} | {_ci(ma)} | {_ci(mb)} | {d:+.3f} [{ci[0]:+.3f}, {ci[1]:+.3f}] |")
    return "\n".join(lines)


def budget_figure(rows: dict[str, dict], out: Path, title: str = "Success rate vs step budget (test episodes)") -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(7, 4.2))
    ks = list(range(1, MAX_STEPS + 1))
    for label, m in rows.items():
        ax.plot(ks, [m["success_by_budget"][str(k)] if str(k) in m["success_by_budget"] else m["success_by_budget"][k]
                     for k in ks], marker="o", ms=3, label=label,
                 lw=2.2 if "fine-tuned" in label or "expert" in label else 1.4)
    ax.set_xlabel("step budget"); ax.set_ylabel("episodes solved"); ax.set_title(title)
    ax.set_ylim(0, 1); ax.grid(alpha=0.3); ax.legend(fontsize=7, loc="lower right")
    fig.tight_layout(); Path(out).parent.mkdir(parents=True, exist_ok=True); fig.savefig(out, dpi=150); plt.close(fig)


# ----- readable traces ------------------------------------------------------------------------

def _m(m: dict | None) -> str:
    if not m or any(m.get(k) is None for k in ("dc_gain_db", "ugf_hz", "pm_deg", "power_w")):
        return "no complete metrics"
    return (f"gain {m['dc_gain_db']:.1f} dB, UGF {m['ugf_hz'] / 1e6:.2f} MHz, PM {m['pm_deg']:.1f} deg, "
            f"power {m['power_w'] * 1e3:.3f} mW")


def render_episode(ep: dict, steps: list[dict], spec: dict | None = None) -> str:
    out = [f"**Episode `{ep['episode_id']}`** - outcome: **{ep['outcome']}** in {ep['steps']} step(s), "
           f"{ep['sims']} simulations, reference path {ep['reference_len']} moves, start distance {ep['start_distance']}, "
           f"final distance {ep['final_distance']}"]
    if spec:
        out.append(f"Spec: gain >= {spec['gain_db_min']} dB, UGF >= {spec['ugf_hz_min'] / 1e6:.2f} MHz, "
                   f"PM >= {spec['pm_deg_min']} deg, power <= {spec['power_w_max'] * 1e3:.3f} mW")
    out.append("")
    for s in sorted(steps, key=lambda x: x["step"]):
        st = s["state"]
        out.append(f"- **Step {s['step'] + 1}** state: {_m(st['metrics'])}; failing: {', '.join(st['failing']) or 'none'}; "
                   f"distance {st['distance']}")
        raw = (s["raw"] or "").strip().replace("\n", " ")
        out.append(f"  - model said: `{raw[:200] or '(rules policy, no text)'}`" + (f" (error: {s['error']})" if s["error"] else ""))
        if s["action"]:
            sm = s["sim"]
            out.append(f"  - action **{s['action']}** -> simulated: {_m(sm['metrics']) if sm else '-'}; distance "
                       f"{s['distance_before']} -> {s['distance_after']} (improvement {s['improvement']:+.3f})")
        else:
            out.append("  - no usable action: step wasted")
        for f in s["failure_classes"]:
            out.append(f"  - failure detected: {f}")
        for r in s["recoveries"]:
            out.append(f"  - recovery taken: **{r['type']}** ({r['detail']})")
    return "\n".join(out)


def pick_examples(steps: list[dict], eps: list[dict]) -> tuple[dict | None, dict | None]:
    """A success in which a recovery fired (the shortest one) and a failure (the one with most failure events)."""
    by_ep: dict[str, list[dict]] = {}
    for s in steps:
        by_ep.setdefault(s["episode_id"], []).append(s)
    succ = [e for e in eps if e["solved"] and sum(e["recoveries"].values()) > 0]
    succ.sort(key=lambda e: (e["steps"], e["episode_id"]))
    fail = [e for e in eps if not e["solved"]]
    fail.sort(key=lambda e: (-sum(e["failure_classes"].values()), e["episode_id"]))
    return (succ[0] if succ else None), (fail[0] if fail else None)
