import math

from analogft.relabel import rank_actions, relabel_record, tied_best
from analogft.shortfall import margin, slack_terms

SPEC = {"gain_db_min": 60.0, "ugf_hz_min": 1e7, "pm_deg_min": 60.0, "power_w_max": 1e-3}


def m(gain=70.0, ugf=1e8, pm=75.0, power=5e-4):
    return {"dc_gain_db": gain, "ugf_hz": ugf, "pm_deg": pm, "power_w": power}


def out(metrics, imp=1.0):
    return {"improvement": imp, "distance_after": 0.0, "metrics": metrics, "n_unsat": 0, "failure": None}


def test_slack_units_and_margin():
    s = slack_terms(SPEC, m(gain=70, ugf=1e8, pm=75, power=1e-4))
    assert math.isclose(s["gain"], 1.0) and math.isclose(s["ugf"], 1.0)
    assert math.isclose(s["pm"], 1.0) and math.isclose(s["power"], 1.0)
    assert margin(SPEC, m(gain=61)) == 0.1  # gain slack is the smallest
    assert margin(SPEC, {"dc_gain_db": None, "ugf_hz": 1, "pm_deg": 1, "power_w": 1}) == -math.inf


def test_tie_prefers_largest_margin_then_id_order():
    outcomes = {"cc_down": out(m(gain=60.5)), "ibias_down": out(m(gain=65)), "cc_up": out(m(gain=65)),
                "w_in_up": out(m(), imp=0.5)}
    ranking = rank_actions(outcomes, SPEC)
    assert ranking[0] == "cc_up"          # margins of cc_up and ibias_down are equal: id order (cc_up first)
    assert ranking[1] == "ibias_down" and ranking[2] == "cc_down" and ranking[3] == "w_in_up"
    assert tied_best(outcomes, ranking) == ["cc_up", "ibias_down", "cc_down"]


def test_no_tie_means_improvement_wins_over_margin():
    outcomes = {"cc_up": out(m(gain=60.1), imp=1.0), "cc_down": out(m(gain=90), imp=0.9)}
    assert rank_actions(outcomes, SPEC) == ["cc_up", "cc_down"]
    assert tied_best(outcomes, ["cc_up", "cc_down"]) == []


def test_relabel_is_idempotent_on_real_record():
    import json
    from analogft import paths
    p = paths.DATA_DIR / "phase2" / "val.jsonl"
    if not p.exists():
        return
    rec = json.loads(p.read_text().splitlines()[0])
    assert relabel_record(rec) == relabel_record(relabel_record(rec)) == rec
