import json
import re

import pytest

from analogft import tracing as T
from analogft.actions import apply
from analogft.agent import SimPool, design_key, run_agent
from analogft.agent_eval import load_episodes, summarize_agent
from analogft.circuit import Design
from analogft.mock import FaultySim, MockBackend
from analogft.policies import LLMPolicy, Policy, RandomPolicy, RulesPolicy
from analogft.predict import Backend, Prediction


@pytest.fixture(scope="module")
def eps():
    return load_episodes("test")[:6]


@pytest.fixture(scope="module")
def pool():
    with SimPool(workers=1) as p:
        yield p


def run(eps, policy, pool, recovery, **kw):
    tw = T.TraceWriter()
    out = run_agent(eps, policy, recovery=recovery, sim=pool, trace=tw, run_id="t", **kw)
    return tw, out


class Garbage(Backend):
    name = "garbage"
    def generate(self, batch, keys=None):
        return [("no idea", {}) for _ in batch]


class FirstThenValid(Backend):
    """Invalid answer on the first ask, a valid answer on the re-ask."""
    name = "reask"
    def generate(self, batch, keys=None):
        out = []
        for m in batch:
            u = m[1]["content"]
            listed = re.findall(r"^([a-z_]+): ", u.split("Actions:")[1], flags=re.M)
            out.append((json.dumps({"action": listed[0], "reason": "x"}) if "previous answer was invalid" in u else "hmm", {}))
        return out


def test_design_key_survives_up_then_down():
    d = Design.from_dict(load_episodes("test")[0]["start_design"])
    assert design_key(apply(apply(d, "cc_up"), "cc_down")) == design_key(d)
    assert design_key(apply(d, "cc_up")) != design_key(d)


def test_invalid_output_without_recovery_wastes_the_step(eps, pool):
    tw, out = run(eps[:3], LLMPolicy(Garbage()), pool, recovery=False)
    assert all(e["outcome"] == "budget_exhausted" and e["steps"] == 8 and e["sims"] == 0 for e in out)
    assert all(s["action"] is None and s["error"] == "no_json" for s in tw.steps)
    assert all(e["failure_classes"][T.INVALID_OUTPUT] == 8 for e in out) and not any(e["recoveries"] for e in out)


def test_reask_then_fallback(eps, pool):
    tw, out = run(eps[:3], LLMPolicy(FirstThenValid()), pool, recovery=True)
    s0 = [s for s in tw.steps if s["step"] == 0]
    assert all(s["recoveries"][0]["type"] == T.REASK and s["attempts"] == 2 and s["action"] for s in s0)
    tw2, out2 = run(eps[:3], LLMPolicy(Garbage()), pool, recovery=True, fallback=RulesPolicy())
    s = tw2.steps[0]
    assert [r["type"] for r in s["recoveries"]] == [T.REASK, T.FALLBACK_RULES] and s["used_fallback"] and s["action"]


class Oscillate(Policy):
    name = "osc"
    def choose(self, states, notes=None):
        out = []
        for s in states:
            want = "cc_up" if s["design"]["cc"] < 1.2e-12 else "cc_down"
            out.append(Prediction("", want if want in s["available_actions"] else s["available_actions"][0], None, {}))
        return out


def test_loop_detected_and_blocked(eps, pool):
    e = [x for x in eps if x["start_design"]["cc"] < 1.2e-12 / 1.3][:2] or eps[:2]
    tw, out = run(e, Oscillate(), pool, recovery=False)
    assert sum(o["failure_classes"].get(T.LOOP, 0) for o in out) > 0
    tw2, out2 = run(e, Oscillate(), pool, recovery=True)
    steps = [s for s in tw2.steps if any(r["type"] == T.LOOP_BLOCK_REASK for r in s["recoveries"])]
    assert steps, "loop recovery did not fire"
    s = steps[0]
    looped = s["recoveries"][0]["detail"]
    assert s["action"] != looped        # the blocked action was removed, the re-ask chose something else


def test_sim_failure_rollback_vs_adopt(eps, pool):
    faulty = FaultySim(pool, every=1)    # every new design fails to simulate
    tw, out = run(eps[:2], RulesPolicy(), faulty, recovery=True)
    s = tw.steps[0]
    assert T.SIM_FAILURE in s["failure_classes"] and s["recoveries"][-1]["type"] == T.SIM_ROLLBACK
    assert s["distance_after"] == s["distance_before"]          # rolled back: state unchanged
    assert tw.steps[1]["action"] != s["action"]                 # the failing action is blocked at that state
    faulty2 = FaultySim(pool, every=1)
    tw2, _ = run(eps[:2], RulesPolicy(), faulty2, recovery=False)
    assert tw2.steps[0]["distance_after"] == 10.0                # adopted the failed state


def test_no_progress_rollback_and_schema(eps, pool):
    tw, out = run(eps, RandomPolicy(0), pool, recovery=True)
    assert sum(o["failure_classes"].get(T.NO_PROGRESS, 0) for o in out) > 0
    assert sum(o["recoveries"].get(T.PROGRESS_ROLLBACK, 0) for o in out) > 0
    for s in tw.steps:
        for k in ("run_id", "policy", "episode_id", "step", "state", "raw", "error", "action", "failure_classes",
                  "recoveries", "sim", "distance_before", "distance_after", "improvement", "latency_ms"):
            assert k in s
    for o in out:
        assert o["steps"] == sum(1 for s in tw.steps if s["episode_id"] == o["episode_id"])
        assert o["outcome"] in T.OUTCOMES and (o["steps_to_success"] is not None) == o["solved"]
        if o["outcome"] == "budget_exhausted":
            assert o["failure_classes"][T.BUDGET_EXHAUSTED] == 1


def test_summary_and_budget_curve(eps, pool):
    tw, out = run(eps, RulesPolicy(), pool, recovery=False)
    m = summarize_agent(tw.steps, out)
    curve = list(m["success_by_budget"].values())
    assert curve == sorted(curve) and abs(curve[-1] - m["success_rate"]) < 1e-9
    lo, hi = m["success_ci"]
    assert lo <= m["success_rate"] <= hi


def test_samples_run_independent_rollouts(eps, pool):
    tw, out = run(eps[:2], LLMPolicy(MockBackend()), pool, recovery=True, samples=3)
    assert len(out) == 6 and len({o["episode_id"] for o in out}) == 6


def test_expert_iteration_dataset_rules(tmp_path):
    from analogft.dataset import read_jsonl
    from analogft import paths
    from analogft.expert_iteration import build_rl_dataset
    train = read_jsonl(paths.DATA_DIR / "phase2" / "train.jsonl")[:50]
    eps = load_episodes("train")[:6]
    with SimPool(workers=1) as p:
        tw = T.TraceWriter(keep_state_full=True)
        out = run_agent(eps, LLMPolicy(MockBackend()), recovery=True, sim=p, trace=tw, run_id="rl", samples=2)
    mixed, stats = build_rl_dataset(train, tw.steps, out, tmp_path / "rl.jsonl")
    solved_ids = {e["episode_id"] for e in out if e["solved"]}
    assert stats["rollouts"] == 12 and stats["rollouts_solved"] == len(solved_ids)
    assert len(mixed) == len(train) + stats["new_examples"] == stats["train_examples_after"]
    new = [r for r in mixed if r.get("source") == "expert_iteration"]
    for r in new:  # only solved episodes, improving non-fallback steps, in the training format
        ep_id = r["id"][3:].rsplit("_k", 1)[0]
        assert ep_id in solved_ids
        assert r["improvement"] > 0 and [m["role"] for m in r["messages"]] == ["system", "user", "assistant"]
        step = next(s for s in tw.steps if s["episode_id"] == ep_id and s["step"] == r["step_index"])
        assert not step["used_fallback"] and json.loads(r["messages"][2]["content"])["action"] == step["action"]
    assert (tmp_path / "rl.jsonl").exists() and (tmp_path / "rl.stats.json").exists()
    assert len({r["messages"][1]["content"] for r in new}) == len(new)  # one label per prompt


def test_chunked_rollouts_resume(tmp_path, pool):
    from analogft.phase4_run import load_rollouts, run_rollouts, write_rollouts_summary
    eps = load_episodes("train")[:4]
    logs = []
    run_rollouts(LLMPolicy(MockBackend()), eps, tmp_path, pool, samples=2, chunk_size=2, log=logs.append)
    steps, out = load_rollouts(tmp_path)
    assert len(out) == 8 and all("state_full" in s for s in steps)
    n_logs = len(logs)
    logs.clear()
    run_rollouts(LLMPolicy(MockBackend()), eps, tmp_path, pool, samples=2, chunk_size=2, log=logs.append)
    assert all("already done" in l for l in logs) and len(logs) == 2          # nothing re-run
    summ = write_rollouts_summary(tmp_path, out, tmp_path / "s.json", 2, 0.8)
    assert summ["rollouts"] == 8 and summ["base_episodes"] == 4
