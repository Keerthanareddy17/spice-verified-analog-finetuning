import pytest

from analogft.baselines import majority_label, textbook_pick
from analogft.evaluation import evaluate, evaluate_random, score_pick


def rec(label, imps, avail=None):
    """Record whose actions have the given improvements (dict id -> improvement)."""
    ranking = sorted(imps, key=lambda a: -imps[a])
    return {"label_action": label, "ranking": ranking, "available_actions": avail or list(imps),
            "action_outcomes": {a: {"improvement": v} for a, v in imps.items()}}


R1 = rec("a", {"a": 0.5, "b": 0.2, "c": -0.1, "d": -0.3})
R2 = rec("b", {"a": 0.1, "b": 0.4, "c": 0.4, "d": -0.2, "e": -0.5})  # b and c tie


def test_metrics_hand_example():
    m = evaluate([R1, R2], ["b", None])
    assert m["valid_rate"] == 0.5
    assert m["top1"] == 0.0 and m["top1_exact"] == 0.0
    assert m["top3"] == 0.5          # 'b' is rank 2 in R1; invalid counts as wrong
    assert m["improve_rate"] == 0.5
    assert m["mean_regret"] == pytest.approx((0.3 + 0.4) / 2)  # invalid = improvement 0


def test_ties_are_tie_aware():
    s = score_pick(R2, "c")  # same improvement as the label 'b'
    assert s["top1"] and not s["top1_exact"] and s["regret"] == 0
    assert score_pick(R2, "a")["top3"] and not score_pick(R2, "e")["top3"]  # a is rank 3, e is rank 5


def test_random_is_exact_expectation():
    m = evaluate_random([R1])
    assert m["top1"] == pytest.approx(0.25) and m["improve_rate"] == pytest.approx(0.5)
    assert m["top3"] == pytest.approx(0.75)
    assert m["mean_regret"] == pytest.approx(0.5 - (0.5 + 0.2 - 0.1 - 0.3) / 4)


def test_majority_and_rule_basics():
    assert majority_label([{"label_action": "x"}, {"label_action": "y"}, {"label_action": "y"}]) == "y"
    spec = {"gain_db_min": 70.0, "ugf_hz_min": 20e6, "pm_deg_min": 50.0, "power_w_max": 1e-3}
    regs = {f"m{i}": True for i in range(1, 9)}
    base = {"spec": spec, "regions": regs, "available_actions": ["cc_up", "w_in_up", "ibias_down", "l_load_up"]}
    pm_low = {"dc_gain_db": 75.0, "ugf_hz": 25e6, "pm_deg": 30.0, "power_w": 5e-4}
    assert textbook_pick({**base, "metrics": pm_low}) == "cc_up"
    # PM fix unavailable -> falls back to the next shortfall (none) -> invalid
    assert textbook_pick({**base, "metrics": pm_low, "available_actions": ["w_in_up"]}) is None
    # PM shortfall = 20/15 = 1.33 beats one unsaturated device (1.0); with PM fine, the device rule wins
    unsat = {**base, "metrics": pm_low, "regions": {**regs, "m6": False}, "available_actions": ["w_cs_up", "cc_up"]}
    assert textbook_pick(unsat) == "cc_up"
    ok_pm = {**pm_low, "pm_deg": 55.0}
    assert textbook_pick({**unsat, "metrics": ok_pm}) == "w_cs_up"
