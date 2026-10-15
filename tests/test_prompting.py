import json

from analogft.actions import ACTION_IDS
from analogft.prompting import (SYSTEM_PROMPT, estimate_tokens, format_prompt, format_response,
                                parse_response)

SPEC = {"gain_db_min": 70.0, "ugf_hz_min": 20e6, "pm_deg_min": 50.0, "power_w_max": 0.5e-3}
DESIGN = {"w_in": 3.7e-6, "l_in": 0.5e-6, "w_load": 5.8e-6, "l_load": 0.5e-6, "w_cs": 79e-6,
          "l_cs": 0.5e-6, "l_bias": 0.5e-6, "ibias": 20e-6, "tail_ratio": 1.4, "out_ratio": 9.5, "cc": 1e-12}
REGIONS = {f"m{i}": True for i in range(1, 9)}


def state(**kw):
    s = {"spec": SPEC, "design": DESIGN, "regions": dict(REGIONS), "available_actions": ACTION_IDS,
         "metrics": {"dc_gain_db": 74.0, "ugf_hz": 25e6, "pm_deg": 41.2, "power_w": 0.4e-3}}
    s.update(kw)
    return s


def outcome(pm, ugf, n_unsat=0, **extra):
    return {"metrics": {"dc_gain_db": 74.0, "ugf_hz": ugf, "pm_deg": pm, "power_w": 0.4e-3},
            "n_unsat": n_unsat, **extra}


def test_prompt_contents_and_size():
    p = format_prompt(state())
    assert "PM (short 8.8 deg)" in p and "Unsaturated devices: none" in p
    assert all(f"{a}:" in p for a in ACTION_IDS)
    assert estimate_tokens(p) < 350


def test_prompt_lists_only_unsaturated_and_available():
    s = state(regions={**REGIONS, "m6": False}, available_actions=["cc_up", "cc_down"])
    p = format_prompt(s)
    assert "Unsaturated devices: M6" in p and "ibias_up:" not in p


def test_response_round_trip():
    resp = format_response("cc_up", outcome(41.2, 25e6), outcome(45.1, 19.75e6), SPEC)
    assert "\n" not in resp and len(json.loads(resp)["reason"].split()) < 25
    assert "PM 41.2 < 50 deg is the largest shortfall" in resp and "PM +3.9 deg" in resp
    assert "UGF -21%" in resp
    assert parse_response(resp, ACTION_IDS) == ("cc_up", None)


def test_response_for_saturation_shortfall():
    before = outcome(60.0, 25e6, n_unsat=1, unsat=["m6"])
    resp = format_response("w_cs_up", before, outcome(60.0, 25e6, 0), SPEC)
    assert "M6 out of saturation" in resp and "unsaturated devices 1->0" in resp


def test_parse_tolerates_noise():
    avail = ["cc_up", "cc_down"]
    assert parse_response('```json\n{"action": "cc_up", "reason": "x"}\n```', avail) == ("cc_up", None)
    assert parse_response('Sure! {"action":"cc_down"} hope that helps', avail) == ("cc_down", None)
    assert parse_response('{"note": {}} then {"action": "cc_up"}', avail) == ("cc_up", None)


def test_parse_errors():
    avail = ["cc_up"]
    assert parse_response("I would increase Cc", avail) == (None, "no_json")
    assert parse_response('{"action": "cc_up", "reason": "trunc', avail) == (None, "no_json")
    assert parse_response('{"act": "cc_up"}', avail) == (None, "no_json")
    assert parse_response('{"action": 3}', avail) == (None, "no_json")
    assert parse_response("", avail) == (None, "no_json")
    assert parse_response('{"action": "make_it_better"}', avail) == (None, "unknown_action")
    assert parse_response('{"action": "cc_down"}', avail) == (None, "unavailable_action")


def test_system_prompt_is_neutral():
    assert "JSON" in SYSTEM_PROMPT and "cc_up" not in SYSTEM_PROMPT
