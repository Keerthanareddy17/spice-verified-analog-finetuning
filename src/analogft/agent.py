"""Multi-step design-repair agent with tracing and recovery paths.

An episode starts from a failing design (spec + start design). Up to `max_steps` times: build the prompt from the
CURRENT state, ask the policy for one action, apply it, simulate, compute spec_distance; stop when the spec is met.
Episodes run in lock-step so that each step makes ONE batched policy call and ONE batched simulation.

Memory (best design so far, visited designs, blocked actions) lives in `EpisodeState`, never in the prompt, so the
prompts stay in the training distribution. See docs/DECISIONS.md D26-D29 for the rules below.
"""
from __future__ import annotations

import math
import multiprocessing as mp
import os
import time
from collections import Counter
from dataclasses import asdict, dataclass, field

from . import tracing as T
from .actions import apply, available_actions
from .circuit import Design, KNOBS, simulate
from .circuit.batch import _work
from .circuit.models import TEMP_NOM
from .circuit.simulator import SimResult
from .dataset import _metrics4, _regions
from .policies import Policy, RulesPolicy
from .predict import Prediction
from .shortfall import has_all_metrics, n_unsaturated, shortfall_terms
from .specs import Spec, spec_distance

NO_PROGRESS_STEPS = 3
EPS = 1e-9


# ----- simulation ---------------------------------------------------------------------------

class SimPool:
    """Persistent process pool for batched simulation (creating a spawn pool per step would dominate the run time)."""

    def __init__(self, workers: int | None = None):
        self.workers = workers or max(1, (os.cpu_count() or 2) - 1)
        self._pool = None

    def run(self, designs: list[Design]) -> list[SimResult]:
        if not designs:
            return []
        if self.workers == 1 or len(designs) < 2:
            return [simulate(d) for d in designs]
        if self._pool is None:
            self._pool = mp.get_context("spawn").Pool(self.workers)
        jobs = [(d, TEMP_NOM, 1.0, True) for d in designs]
        return self._pool.map(_work, jobs, chunksize=max(1, len(jobs) // (self.workers * 4)))

    def close(self) -> None:
        if self._pool is not None:
            self._pool.close(); self._pool.join(); self._pool = None

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


# ----- per-episode state --------------------------------------------------------------------

def design_key(d: Design) -> tuple:
    """Hashable identity of a design that tolerates float noise (x1.3 then /1.3 is not bit-exact)."""
    return tuple(round(math.log(getattr(d, k)), 4) for k in KNOBS)


@dataclass
class EpisodeState:
    ep: dict
    sample: int
    spec: Spec
    design: Design
    result: SimResult
    distance: float
    best_design: Design
    best_distance: float
    start_distance: float
    visited: dict = field(default_factory=dict)       # key -> (Design, SimResult)
    blocked: dict = field(default_factory=dict)       # key -> set of action ids blocked at that design
    last_action_at: dict = field(default_factory=dict)  # key -> action id most recently chosen there
    no_progress: int = 0
    done: bool = False
    outcome: str | None = None
    steps: int = 0
    steps_to_success: int | None = None
    sims: int = 0
    failures: Counter = field(default_factory=Counter)
    recoveries: Counter = field(default_factory=Counter)
    invalid_outputs: int = 0
    policy_calls: int = 0
    last_context_failures: list = field(default_factory=list)

    @property
    def id(self) -> str:
        return self.ep["id"] if self.sample < 0 else f"{self.ep['id']}#s{self.sample}"

    @property
    def spec_d(self) -> dict:
        return asdict(self.spec)

    def avail(self) -> list[str]:
        blocked = self.blocked.get(design_key(self.design), set())
        return [a.id for a in available_actions(self.design) if a.id not in blocked]

    def state(self, avail: list[str]) -> dict:
        return {"spec": self.spec_d, "design": self.design.to_dict(), "metrics": _metrics4(self.result),
                "regions": _regions(self.result), "available_actions": avail}

    def block(self, action: str) -> None:
        self.blocked.setdefault(design_key(self.design), set()).add(action)


def reference_len(ep: dict) -> int:
    """Number of inverse lattice moves from the start design to its target (Phase 2 construction)."""
    return int(sum(abs(v) for v in ep["lattice_k"].values()))


def _init_states(episodes: list[dict], sim: SimPool, samples: int) -> list[EpisodeState]:
    starts = [Design.from_dict(e["start_design"]) for e in episodes]
    results = sim.run(starts)
    out = []
    for e, d, r in zip(episodes, starts, results):
        spec = Spec(**e["spec"])
        dist = spec_distance(r, spec)
        for j in range(samples):
            st = EpisodeState(e, j if samples > 1 else -1, spec, d, r, dist, d, dist, dist)
            st.visited[design_key(d)] = (d, r)
            out.append(st)
    return out


# ----- helpers ------------------------------------------------------------------------------

def _failing(spec_d: dict, metrics: dict, n_unsat: int) -> list[str]:
    terms = shortfall_terms(spec_d, metrics, n_unsat)
    return [k for k, v in terms.items() if v > 0]


def _reask_note(err: str) -> str:
    why = {"unavailable_action": "that action is not in the Actions list for this state",
           "unknown_action": "that is not a valid action id",
           "no_json": "it was not a JSON object with an \"action\" field"}.get(err, "it could not be used")
    return (f"Your previous answer was invalid: {why}. Choose exactly one action id from the Actions list above "
            'and answer with one line of JSON: {"action": "<action id>", "reason": "<short reason>"}')


@dataclass
class _Ctx:
    e: EpisodeState
    avail: list[str]
    state: dict
    pred: Prediction | None = None
    first: Prediction | None = None
    attempts: int = 0
    latency_ms: float = 0.0
    recs: list = field(default_factory=list)
    fcs: list = field(default_factory=list)
    used_fallback: bool = False
    note_used: bool = False
    action: str | None = None
    gave_up: bool = False


def _ask(policy: Policy, ctxs: list[_Ctx], notes: list[str | None] | None = None) -> None:
    if not ctxs:
        return
    t0 = time.time()
    preds = policy.choose([c.state for c in ctxs], notes)
    per = (time.time() - t0) * 1000.0 / len(ctxs)
    for c, p in zip(ctxs, preds):
        c.pred, c.attempts, c.latency_ms = p, c.attempts + 1, c.latency_ms + per
        c.e.policy_calls += 1
        if c.first is None:
            c.first = p


def _note_failure(c: _Ctx, fclass: str) -> None:
    c.fcs.append(fclass)
    c.e.failures[fclass] += 1


def _note_recovery(c: _Ctx, rtype: str, detail: str = "") -> None:
    c.recs.append({"type": rtype, "detail": detail})
    c.e.recoveries[rtype] += 1


# ----- the loop -----------------------------------------------------------------------------

def run_agent(episodes: list[dict], policy: Policy, *, recovery: bool, sim: SimPool, trace: T.TraceWriter,
              max_steps: int = 8, run_id: str = "run", samples: int = 1, fallback: Policy | None = None,
              log=None) -> list[dict]:
    """Run all episodes in lock-step; returns the episode records (also written to `trace`).

    `samples` > 1 runs several independent rollouts per episode (expert iteration with a sampling policy).
    With recovery=False the agent just keeps going: an invalid output wastes the step, a looping move is taken,
    a failed simulation is adopted as the new state.
    """
    fallback = fallback or RulesPolicy()
    t_start = time.time()
    first_new = len(trace.episodes)
    eps = _init_states(episodes, sim, samples)
    for step in range(max_steps):
        ctxs: list[_Ctx] = []
        for e in eps:
            if e.done:
                continue
            av = e.avail()
            if not av:
                _finish(e, "gave_up", trace, run_id, policy.name, recovery)
                continue
            ctxs.append(_Ctx(e, av, e.state(av)))
        if not ctxs:
            break
        n_start = len(ctxs)
        t_step = time.time()

        # A. ask the policy
        _ask(policy, ctxs)
        # B. invalid / unavailable outputs
        for c in ctxs:
            if c.pred.action is None:
                c.e.invalid_outputs += 1
                _note_failure(c, T.failure_class_of_parse_error(c.pred.error))
        bad = [c for c in ctxs if c.pred.action is None]
        if recovery and bad:
            for c in bad:
                _note_recovery(c, T.REASK, c.pred.error)
                c.note_used = True
            _ask(policy, bad, [_reask_note(c.pred.error) for c in bad])
            still = [c for c in bad if c.pred.action is None]
            for c in still:
                _note_failure(c, T.failure_class_of_parse_error(c.pred.error))
            if still:
                fb = fallback.choose([c.state for c in still])
                for c, p in zip(still, fb):
                    _note_recovery(c, T.FALLBACK_RULES, p.action or "none")
                    c.used_fallback = True
                    c.pred = p
                    c.gave_up = p.action is None
        for c in ctxs:
            c.action = c.pred.action

        # C. loops: a move that returns to a design already visited in this episode
        def is_loop(c: _Ctx) -> bool:
            return c.action is not None and design_key(apply(c.e.design, c.action)) in c.e.visited

        loops = [c for c in ctxs if is_loop(c)]
        for c in loops:
            _note_failure(c, T.LOOP)
        if recovery and loops:
            redo = []
            for c in loops:
                c.e.block(c.action)
                _note_recovery(c, T.LOOP_BLOCK_REASK, c.action)
                c.avail = [a for a in c.avail if a != c.action]
                c.state = c.e.state(c.avail)
                if c.avail:
                    redo.append(c)
                else:
                    c.action, c.gave_up = None, True
            _ask(policy, redo)
            for c in redo:
                if c.pred.action is None:
                    c.e.invalid_outputs += 1
                    _note_failure(c, T.failure_class_of_parse_error(c.pred.error))
                    p = fallback.choose([c.state])[0]
                    _note_recovery(c, T.FALLBACK_RULES, p.action or "none")
                    c.used_fallback, c.pred = True, p
                    c.gave_up = p.action is None
                c.action = c.pred.action
                if is_loop(c):  # still a loop after one re-ask: take it, NO_PROGRESS will catch a cycle
                    _note_failure(c, T.LOOP)

        # D. simulate all new designs in one batch
        new_designs: dict[tuple, Design] = {}
        for c in ctxs:
            if c.action is not None:
                nd = apply(c.e.design, c.action)
                if design_key(nd) not in c.e.visited:
                    new_designs[(c.e.id, design_key(nd))] = nd
        sim_keys = list(new_designs)
        sim_results = dict(zip(sim_keys, sim.run([new_designs[k] for k in sim_keys])))

        # E. apply results, bookkeeping, recoveries, trace
        for c in ctxs:
            e = c.e
            key_before = design_key(e.design)
            d_before = e.distance
            state_summary = {"metrics": c.state["metrics"],
                             "failing": _failing(e.spec_d, c.state["metrics"], n_unsaturated(c.state["regions"])),
                             "distance": round(d_before, 6), "n_unsat": n_unsaturated(c.state["regions"])}
            sim_info, after, improvement, d_after = None, None, 0.0, d_before
            adopted = False
            if c.action is None:
                pass  # wasted step (invalid output without a usable fallback)
            else:
                e.last_action_at[key_before] = c.action
                nd = apply(e.design, c.action)
                nk = design_key(nd)
                reused = nk in e.visited
                if reused:
                    res = e.visited[nk][1]
                else:
                    res = sim_results[(e.id, nk)]
                    e.sims += 1
                    e.visited[nk] = (nd, res)
                sim_d = spec_distance(res, e.spec)
                complete = has_all_metrics(_metrics4(res))
                sim_info = {"metrics": _metrics4(res), "failure": res.failure.value if res.failure else None,
                            "reused": reused, "distance": round(sim_d, 6)}
                if not complete:
                    _note_failure(c, T.SIM_FAILURE)
                if not complete and recovery:
                    e.block(c.action)  # rollback = simply not adopting the failed design
                    _note_recovery(c, T.SIM_ROLLBACK, c.action)
                else:
                    adopted = True
                    e.design, e.result, e.distance = nd, res, sim_d
                    d_after = sim_d
                    improvement = d_before - d_after
                    after = {"metrics": _metrics4(res), "n_unsat": n_unsaturated(_regions(res))}
            e.steps += 1
            improved_best = adopted and d_after < e.best_distance - EPS
            if improved_best:
                e.best_distance, e.best_design, e.no_progress = d_after, e.design, 0
            else:
                e.no_progress += 1
            solved = adopted and d_after <= 0.0
            if not solved and e.no_progress % NO_PROGRESS_STEPS == 0 and e.no_progress > 0:
                _note_failure(c, T.NO_PROGRESS)
                if recovery:
                    bkey = design_key(e.best_design)
                    e.design, e.result = e.best_design, e.visited[bkey][1]
                    e.distance = e.best_distance
                    prev = e.last_action_at.get(bkey)
                    if prev:
                        e.blocked.setdefault(bkey, set()).add(prev)
                    _note_recovery(c, T.PROGRESS_ROLLBACK, prev or "none")
                    e.no_progress = 0
            tokens = None
            if c.pred.meta:
                tokens = c.pred.meta.get("total_tokens") or c.pred.meta.get("completion_tokens")
            rec = T.step_record(
                run_id=run_id, policy=policy.name, episode_id=e.id, step=step, recovery=recovery,
                sample=max(e.sample, 0), state=state_summary, raw=c.first.raw if c.first else "",
                error=c.first.error if c.first else None, action=c.action, failure_classes=c.fcs,
                recoveries=c.recs, used_fallback=c.used_fallback, note_used=c.note_used, attempts=c.attempts,
                sim=sim_info, distance_before=round(d_before, 6), distance_after=round(d_after, 6),
                improvement=round(improvement, 6), best_distance=round(e.best_distance, 6),
                latency_ms=round(c.latency_ms, 1), tokens=tokens, after=after, state_full=c.state)
            trace.step(rec)
            if solved:
                e.steps_to_success = step + 1
                _finish(e, "solved", trace, run_id, policy.name, recovery)
            elif c.gave_up:
                _finish(e, "gave_up", trace, run_id, policy.name, recovery)
        if log:
            n_solved = sum(e.outcome == "solved" for e in eps)
            log(f"[{run_id}] step {step + 1}/{max_steps}: {n_start} active, {n_solved}/{len(eps)} solved, "
                f"step took {time.time() - t_step:.1f}s, total {time.time() - t_start:.0f}s")
    for e in eps:
        if not e.done:
            e.failures[T.BUDGET_EXHAUSTED] += 1
            _finish(e, "budget_exhausted", trace, run_id, policy.name, recovery)
    trace.flush()
    return trace.episodes[first_new:]


def _finish(e: EpisodeState, outcome: str, trace: T.TraceWriter, run_id: str, policy_name: str, recovery: bool) -> None:
    e.done, e.outcome = True, outcome
    trace.episode(T.episode_record(
        run_id=run_id, policy=policy_name, episode_id=e.id, base_episode_id=e.ep["id"], group_id=e.ep["group_id"],
        sample=max(e.sample, 0), recovery=recovery, outcome=outcome, solved=outcome == "solved", steps=e.steps,
        steps_to_success=e.steps_to_success, reference_len=reference_len(e.ep), sims=e.sims,
        start_distance=round(e.start_distance, 6), final_distance=round(e.distance, 6),
        best_distance=round(e.best_distance, 6), failure_classes=dict(e.failures), recoveries=dict(e.recoveries),
        invalid_outputs=e.invalid_outputs, policy_calls=e.policy_calls))
