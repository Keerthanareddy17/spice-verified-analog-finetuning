from dataclasses import replace

import pytest

from analogft.actions import ACTIONS, ACTION_IDS, apply, available_actions
from analogft.circuit.design import KNOBS, Design, nominal_design


def test_nominal_inside_bounds():
    d = nominal_design()
    assert d == d.clip()
    for k, (lo, hi) in KNOBS.items():
        assert lo <= getattr(d, k) <= hi


def test_clip_clamps():
    d = replace(nominal_design(), cc=1.0, w_in=1e-9).clip()
    assert d.cc == KNOBS["cc"][1] and d.w_in == KNOBS["w_in"][0]


def test_roundtrip_dict():
    d = nominal_design()
    assert Design.from_dict(d.to_dict()) == d


def test_action_set():
    assert len(ACTIONS) == 14 and len(set(ACTION_IDS)) == 14
    assert "cc_up" in ACTION_IDS and "cc_down" in ACTION_IDS


def test_apply_scales_by_1p3():
    d = nominal_design()
    assert apply(d, "cc_up").cc == pytest.approx(d.cc * 1.3)
    assert apply(d, "cc_down").cc == pytest.approx(d.cc / 1.3)


def test_clipping_noop_makes_action_unavailable():
    d = replace(nominal_design(), cc=KNOBS["cc"][1])
    ids = [a.id for a in available_actions(d)]
    assert "cc_up" not in ids and "cc_down" in ids
    assert len(available_actions(nominal_design())) == 14


def test_descriptions_have_no_metric_hints():
    for a in ACTIONS:
        for word in ("gain", "phase", "bandwidth", "power", "margin", "speed"):
            assert word not in a.description.lower()
