"""Per-spec normalized shortfalls, the pieces that spec_distance adds up.

Works on plain dicts (as stored in the dataset), so prompts, response reasons
and the rule-based baseline all agree with `specs.spec_distance`.
"""
from __future__ import annotations

import math

from .specs import SAT_PENALTY, SIM_FAIL_PENALTY

METRIC_KEYS = ("dc_gain_db", "ugf_hz", "pm_deg", "power_w")


def has_all_metrics(metrics: dict) -> bool:
    return all(metrics.get(k) is not None for k in METRIC_KEYS)


def shortfall_terms(spec: dict, metrics: dict, n_unsat: int) -> dict[str, float]:
    """Return {gain, ugf, pm, power, sat: >= 0}; their sum is the spec distance.

    If any metric is missing the simulation counts as failed: {"nosim": 10.0}.
    """
    if not has_all_metrics(metrics):
        return {"nosim": SIM_FAIL_PENALTY}
    return {
        "gain": max(0.0, spec["gain_db_min"] - metrics["dc_gain_db"]) / 10.0,
        "ugf": max(0.0, math.log10(spec["ugf_hz_min"] / metrics["ugf_hz"])),
        "pm": max(0.0, spec["pm_deg_min"] - metrics["pm_deg"]) / 15.0,
        "power": max(0.0, math.log10(metrics["power_w"] / spec["power_w_max"])),
        "sat": SAT_PENALTY * n_unsat,
    }


def n_unsaturated(regions: dict[str, bool]) -> int:
    return sum(not s for s in regions.values())


def unsaturated(regions: dict[str, bool]) -> list[str]:
    return [d for d, s in regions.items() if not s]


def slack_terms(spec: dict, metrics: dict) -> dict[str, float]:
    """Margin beyond each spec in the same units as `shortfall_terms` (positive = passes with room).

    gain: dB/10, ugf and power: decades, pm: deg/15. Saturation is not included (it is
    pass/fail and already part of the distance). Missing metrics give -inf for every term.
    """
    if not has_all_metrics(metrics):
        return {k: -math.inf for k in ("gain", "ugf", "pm", "power")}
    return {
        "gain": (metrics["dc_gain_db"] - spec["gain_db_min"]) / 10.0,
        "ugf": math.log10(metrics["ugf_hz"] / spec["ugf_hz_min"]),
        "pm": (metrics["pm_deg"] - spec["pm_deg_min"]) / 15.0,
        "power": math.log10(spec["power_w_max"] / metrics["power_w"]),
    }


def margin(spec: dict, metrics: dict) -> float:
    """Smallest normalized slack across the four specs: how robustly a design passes."""
    return min(slack_terms(spec, metrics).values())
