import math
from dataclasses import replace

import numpy as np
import pytest

from analogft.actions import ACTION_IDS, apply
from analogft.circuit import KNOBS, nominal_design
from analogft.dataset import (ACTION_KNOBS, BuildConfig, assign_splits, build, check_no_leakage,
                              inverse_actions, make_spec, sample_start, sample_targets)
from analogft.shortfall import n_unsaturated, shortfall_terms
from analogft.specs import Spec, spec_distance
from analogft.circuit import simulate


def test_starts_are_on_the_lattice_and_solvable():
    rng = np.random.default_rng(1)
    cfg = BuildConfig()
    for target in sample_targets(rng, 30, 3.0):
        start, k = sample_start(rng, target, cfg)
        assert cfg.k_total_min <= sum(abs(v) for v in k.values()) <= cfg.k_total_max
        assert all(abs(v) <= cfg.k_range for v in k.values())
        for knob, (lo, hi) in KNOBS.items():  # nothing was clipped
            assert lo <= getattr(start, knob) <= hi
        for knob in KNOBS:  # non-action knobs untouched
            if knob not in ACTION_KNOBS:
                assert getattr(start, knob) == getattr(target, knob)
        d = start
        for a in inverse_actions(k):  # real action application, including clip()
            d = apply(d, a)
        for knob in KNOBS:
            assert getattr(d, knob) == pytest.approx(getattr(target, knob), rel=1e-9)
        assert len(inverse_actions(k)) <= cfg.k_total_max


def test_targets_within_range():
    nom = nominal_design()
    for t in sample_targets(np.random.default_rng(0), 20, 3.0):
        for knob, (lo, hi) in KNOBS.items():
            v = getattr(t, knob)
            assert max(lo, getattr(nom, knob) / 3) * (1 - 1e-9) <= v <= min(hi, getattr(nom, knob) * 3) * (1 + 1e-9)


def test_spec_is_met_by_its_target():
    r = simulate(nominal_design())
    rng = np.random.default_rng(0)
    for _ in range(50):
        assert spec_distance(r, make_spec(rng, r.metrics)) == 0.0


def test_shortfall_terms_match_spec_distance():
    r = simulate(nominal_design())
    spec = Spec(gain_db_min=80.0, ugf_hz_min=40e6, pm_deg_min=75.0, power_w_max=0.3e-3)
    regions = {d: v["saturated"] for d, v in r.regions.items()}
    m = {k: r.metrics[k] for k in ("dc_gain_db", "ugf_hz", "pm_deg", "power_w")}
    terms = shortfall_terms(spec.__dict__, m, n_unsaturated(regions))
    assert sum(terms.values()) == pytest.approx(spec_distance(r, spec))
    assert all(v > 0 for k, v in terms.items() if k != "sat")


def test_split_has_no_leakage():
    groups = [f"t{i:04d}" for i in range(100)] * 3
    split = assign_splits(groups, (0.8, 0.1, 0.1), seed=0)
    assert sorted(set(split.values())) == ["test", "train", "val"]
    assert [sum(v == s for v in split.values()) for s in ("train", "val", "test")] == [80, 10, 10]
    assert split == assign_splits(groups, (0.8, 0.1, 0.1), seed=0)  # deterministic
    recs = [{"group_id": g, "split": split[g]} for g in groups]
    check_no_leakage(recs)
    recs[0] = {"group_id": recs[0]["group_id"], "split": "test" if split[recs[0]["group_id"]] != "test" else "val"}
    with pytest.raises(AssertionError):
        check_no_leakage(recs)


def test_tiny_build_end_to_end():
    cfg = BuildConfig(seed=3, n_targets=4, starts_per_target=2, workers=2)
    out = build(cfg, log=lambda *_: None)
    recs, eps = out["records"], out["episodes"]
    assert recs and eps
    check_no_leakage(recs)
    assert {e["group_id"] for e in eps} == {r["group_id"] for r in recs}
    ids = [r["id"] for r in recs]
    assert len(ids) == len(set(ids))
    for r in recs:
        assert r["distance"] > 0
        assert r["ranking"][0] == r["label_action"] and set(r["ranking"]) == set(r["action_outcomes"])
        imps = [r["action_outcomes"][a]["improvement"] for a in r["ranking"]]
        assert imps == sorted(imps, reverse=True)
        assert r["best_improves"] == (imps[0] > 0)
        assert [m["role"] for m in r["messages"]] == ["system", "user", "assistant"]
        assert all(a in ACTION_IDS for a in r["available_actions"])
    for e in eps:  # episode start distance matches the step-0 record
        assert 0 < e["start_distance"] <= cfg.max_start_distance
