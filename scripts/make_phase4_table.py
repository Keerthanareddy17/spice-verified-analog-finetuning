"""Build results/phase4_results.md, results/phase4/examples.md and the budget figure from agent runs.

Reads agent runs from results/phase4/<agent>/ (locally run agents, committed) and runs/phase4/agents/<agent>/ (Colab agents,
after scripts/import_results_zip.py). Colab agents are copied into results/phase4/ so they get committed.
Usage: python scripts/make_phase4_table.py
"""
import json
import shutil

from analogft import paths
from analogft.agent_eval import load_episodes, summarize_agent
from analogft.report4 import (AGENTS, RESULTS4, agent_dirs, agent_table, budget_figure, failure_table, load, pair_table,
                              pick_examples, render_episode, restrict)


def main() -> None:
    dirs = agent_dirs()
    for name, d in dirs.items():  # keep the Colab agents next to the locally run ones, committed
        if d.parent.name == "agents" and not (RESULTS4 / name).exists():
            (RESULTS4 / name).mkdir(parents=True, exist_ok=True)
            for f in ("steps.jsonl", "episodes.jsonl", "metrics.json"):
                shutil.copy(d / f, RESULTS4 / name / f)
    dirs = agent_dirs()
    data = {n: load(n, dirs) for n, _ in AGENTS if n in dirs}
    label = dict(AGENTS)
    full = {label[n]: summarize_agent(*data[n]) for n in data if not n.startswith("groq")}
    # Groq subset: the episodes the Groq agent actually finished; every agent is re-scored on exactly those
    gname = next((n for n in data if n.startswith("groq_openai") and n.endswith("_recovery")), None) or next((n for n in data if n.startswith("groq")), None)
    gids = {e["episode_id"] for e in data[gname][1]} if gname else set()
    sub = {label[n]: summarize_agent(*restrict(*data[n], gids)) for n in data
           if gids and (n.startswith("groq") or {e["episode_id"] for e in data[n][1]} >= gids)}
    md = ["# Phase 4 results: multi-step agent, recovery, expert iteration", "",
          "Test episodes: 174 failing designs (60 unseen targets), 8-step budget; an episode is solved when the simulator says "
          "every spec passes. All numbers come from simulating the agent's moves with ngspice. 95% CIs are bootstrap intervals "
          "over episodes. \"steps / reference path\" is the total steps used on solved episodes divided by the total number of "
          "inverse lattice moves between their start design and the target they came from (a known solution length; the agent "
          "can solve with fewer or more moves).", "",
          "## 1. All test episodes (no Groq)", "", agent_table(full), ""]
    if gids:
        md += [f"## 2. Groq subset ({len(gids)} test episodes the Groq agent finished; every agent re-scored on exactly these)", "",
               agent_table(sub), "",
               "(Groq free-tier limits (8,000 tokens/min, 200,000 tokens/day per model) restrict this subset to 30 episodes, so CIs are wide: "
               "read it as a pilot, not a ranking.)", ""]
    md += ["## 3. Failure classes and recoveries (counts over all test episodes)", "", failure_table(full), "",
           "Counts are events, so one episode can contribute several. BUDGET_EXHAUSTED is once per unsolved episode.", ""]
    pairs = []
    for base, lab in (("random", "random"), ("rules", "textbook rules"), ("ft", "fine-tuned Qwen")):
        a, b = f"{base}_norecovery", f"{base}_recovery"
        if a in data and b in data:
            pairs.append((lab, summarize_agent(*data[a]), data[a][1], summarize_agent(*data[b]), data[b][1]))
    if pairs:
        md += ["## 4. Recovery ablation (same episodes, recovery off vs on)", "", pair_table(pairs, "no recovery", "recovery"), ""]
    if "ft_recovery" in data and "rl_recovery" in data:
        md += ["## 5. Expert iteration: before vs after (agent with recovery)", "",
               pair_table([("fine-tuned -> after expert iteration", summarize_agent(*data["ft_recovery"]), data["ft_recovery"][1],
                            summarize_agent(*data["rl_recovery"]), data["rl_recovery"][1])], "before", "after"), ""]
        for tag, run in (("Phase 3 fine-tuned", paths.RUNS_DIR / "phase3" / "qwen25_05b_lora"),
                         ("after expert iteration", paths.RUNS_DIR / "phase4" / "qwen25_05b_rl")):
            f = run / "eval" / "finetuned" / "test" / "metrics.json"
            if f.exists():
                m = json.loads(f.read_text())
                md.append(f"- single-step test eval, {tag} (n={m['n']}): top-1 {m['top1']:.3f} [{m['ci']['top1'][0]:.3f}, "
                          f"{m['ci']['top1'][1]:.3f}], improvement {m['improve_rate']:.3f}, regret {m['mean_regret']:.3f}, valid {m['valid_rate']:.3f}")
        rs = paths.RUNS_DIR / "phase4" / "rl_dataset" / "rl_train.stats.json"
        if rs.exists():
            s = json.loads(rs.read_text())
            md += ["", f"Expert-iteration data: {s['rollouts']} rollouts, {s['rollouts_solved']} solved "
                   f"({100 * s['rollout_success_rate']:.1f}%), {s['candidate_steps']} candidate improving steps, "
                   f"{s['duplicates_of_phase2_train']} exact duplicates of Phase 2 examples dropped, **{s['new_examples']} new examples** "
                   f"added to {s['train_examples_before']} (total {s['train_examples_after']}); dropped steps: {s['dropped']}"]
        md.append("")
    figs = paths.REPO_ROOT / "results" / "figures"
    budget_figure(full, figs / "phase4_success_vs_budget.png")
    (paths.RUNS_DIR / "phase4" / "figures").mkdir(parents=True, exist_ok=True)
    shutil.copy(figs / "phase4_success_vs_budget.png", paths.RUNS_DIR / "phase4" / "figures" / "phase4_success_vs_budget.png")
    md += ["## 6. Success rate vs step budget", "", "![success vs budget](figures/phase4_success_vs_budget.png)", ""]
    (paths.REPO_ROOT / "results" / "phase4_results.md").write_text("\n".join(md))
    (paths.REPO_ROOT / "results" / "phase4_results.json").write_text(json.dumps({"all_test": full, "groq_subset": sub}, indent=1) + "\n")
    # example traces from the fine-tuned agent with recovery (falls back to rules)
    src = next((n for n in ("rl_recovery", "ft_recovery", "rules_recovery") if n in data), None)
    if src:
        steps, eps = data[src]
        specs = {e["id"]: e["spec"] for e in load_episodes("test")}
        succ, fail = pick_examples(steps, eps)
        ex = [f"# Example traces ({label[src]})", "", "Each step shows the state the model saw, what it answered, any recovery, "
              "the action applied and the simulated result.", ""]
        for title, e in (("A success in which a recovery path fired", succ), ("A failure", fail)):
            if e:
                ex += [f"## {title}", "", render_episode(e, [s for s in steps if s["episode_id"] == e["episode_id"]],
                                                         specs.get(e.get("base_episode_id", e["episode_id"]))), ""]
        (RESULTS4 / "examples.md").write_text("\n".join(ex))
    print("\n".join(md))


if __name__ == "__main__":
    main()
