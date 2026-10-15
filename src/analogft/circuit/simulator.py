"""Run ngspice on a Design and turn the output into a typed SimResult.

Two separate notions of failure:
  * the simulation FAILED (no usable numbers): ok=False, metrics empty;
  * the simulation RAN but the design is invalid (e.g. a device left
    saturation): ok=False with failure=DEVICE_NOT_SATURATED, metrics kept.
"""
from __future__ import annotations

import functools
import hashlib
import json
import math
import re
import shutil
import subprocess
import tempfile
import time
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path

import numpy as np

from .. import paths
from .design import Design
from .models import TEMP_NOM
from .netlist import DEVICES, build_netlist

TIMEOUT_S = 10.0
VDS_MARGIN = 0.05  # V, saturation margin on top of |Vdsat|
LF_PHASE_TOL_DEG = 30.0  # |phase at 1 Hz| must be below this to trust the phase


class FailureType(str, Enum):
    NONCONVERGENCE = "NONCONVERGENCE"
    TIMEOUT = "TIMEOUT"
    MEASUREMENT_MISSING = "MEASUREMENT_MISSING"
    DEVICE_NOT_SATURATED = "DEVICE_NOT_SATURATED"
    PARSE_ERROR = "PARSE_ERROR"
    NGSPICE_ERROR = "NGSPICE_ERROR"


@dataclass
class SimResult:
    ok: bool
    metrics: dict[str, float] = field(default_factory=dict)
    regions: dict[str, dict] = field(default_factory=dict)  # device -> vds, vdsat, vgs, vth, saturated
    failure: FailureType | None = None
    message: str = ""
    runtime_s: float = 0.0
    ngspice_version: str = ""
    cached: bool = False

    @property
    def ran(self) -> bool:
        """True when ngspice produced numbers (metrics present), valid design or not."""
        return bool(self.metrics)

    def to_json(self) -> str:
        d = asdict(self)
        d["failure"] = self.failure.value if self.failure else None
        return json.dumps(d)

    @classmethod
    def from_json(cls, s: str) -> "SimResult":
        d = json.loads(s)
        d["failure"] = FailureType(d["failure"]) if d["failure"] else None
        return cls(**d)


@functools.lru_cache(maxsize=1)
def ngspice_bin() -> str:
    exe = shutil.which("ngspice")
    if exe is None:
        raise RuntimeError("ngspice not found on PATH (brew install ngspice / apt install ngspice)")
    return exe


@functools.lru_cache(maxsize=1)
def ngspice_version() -> str:
    out = subprocess.run([ngspice_bin(), "--version"], capture_output=True, text=True, timeout=20).stdout
    m = re.search(r"ngspice-(\d+(?:\.\d+)?)", out)
    return m.group(1) if m else "unknown"


_NUM = r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?"
_KV = re.compile(rf"^\s*(\S+)\s*=\s*({_NUM})\s*$", re.M)
_NONCONV = re.compile(r"no convergence|singular matrix|timestep too small|gmin stepping failed"
                      r"|source stepping failed|iteration limit", re.I)


def netlist_key(netlist: str) -> str:
    return hashlib.sha256((netlist + "|ngspice-" + ngspice_version()).encode()).hexdigest()


def _fail(kind: FailureType, msg: str, t0: float, **kw) -> SimResult:
    return SimResult(ok=False, failure=kind, message=msg, runtime_s=time.time() - t0,
                     ngspice_version=ngspice_version(), **kw)


def device_region(vgs: float, vds: float, vth: float, vdsat: float) -> bool:
    """Saturated iff |Vds| >= |Vdsat| + 50 mV and |Vgs| > |Vth| (|.| handles PMOS signs)."""
    return abs(vds) >= abs(vdsat) + VDS_MARGIN and abs(vgs) > abs(vth)


def parse_ac(path: Path) -> tuple[np.ndarray, np.ndarray]:
    """Read ngspice wrdata output: columns freq, re, im -> (freq, complex v(out))."""
    arr = np.loadtxt(path, ndmin=2)
    if arr.shape[1] < 3 or arr.shape[0] < 5:
        raise ValueError(f"unexpected AC data shape {arr.shape}")
    return arr[:, 0], arr[:, 1] + 1j * arr[:, 2]


def ac_metrics(freq: np.ndarray, h: np.ndarray) -> dict[str, float] | str:
    """Gain/UGF/PM from the complex response, or a string describing what is missing."""
    mag_db = 20 * np.log10(np.maximum(np.abs(h), 1e-30))
    phase = np.degrees(np.unwrap(np.angle(h)))
    phase = phase - 360.0 * np.round(phase[0] / 360.0)  # start in (-180, 180]
    if abs(phase[0]) > LF_PHASE_TOL_DEG:
        return f"low-frequency phase is {phase[0]:.0f} deg, expected ~0 (wrong polarity or broken loop)"
    out = {"dc_gain_db": float(mag_db[0])}
    above = mag_db > 0
    if not above[0]:
        return "gain below 0 dB at 1 Hz, no unity-gain crossing"
    idx = np.where(above[:-1] & ~above[1:])[0]
    if len(idx) == 0:
        return "no 0 dB crossing below 10 GHz"
    i = idx[0]  # first downward crossing; interpolate in log-frequency
    frac = mag_db[i] / (mag_db[i] - mag_db[i + 1])
    lf = math.log10(freq[i]) + frac * (math.log10(freq[i + 1]) - math.log10(freq[i]))
    ph = phase[i] + frac * (phase[i + 1] - phase[i])
    out["ugf_hz"] = float(10 ** lf)
    out["pm_deg"] = float(180.0 + ph)
    return out


def _run(netlist: str, t0: float) -> SimResult:
    with tempfile.TemporaryDirectory(prefix="analogft_") as tmp:
        tmpd = Path(tmp)
        (tmpd / "n.cir").write_text(netlist)
        try:
            proc = subprocess.run([ngspice_bin(), "-b", "n.cir"], cwd=tmpd, capture_output=True,
                                  text=True, timeout=TIMEOUT_S)
        except subprocess.TimeoutExpired:
            return _fail(FailureType.TIMEOUT, f"ngspice exceeded {TIMEOUT_S}s", t0)
        text = proc.stdout + "\n" + proc.stderr
        if _NONCONV.search(text) and "v(out)" not in proc.stdout:
            return _fail(FailureType.NONCONVERGENCE, "operating point did not converge", t0)
        vals = {k: float(v) for k, v in _KV.findall(proc.stdout)}
        need = ["v(out)", "@vdd[i]"] + [f"@{m}[{p}]" for m in DEVICES
                                         for p in ("vgs", "vds", "von", "vdsat", "id")]
        missing = [k for k in need if k not in vals]
        if missing:
            kind = FailureType.NGSPICE_ERROR if proc.returncode != 0 or "rror" in text else FailureType.PARSE_ERROR
            return _fail(kind, f"missing values: {missing[:3]}...; tail: {text[-200:]!r}", t0)
        regions = {}
        for m in DEVICES:
            vgs, vds, vth, vdsat = (vals[f"@{m}[{p}]"] for p in ("vgs", "vds", "von", "vdsat"))
            regions[m] = {"vgs": vgs, "vds": vds, "vth": vth, "vdsat": vdsat,
                          "saturated": device_region(vgs, vds, vth, vdsat)}
        vdd_v = None
        mt = re.search(rf"^Vdd\s+vdd\s+0\s+({_NUM})", netlist, re.M)
        vdd_v = float(mt.group(1)) if mt else float("nan")
        metrics = {"power_w": vdd_v * abs(vals["@vdd[i]"]), "vout_dc": vals["v(out)"]}
        ac_file = tmpd / "ac.dat"
        if not ac_file.exists():
            return _fail(FailureType.MEASUREMENT_MISSING, "AC analysis produced no data", t0,
                         metrics=metrics, regions=regions)
        try:
            freq, h = parse_ac(ac_file)
        except Exception as e:  # noqa: BLE001
            return _fail(FailureType.PARSE_ERROR, f"AC parse: {e}", t0, metrics=metrics, regions=regions)
        ac = ac_metrics(freq, h)
        if isinstance(ac, str):
            return _fail(FailureType.MEASUREMENT_MISSING, ac, t0, metrics=metrics, regions=regions)
        metrics.update(ac)
        bad = [m for m, r in regions.items() if not r["saturated"]]
        res = SimResult(ok=not bad, metrics=metrics, regions=regions,
                        runtime_s=time.time() - t0, ngspice_version=ngspice_version())
        if bad:
            res.failure = FailureType.DEVICE_NOT_SATURATED
            res.message = "not saturated: " + ",".join(bad)
        return res


def _cache_path(key: str) -> Path:
    return paths.CACHE_DIR / key[:2] / f"{key}.json"


def simulate(design: Design, temp_c: float = TEMP_NOM, vdd_scale: float = 1.0,
             use_cache: bool = True) -> SimResult:
    """Simulate one design. Results (except TIMEOUT) are cached on disk by netlist hash."""
    t0 = time.time()
    netlist = build_netlist(design, temp_c=temp_c, vdd_scale=vdd_scale)
    cp = _cache_path(netlist_key(netlist))
    if use_cache and cp.exists():
        try:
            r = SimResult.from_json(cp.read_text())
            r.cached = True
            return r
        except Exception:  # corrupt cache entry: recompute
            pass
    res = _run(netlist, t0)
    if use_cache and res.failure != FailureType.TIMEOUT:
        cp.parent.mkdir(parents=True, exist_ok=True)
        tmp = cp.with_suffix(f".{time.time_ns()}.tmp")
        tmp.write_text(res.to_json())
        tmp.replace(cp)  # atomic: safe with parallel workers
    return res
