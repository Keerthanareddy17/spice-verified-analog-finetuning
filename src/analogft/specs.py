"""Specs, pass/fail checking and the spec distance (ranking signal / RL reward)."""
from __future__ import annotations

import math
from dataclasses import dataclass

from .circuit.simulator import SimResult

SIM_FAIL_PENALTY = 10.0
SAT_PENALTY = 1.0


@dataclass(frozen=True)
class Spec:
    gain_db_min: float
    ugf_hz_min: float
    pm_deg_min: float
    power_w_max: float


def check(result: SimResult, spec: Spec) -> dict[str, bool]:
    """Per-metric pass/fail plus 'saturated' and 'met' (everything passes)."""
    m = result.metrics
    out = {
        "gain": m.get("dc_gain_db", -math.inf) >= spec.gain_db_min,
        "ugf": m.get("ugf_hz", 0.0) >= spec.ugf_hz_min,
        "pm": m.get("pm_deg", -math.inf) >= spec.pm_deg_min,
        "power": m.get("power_w", math.inf) <= spec.power_w_max,
        "saturated": bool(result.regions) and all(r["saturated"] for r in result.regions.values()),
    }
    out["met"] = result.ok and all(out.values())
    return out


def is_met(result: SimResult, spec: Spec) -> bool:
    return check(result, spec)["met"]


def spec_distance(result: SimResult, spec: Spec) -> float:
    """0 iff the spec is met; otherwise a sum of normalized shortfalls.

    gain: dB/10, ugf and power: decades (log10 ratio), pm: deg/15,
    +1 per device out of saturation, 10 if the simulation produced no numbers.
    A run that produced numbers but missed a measurement (e.g. no 0 dB
    crossing) has no complete metrics, so it is treated as a failed simulation.
    """
    m = result.metrics
    if not all(k in m for k in ("dc_gain_db", "ugf_hz", "pm_deg", "power_w")):
        return SIM_FAIL_PENALTY
    d = max(0.0, spec.gain_db_min - m["dc_gain_db"]) / 10.0
    d += max(0.0, math.log10(spec.ugf_hz_min / m["ugf_hz"]))
    d += max(0.0, spec.pm_deg_min - m["pm_deg"]) / 15.0
    d += max(0.0, math.log10(m["power_w"] / spec.power_w_max))
    d += SAT_PENALTY * sum(not r["saturated"] for r in result.regions.values())
    if d == 0.0 and not result.ok:  # ran, all metrics pass, but invalid for another reason
        d = 1e-6
    return d
