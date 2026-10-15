import json
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from analogft import paths
from analogft.circuit import simulate_batch, simulate
from analogft.circuit.design import KNOBS, Design, nominal_design
from analogft.circuit.simulator import SimResult
from analogft.drive_check import DriveUploadIncomplete, verify_manifest, write_manifest


def _random_design(rng) -> Design:
    return Design(**{k: float(np.exp(rng.uniform(np.log(lo), np.log(hi)))) for k, (lo, hi) in KNOBS.items()})


def test_determinism_without_cache():
    a = simulate(nominal_design(), use_cache=False)
    b = simulate(nominal_design(), use_cache=False)
    assert not a.cached and not b.cached and a.metrics == b.metrics


@pytest.mark.parametrize("kind", ["all_min", "all_max", "ibias_max_widths_min", "mixed"])
def test_absurd_designs_never_raise(kind):
    lo = {k: v[0] for k, v in KNOBS.items()}
    hi = {k: v[1] for k, v in KNOBS.items()}
    widths = ["w_in", "w_load", "w_cs"]
    d = {"all_min": lo, "all_max": hi,
         "ibias_max_widths_min": {**hi, **{k: lo[k] for k in widths}},
         "mixed": {**lo, "ibias": hi["ibias"], "out_ratio": hi["out_ratio"], "cc": hi["cc"]}}[kind]
    r = simulate(Design(**d), use_cache=False)
    assert isinstance(r, SimResult)
    assert r.ok or r.failure is not None


def test_paths_local():
    assert paths.IS_COLAB is False
    assert paths.STORAGE_ROOT == paths.REPO_ROOT
    for d in (paths.DATA_DIR, paths.RUNS_DIR, paths.RESULTS_DIR):
        assert paths.STORAGE_ROOT in d.parents


def test_batch_matches_sequential():
    rng = np.random.default_rng(1)
    ds = [_random_design(rng) for _ in range(20)]
    seq = [simulate(d, use_cache=False) for d in ds]
    par = simulate_batch(ds, workers=3, use_cache=False)
    for s, p in zip(seq, par):
        assert s.ok == p.ok and s.failure == p.failure and s.metrics == p.metrics


def test_manifest_verify(tmp_path: Path):
    (tmp_path / "a.csv").write_text("x,y\n1,2\n3,4\n")
    (tmp_path / "b.jsonl").write_text('{"a":1}\n{"a":2}\n')
    mf = json.loads(write_manifest(tmp_path).read_text())
    assert mf["files"]["a.csv"]["rows"] == 2 and mf["files"]["b.jsonl"]["rows"] == 2
    assert verify_manifest(tmp_path) == (True, [])
    (tmp_path / "a.csv").write_text("x,y\n1,2\n")       # truncated upload
    (tmp_path / "b.jsonl").unlink()
    ok, problems = verify_manifest(tmp_path)
    assert not ok and len(problems) == 2
    with pytest.raises(DriveUploadIncomplete, match="not finished yet"):
        verify_manifest(tmp_path, raise_on_error=True)
