from dataclasses import replace

import numpy as np
import pytest

from analogft.circuit.design import KNOBS, nominal_design
from analogft.circuit.netlist import build_netlist
from analogft.circuit.simulator import FailureType, ac_metrics, simulate
from analogft.circuit import simulate_batch_with_stats


def test_nominal_ok_and_in_range():
    r = simulate(nominal_design())
    assert r.ok and r.failure is None
    m = r.metrics
    assert m["dc_gain_db"] >= 60 and 50 <= m["pm_deg"] <= 70
    assert 1e7 <= m["ugf_hz"] < 1e8 and m["power_w"] < 1e-3
    assert all(x["saturated"] for x in r.regions.values())
    assert 0.3 < m["vout_dc"] < 1.5


def test_cache_hit_and_same_result():
    a = simulate(nominal_design())
    b = simulate(nominal_design())
    assert not a.cached and b.cached and a.metrics == b.metrics


def test_longer_l_gives_more_gain():
    base = nominal_design()
    longer = replace(base, l_in=1.0e-6, l_load=1.0e-6, l_cs=1.0e-6).clip()
    assert simulate(longer).metrics["dc_gain_db"] > simulate(base).metrics["dc_gain_db"] + 1


def test_cc_tradeoff():
    lo = simulate(replace(nominal_design(), cc=0.5e-12)).metrics
    hi = simulate(replace(nominal_design(), cc=2.0e-12)).metrics
    assert hi["pm_deg"] > lo["pm_deg"] and hi["ugf_hz"] < lo["ugf_hz"]


def test_lowfreq_response_flat_and_in_phase():
    """The L/C loop-break must not distort the low-frequency gain."""
    import subprocess, tempfile, pathlib
    from analogft.circuit.simulator import ngspice_bin, parse_ac
    with tempfile.TemporaryDirectory() as t:
        p = pathlib.Path(t)
        (p / "n.cir").write_text(build_netlist(nominal_design()))
        subprocess.run([ngspice_bin(), "-b", "n.cir"], cwd=p, capture_output=True, timeout=20)
        f, h = parse_ac(p / "ac.dat")
    db = 20 * np.log10(np.abs(h))
    low = f <= 1e3
    assert db[low].max() - db[low].min() < 0.2
    assert abs(np.degrees(np.angle(h[0]))) < 5


def test_not_saturated_keeps_metrics():
    """Ran-but-invalid is distinct from failed: metrics and regions are kept."""
    r = simulate(replace(nominal_design(), w_load=1e-6, l_load=2e-6))
    assert r.failure == FailureType.DEVICE_NOT_SATURATED
    assert not r.ok and r.ran and "dc_gain_db" in r.metrics
    assert not r.regions["m4"]["saturated"]


def test_ac_metrics_missing_crossing():
    f = np.logspace(0, 10, 100)
    h = np.full(100, 10.0 + 0j)          # flat 20 dB, never crosses 0 dB
    assert isinstance(ac_metrics(f, h), str)


def test_ac_metrics_single_pole():
    f = np.logspace(0, 10, 400)
    h = 1000.0 / (1 + 1j * f / 1e3)       # A0=60 dB, pole 1 kHz -> UGF ~1 MHz, PM ~90
    m = ac_metrics(f, h)
    assert m["dc_gain_db"] == pytest.approx(60, abs=0.1)
    assert m["ugf_hz"] == pytest.approx(1e6, rel=0.02)
    assert m["pm_deg"] == pytest.approx(90, abs=1)


def test_batch_order_and_stats():
    ds = [replace(nominal_design(), cc=c * 1e-12) for c in (0.5, 1.0, 1.5, 2.0)]
    rs, st = simulate_batch_with_stats(ds, workers=2)
    assert [r.ok for r in rs] == [True] * 4 and st.n == 4 and st.sims_per_s > 0
    assert rs[0].metrics["ugf_hz"] > rs[3].metrics["ugf_hz"]
