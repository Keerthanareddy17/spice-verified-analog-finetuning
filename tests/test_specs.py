import pytest

from analogft.circuit.design import nominal_design
from analogft.circuit.simulator import FailureType, SimResult, simulate
from analogft.specs import Spec, check, is_met, spec_distance

SPEC = Spec(gain_db_min=60, ugf_hz_min=1e7, pm_deg_min=50, power_w_max=1e-3)


def test_nominal_meets_sample_spec():
    r = simulate(nominal_design())
    assert is_met(r, SPEC) and spec_distance(r, SPEC) == 0.0


def test_distance_components():
    r = simulate(nominal_design())
    tight = Spec(gain_db_min=r.metrics["dc_gain_db"] + 10, ugf_hz_min=r.metrics["ugf_hz"] * 10,
                 pm_deg_min=r.metrics["pm_deg"] + 15, power_w_max=r.metrics["power_w"] / 10)
    assert not is_met(r, tight)
    assert spec_distance(r, tight) == pytest.approx(4.0, abs=1e-6)  # 1+1+1+1


def test_failed_sim_penalty():
    r = SimResult(ok=False, failure=FailureType.NONCONVERGENCE)
    assert spec_distance(r, SPEC) == 10.0 and not check(r, SPEC)["met"]


def test_unsaturated_penalty_and_met_false():
    r = simulate(nominal_design())
    r.regions["m1"]["saturated"] = False
    r.ok = False
    assert spec_distance(r, SPEC) == pytest.approx(1.0)
    assert not is_met(r, SPEC)
