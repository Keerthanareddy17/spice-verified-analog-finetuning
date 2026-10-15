"""Phase 2 dataset: achievable specs, broken start states, all-action labeling, splits.

Pipeline (all simulations go through `SimRunner`, which dedupes and counts):
  1. targets: random good designs; their own metrics (with slack) define the spec
  2. starts: targets perturbed on the action lattice (reachable by inverse moves)
  3. labeling: simulate every action from each state, follow the greedy best action
"""
from __future__ import annotations

import json
import math
import time
from dataclasses import asdict, dataclass, replace
from pathlib import Path

import numpy as np

from .actions import ACTION_BY_ID, ACTION_IDS, STEP, apply, available_actions
from .circuit import Design, KNOBS, nominal_design, simulate_batch_with_stats
from .circuit.simulator import SimResult
from .prompting import SYSTEM_PROMPT, format_prompt, format_response
from .shortfall import METRIC_KEYS, n_unsaturated, unsaturated
from .specs import Spec, spec_distance

ACTION_KNOBS = ["cc", "ibias", "w_in", "l_in", "l_load", "w_cs", "out_ratio"]
SPLITS = ("train", "val", "test")


@dataclass
class BuildConfig:
    seed: int = 0
    n_targets: int = 600
    starts_per_target: int = 3
    start_oversample: float = 2.0       # candidate starts per wanted start
    target_range: float = 3.0           # knobs log-uniform in [nominal/3, nominal*3]
    target_min_pm: float = 50.0
    k_range: int = 3                    # per-knob lattice exponent in [-3, 3]
    k_total_min: int = 2
    k_total_max: int = 6
    max_start_distance: float = 5.0
    extra_steps: int = 3                # greedy steps after the start state
    split_fractions: tuple[float, float, float] = (0.8, 0.1, 0.1)
    out_name: str = "phase2"            # folder under data/
    workers: int | None = None

    @classmethod
    def from_json(cls, path: Path) -> "BuildConfig":
        d = json.loads(Path(path).read_text())
        if "split_fractions" in d:
            d["split_fractions"] = tuple(d["split_fractions"])
        return cls(**d)


# ----- simulation bookkeeping --------------------------------------------------------

class SimRunner:
    """Batch simulation with dedupe; tracks unique simulations, cache hits and wall time."""

    def __init__(self, workers: int | None = None):
        self.workers, self.requested, self.cache_hits, self.seconds = workers, 0, 0, 0.0

    def run(self, designs: list[Design]) -> list[SimResult]:
        unique = list(dict.fromkeys(designs))
        results, stats = simulate_batch_with_stats(unique, workers=self.workers)
        self.requested += len(unique)
        self.cache_hits += stats.cache_hits
        self.seconds += stats.seconds
        by_design = dict(zip(unique, results))
        return [by_design[d] for d in designs]


# ----- step 1: targets and specs -----------------------------------------------------

def sample_targets(rng: np.random.Generator, n: int, span: float) -> list[Design]:
    """Each knob log-uniform in [nominal/span, nominal*span], clipped to its bounds."""
    nom = nominal_design().to_dict()
    out = []
    for _ in range(n):
        vals = {k: nom[k] * math.exp(rng.uniform(-math.log(span), math.log(span))) for k in KNOBS}
        out.append(Design.from_dict(vals).clip())
    return out


def target_ok(r: SimResult, min_pm: float) -> bool:
    return r.ok and all(x["saturated"] for x in r.regions.values()) and r.metrics["pm_deg"] >= min_pm


def make_spec(rng: np.random.Generator, m: dict) -> Spec:
    """Spec from the target's own metrics with slack. Rounded toward slack so the target still passes."""
    gain = m["dc_gain_db"] - rng.uniform(0, 3)
    ugf = m["ugf_hz"] * rng.uniform(0.75, 0.95)
    pm = min(max(m["pm_deg"] - rng.uniform(0, 10), 45.0), 70.0)
    power = m["power_w"] * rng.uniform(1.05, 1.3)
    return Spec(gain_db_min=math.floor(gain * 10) / 10,
                ugf_hz_min=math.floor(ugf / 1e4) * 1e4,
                pm_deg_min=math.floor(pm * 10) / 10,
                power_w_max=math.ceil(power * 1e6) / 1e6)


# ----- step 2: start states ----------------------------------------------------------

def sample_start(rng: np.random.Generator, target: Design, cfg: BuildConfig):
    """Perturb the 7 action knobs by 1.3^k; resample until nothing hits a bound.

    Staying inside the bounds keeps the start on the action lattice: applying the
    inverse actions (no clipping involved) returns exactly the target's knobs.
    """
    while True:
        k = rng.integers(-cfg.k_range, cfg.k_range + 1, size=len(ACTION_KNOBS))
        if not cfg.k_total_min <= int(np.abs(k).sum()) <= cfg.k_total_max:
            continue
        vals = {kn: getattr(target, kn) * STEP ** int(ki) for kn, ki in zip(ACTION_KNOBS, k)}
        if all(KNOBS[kn][0] * (1 - 1e-9) <= v <= KNOBS[kn][1] * (1 + 1e-9) for kn, v in vals.items()):
            return replace(target, **vals), {kn: int(ki) for kn, ki in zip(ACTION_KNOBS, k)}


def inverse_actions(k: dict[str, int]) -> list[str]:
    """Action ids that undo a lattice perturbation k."""
    out = []
    for kn, ki in k.items():
        out += [f"{kn}_{'down' if ki > 0 else 'up'}"] * abs(ki)
    return out


# ----- state records -----------------------------------------------------------------

def _metrics4(r: SimResult) -> dict:
    return {k: r.metrics.get(k) for k in METRIC_KEYS}


def _regions(r: SimResult) -> dict[str, bool]:
    return {d: bool(v["saturated"]) for d, v in r.regions.items()}


def _outcome(r: SimResult, spec: Spec, d_before: float) -> dict:
    d = spec_distance(r, spec)
    return {"distance_after": round(d, 6), "improvement": round(d_before - d, 6),
            "metrics": _metrics4(r), "n_unsat": n_unsaturated(_regions(r)) if r.regions else None,
            "failure": r.failure.value if r.failure else None}


@dataclass
class Node:
    group_id: str
    start_id: str
    step: int
    design: Design
    result: SimResult
    spec: Spec


def label_nodes(nodes: list[Node], runner: SimRunner, max_step: int) -> tuple[list[dict], list[Node]]:
    """Simulate every available action for each node; return records and the greedy next nodes."""
    plans = []
    child_designs: list[Design] = []
    for n in nodes:
        acts = available_actions(n.design)
        kids = [apply(n.design, a) for a in acts]
        plans.append((acts, kids))
        child_designs += kids
    results = iter(runner.run(child_designs))
    records, next_nodes = [], []
    for n, (acts, kids) in zip(nodes, plans):
        kid_res = {a.id: next(results) for a in acts}
        d0 = spec_distance(n.result, n.spec)
        outcomes = {a.id: _outcome(kid_res[a.id], n.spec, d0) for a in acts}
        # best first; ties broken by action id order (stable sort over ACTION_IDS order)
        ranking = sorted(outcomes, key=lambda a: (-outcomes[a]["improvement"], ACTION_IDS.index(a)))
        best = ranking[0]
        top = outcomes[best]["improvement"]
        tied = [a for a in ranking if abs(outcomes[a]["improvement"] - top) < 1e-9]
        regions = _regions(n.result)
        rec = {"id": f"{n.start_id}_k{n.step}", "group_id": n.group_id, "start_id": n.start_id,
               "split": None, "step_index": n.step, "spec": asdict(n.spec),
               "design": n.design.to_dict(), "metrics": _metrics4(n.result), "regions": regions,
               "distance": round(d0, 6), "available_actions": [a.id for a in acts],
               "label_action": best, "best_improves": top > 0,
               "label_solves": outcomes[best]["distance_after"] == 0.0,
               "tied_best": tied if len(tied) > 1 else [], "ranking": ranking,
               "action_outcomes": outcomes}
        before = {"metrics": rec["metrics"], "n_unsat": n_unsaturated(regions),
                  "unsat": unsaturated(regions)}
        rec["messages"] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": format_prompt(rec)},
            {"role": "assistant", "content": format_response(best, before, outcomes[best], rec["spec"])}]
        records.append(rec)
        if top > 0 and outcomes[best]["distance_after"] > 0 and n.step < max_step:
            a_best = ACTION_BY_ID[best]
            next_nodes.append(replace(n, step=n.step + 1, design=apply(n.design, a_best),
                                      result=kid_res[best]))
    return records, next_nodes



# ----- splits ------------------------------------------------------------------------

def assign_splits(group_ids: list[str], fractions: tuple[float, float, float], seed: int) -> dict[str, str]:
    """Group-level split: all states of one target go to the same split."""
    groups = sorted(set(group_ids))
    perm = np.random.default_rng(seed + 12345).permutation(len(groups))
    n_val = round(fractions[1] * len(groups))
    n_test = round(fractions[2] * len(groups))
    out = {}
    for rank, gi in enumerate(perm):
        out[groups[gi]] = "val" if rank < n_val else "test" if rank < n_val + n_test else "train"
    return out


def check_no_leakage(records: list[dict]) -> None:
    seen: dict[str, str] = {}
    for r in records:
        prev = seen.setdefault(r["group_id"], r["split"])
        assert prev == r["split"], f"group {r['group_id']} in splits {prev} and {r['split']}"


# ----- build -------------------------------------------------------------------------

def build(cfg: BuildConfig, log=print) -> dict:
    """Run the whole pipeline in memory. Returns records, episodes and build stats."""
    t_start = time.time()
    rng = np.random.default_rng(cfg.seed)
    runner = SimRunner(cfg.workers)

    # 1. targets
    targets: list[tuple[Design, SimResult, Spec]] = []
    n_cand = n_fail_cand = 0
    while len(targets) < cfg.n_targets:
        want = max(16, int((cfg.n_targets - len(targets)) * 1.5))
        cands = sample_targets(rng, want, cfg.target_range)
        for d, r in zip(cands, runner.run(cands)):
            n_cand += 1
            if target_ok(r, cfg.target_min_pm) and len(targets) < cfg.n_targets:
                targets.append((d, r, make_spec(rng, r.metrics)))
    log(f"targets: {len(targets)} kept of {n_cand} candidates ({100 * len(targets) / n_cand:.0f}% yield)")
    for _, r, s in targets:  # guaranteed achievable
        assert spec_distance(r, s) == 0.0

    # 2. start states
    episodes, nodes = [], []
    n_start_cand = n_start_fail = n_start_pass = n_start_far = 0
    all_cands = []  # (group id, target, spec, [(start design, k), ...]) -- sampled first so one batch simulates all
    for ti, (tdes, tres, spec) in enumerate(targets):
        n_c = int(cfg.starts_per_target * cfg.start_oversample)
        all_cands.append((f"t{ti:04d}", tdes, tres, spec, [sample_start(rng, tdes, cfg) for _ in range(n_c)]))
    flat = runner.run([c[0] for *_, cs in all_cands for c in cs])
    results_iter = iter(flat)
    for gid, tdes, tres, spec, cands in all_cands:
        n_want, kept, seen = cfg.starts_per_target, 0, {tdes}
        for sdes, k in cands:
            sres = next(results_iter)
            n_start_cand += 1
            d = spec_distance(sres, spec)
            if not sres.ran:
                n_start_fail += 1
            elif d <= 0:
                n_start_pass += 1
            elif d > cfg.max_start_distance:
                n_start_far += 1
            elif kept < n_want and sdes not in seen:
                seen.add(sdes)
                sid = f"{gid}_s{kept}"
                episodes.append({"id": sid, "group_id": gid, "split": None,
                                 "target_design": tdes.to_dict(), "target_metrics": _metrics4(tres),
                                 "spec": asdict(spec), "start_design": sdes.to_dict(),
                                 "start_distance": round(d, 6), "lattice_k": k})
                nodes.append(Node(gid, sid, 0, sdes, sres, spec))
                kept += 1
    log(f"starts: {len(episodes)} kept of {n_start_cand} candidates "
        f"(rejected: {n_start_fail} failed sim, {n_start_pass} already pass, {n_start_far} too far)")

    # 3. label level by level (all states of one step_index in one parallel batch)
    records: list[dict] = []
    seen_states: set[tuple[str, Design]] = set()
    frontier = nodes
    while frontier:
        frontier = [n for n in frontier if (n.group_id, n.design) not in seen_states]  # converged paths
        seen_states.update((n.group_id, n.design) for n in frontier)
        if not frontier:
            break
        level = frontier[0].step
        recs, frontier = label_nodes(frontier, runner, cfg.extra_steps)
        records += recs
        log(f"  step {level}: labeled {len(recs)} states, {runner.requested} sims so far")

    # 4. splits
    group_split = assign_splits([e["group_id"] for e in episodes], cfg.split_fractions, cfg.seed)
    for x in records + episodes:
        x["split"] = group_split[x["group_id"]]
    check_no_leakage(records)
    stats = {"config": asdict(cfg), "n_targets": len(targets), "target_candidates": n_cand,
             "start_candidates": n_start_cand, "start_rejected": {"failed_sim": n_start_fail,
             "already_pass": n_start_pass, "too_far": n_start_far},
             "n_episodes": len(episodes), "n_records": len(records),
             "unique_simulations": runner.requested, "cache_hits": runner.cache_hits,
             "simulation_seconds": round(runner.seconds, 1),
             "total_seconds": round(time.time() - t_start, 1),
             "groups_per_split": {s: sum(v == s for v in group_split.values()) for s in SPLITS}}
    return {"records": records, "episodes": episodes, "stats": stats}


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        for r in rows:
            f.write(json.dumps(r, separators=(",", ":")) + "\n")


def read_jsonl(path: Path) -> list[dict]:
    with Path(path).open() as f:
        return [json.loads(line) for line in f if line.strip()]


def save(built: dict, out_dir: Path) -> None:
    for s in SPLITS:
        write_jsonl(out_dir / f"{s}.jsonl", [r for r in built["records"] if r["split"] == s])
        write_jsonl(out_dir / f"episodes_{s}.jsonl", [e for e in built["episodes"] if e["split"] == s])
    (out_dir / "build_stats.json").write_text(json.dumps(built["stats"], indent=2) + "\n")
