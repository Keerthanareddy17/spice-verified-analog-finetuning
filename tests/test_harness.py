import json

from analogft.evaluation import breakdown, per_state_scores, summarize_scores
from analogft.harness import make_eval_subset, save_evaluation, select
from analogft.predict import GroqBackend, Prediction, Predictor, Backend, _parse_duration, build_messages
from analogft.relabel import relabel_record
from analogft import paths
from analogft.dataset import read_jsonl


def fake_records(n=40):
    recs = []
    for i in range(n):
        step = i % 4
        outs = {"cc_up": {"improvement": 0.5, "distance_after": 0.0, "metrics": {}, "n_unsat": 0, "failure": None},
                "cc_down": {"improvement": -0.2, "distance_after": 1.0, "metrics": {}, "n_unsat": 0, "failure": None}}
        recs.append({"id": f"r{i}", "step_index": step, "label_action": "cc_up", "available_actions": list(outs),
                     "action_outcomes": outs, "ranking": ["cc_up", "cc_down"],
                     "spec": {"gain_db_min": 60.0, "ugf_hz_min": 1e7, "pm_deg_min": 60.0, "power_w_max": 1e-3},
                     "metrics": {"dc_gain_db": 50.0, "ugf_hz": 2e7, "pm_deg": 70.0, "power_w": 5e-4},
                     "regions": {"m1": True}})
    return recs


def test_subset_stratified_seeded():
    recs = fake_records(40)
    a, b = make_eval_subset(recs, 12, seed=1), make_eval_subset(recs, 12, seed=1)
    assert a == b and len(a) == 12 == len(set(a))
    steps = [r["step_index"] for r in select(recs, a)]
    assert all(steps.count(s) == 3 for s in range(4))
    assert make_eval_subset(recs, 12, seed=2) != a


def test_ci_brackets_mean_and_is_degenerate_for_constant():
    rows = per_state_scores(fake_records(20), ["cc_up"] * 10 + ["cc_down"] * 10)
    s = summarize_scores(rows, n_boot=500)
    lo, hi = s["ci"]["top1"]
    assert lo <= s["top1"] <= hi and lo < hi
    s2 = summarize_scores(per_state_scores(fake_records(20), ["cc_up"] * 20), n_boot=100)
    assert s2["ci"]["top1"] == [1.0, 1.0]


class StubBackend(Backend):
    def __init__(self, texts):
        self.texts = texts
    def generate(self, batch, keys):
        return [(self.texts[i % len(self.texts)], {"total_tokens": 10}) for i in range(len(batch))]


def test_predictor_and_save(tmp_path):
    recs = fake_records(4)
    pred = Predictor(StubBackend(['{"action": "cc_up", "reason": "x"}', "nonsense"]))
    # records lack prompt fields, so test via the parts that do not need them
    outs = pred.backend.generate([[]] * 4, [r["id"] for r in recs])
    from analogft.prompting import parse_response
    preds = [Prediction(t, *parse_response(t, r["available_actions"]), m) for (t, m), r in zip(outs, recs)]
    m = save_evaluation(tmp_path, recs, preds, "stub")
    assert m["n"] == 4 and m["valid_rate"] == 0.5 and m["errors"] == {"ok": 2, "no_json": 2}
    lines = [json.loads(x) for x in (tmp_path / "predictions.jsonl").read_text().splitlines()]
    assert lines[0]["action"] == "cc_up" and lines[1]["error"] == "no_json"


def test_predict_one_builds_prompt_from_live_state():
    rec = read_jsonl(paths.DATA_DIR / "phase2" / "val.jsonl")[0]
    state = {k: rec[k] for k in ("spec", "design", "metrics", "regions", "available_actions")}  # no id, no label
    msgs = build_messages(state)
    assert msgs == rec["messages"][:2]  # identical to the stored prompt
    seen = {}
    class Echo(Backend):
        def generate(self, batch, keys):
            seen["keys"] = keys
            return [('{"action": "%s", "reason": "r"}' % state["available_actions"][0], {})]
    p = Predictor(Echo()).predict_one(state)
    assert p.action == state["available_actions"][0] and p.error is None and len(seen["keys"][0]) == 16


def test_duration_parse():
    assert _parse_duration("1m30.5s") == 90.5 and _parse_duration("250ms") == 0.25 and _parse_duration("7.66s") == 7.66


def test_groq_cache_resume(tmp_path, monkeypatch):
    cache = tmp_path / "c.jsonl"
    b = GroqBackend("m", cache_path=cache, api_key="x", log=lambda *_: None)
    calls = []
    def fake_post(messages):
        calls.append(1)
        return ({"choices": [{"message": {"content": "hi", "reasoning": "r"}, "finish_reason": "stop"}],
                 "usage": {"prompt_tokens": 5, "completion_tokens": 7, "total_tokens": 12,
                           "completion_tokens_details": {"reasoning_tokens": 4}}}, {}, 0.1)
    monkeypatch.setattr(b, "_post", fake_post)
    out = b.generate([[{"role": "user", "content": "a"}]], ["k1"])
    assert out[0][0] == "hi" and out[0][1]["reasoning_tokens"] == 4 and calls == [1]
    b2 = GroqBackend("m", cache_path=cache, api_key="x", log=lambda *_: None)  # new process, same cache
    monkeypatch.setattr(b2, "_post", fake_post)
    assert b2.generate([[{"role": "user", "content": "a"}]], ["k1"])[0][0] == "hi" and calls == [1]
