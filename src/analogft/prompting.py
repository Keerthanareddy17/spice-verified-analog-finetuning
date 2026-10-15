"""Prompt and response format shared by dataset building, evaluation (Phase 3) and the agent (Phase 4).

A "state" is a plain dict with: spec, design, metrics, regions (device -> saturated bool)
and available_actions (list of action ids).
"""
from __future__ import annotations

import json
import math

from .actions import ACTION_BY_ID, ACTION_IDS
from .shortfall import has_all_metrics, n_unsaturated, shortfall_terms, unsaturated

SYSTEM_PROMPT = (
    "You are an analog design assistant. A two-stage Miller-compensated op-amp does not yet "
    "meet its spec. Pick exactly one action from the list you are given to move the design "
    "toward the spec. Answer with one line of JSON and nothing else: "
    '{"action": "<action id>", "reason": "<short reason>"}'
)

_ERR_NO_JSON = "no_json"
_ERR_UNKNOWN = "unknown_action"
_ERR_UNAVAILABLE = "unavailable_action"


def _g(x: float, digits: int = 3) -> str:
    return f"{x:.{digits}g}"


def _knob_line(d: dict) -> str:
    um, pf = 1e6, 1e12
    return (f"Cc={d['cc'] * pf:.3g}pF Ibias={d['ibias'] * um:.3g}uA W1={d['w_in'] * um:.3g}um "
            f"L1={d['l_in'] * um:.3g}um L3={d['l_load'] * um:.3g}um W6={d['w_cs'] * um:.3g}um "
            f"ratio={d['out_ratio']:.3g} | fixed: W3={d['w_load'] * um:.3g}um "
            f"L6={d['l_cs'] * um:.3g}um Lbias={d['l_bias'] * um:.3g}um tail_ratio={d['tail_ratio']:.3g}")


def _fail_text(spec: dict, m: dict) -> str:
    parts = []
    if m["dc_gain_db"] < spec["gain_db_min"]:
        parts.append(f"gain (short {spec['gain_db_min'] - m['dc_gain_db']:.1f} dB)")
    if m["ugf_hz"] < spec["ugf_hz_min"]:
        parts.append(f"UGF (short {100 * (1 - m['ugf_hz'] / spec['ugf_hz_min']):.0f}%)")
    if m["pm_deg"] < spec["pm_deg_min"]:
        parts.append(f"PM (short {spec['pm_deg_min'] - m['pm_deg']:.1f} deg)")
    if m["power_w"] > spec["power_w_max"]:
        parts.append(f"power (over by {100 * (m['power_w'] / spec['power_w_max'] - 1):.0f}%)")
    return ", ".join(parts) or "none"


def format_prompt(state: dict) -> str:
    """User message: spec, current metrics, failing specs, unsaturated devices, knobs, actions."""
    s, m = state["spec"], state["metrics"]
    lines = [
        f"Spec: gain >= {s['gain_db_min']:.1f} dB, UGF >= {s['ugf_hz_min'] / 1e6:.2f} MHz, "
        f"PM >= {s['pm_deg_min']:.1f} deg, power <= {s['power_w_max'] * 1e3:.3f} mW"]
    if has_all_metrics(m):
        lines.append(f"Now: gain {m['dc_gain_db']:.1f} dB, UGF {m['ugf_hz'] / 1e6:.2f} MHz, "
                     f"PM {m['pm_deg']:.1f} deg, power {m['power_w'] * 1e3:.3f} mW")
        lines.append(f"Failing: {_fail_text(s, m)}")
    else:
        lines.append("Now: metrics unavailable (simulation incomplete)")
    unsat = [d.upper() for d in unsaturated(state["regions"])]
    lines.append(f"Unsaturated devices: {', '.join(unsat) if unsat else 'none'}")
    lines.append(f"Knobs: {_knob_line(state['design'])}")
    lines.append("Actions:")
    lines += [f"{a}: {ACTION_BY_ID[a].description}" for a in state["available_actions"]]
    return "\n".join(lines)


# ----- response ------------------------------------------------------------------------

_NAMES = {"gain": "gain", "ugf": "UGF", "pm": "PM", "power": "power"}
_KEYS = {"gain": "dc_gain_db", "ugf": "ugf_hz", "pm": "pm_deg", "power": "power_w"}


def _shortfall_phrase(term: str, spec: dict, before: dict) -> str:
    m = before["metrics"]
    if term == "sat":
        return f"{', '.join(d.upper() for d in before.get('unsat') or ['a device'])} out of saturation"
    if term == "gain":
        return f"gain {m['dc_gain_db']:.1f} < {spec['gain_db_min']:.1f} dB"
    if term == "ugf":
        return f"UGF {m['ugf_hz'] / 1e6:.1f} < {spec['ugf_hz_min'] / 1e6:.1f} MHz"
    if term == "pm":
        return f"PM {m['pm_deg']:.1f} < {spec['pm_deg_min']:.0f} deg"
    return f"power {m['power_w'] * 1e3:.2f} > {spec['power_w_max'] * 1e3:.2f} mW"


def _change(term: str, b: dict, a: dict) -> tuple[str, float]:
    """(text, normalized magnitude) of the change of one metric."""
    name, k = _NAMES[term], _KEYS[term]
    if term == "gain":
        d = a[k] - b[k]
        return f"{name} {d:+.1f} dB", abs(d) / 10.0
    if term == "pm":
        d = a[k] - b[k]
        return f"{name} {d:+.1f} deg", abs(d) / 15.0
    pct = 100 * (a[k] / b[k] - 1)
    return f"{name} {pct:+.0f}%" if abs(pct) >= 10 else f"{name} {pct:+.1f}%", abs(math.log10(a[k] / b[k]))


def format_response(action_id: str, outcome_before: dict, outcome_after: dict, spec: dict) -> str:
    """One-line JSON {"action", "reason"}; the reason is built from simulated data.

    An outcome is {"metrics": {...}, "n_unsat": int, "unsat": [device, ...] (before only)}.
    The reason names the largest failing spec and the simulated effect of the action.
    """
    b, a = outcome_before, outcome_after
    terms = shortfall_terms(spec, b["metrics"], b["n_unsat"])
    big = max(terms, key=terms.get)
    if big == "nosim":
        reason = f"{action_id}: no complete metrics to reason from"
        return json.dumps({"action": action_id, "reason": reason})
    head = f"{_shortfall_phrase(big, spec, b)} is the largest shortfall"
    if not has_all_metrics(a["metrics"]):
        effect = "simulation of the result fails"
    else:
        parts: list[str] = []
        if big == "sat":
            parts.append(f"unsaturated devices {b['n_unsat']}->{a['n_unsat']}")
        else:
            parts.append(_change(big, b["metrics"], a["metrics"])[0])
        others = sorted(((t, *_change(t, b["metrics"], a["metrics"])) for t in _NAMES if t != big),
                        key=lambda x: -x[2])
        if others and others[0][2] >= 0.03:  # side effect worth mentioning (> ~0.3 dB-equivalent)
            parts.append(others[0][1])
        effect = ", ".join(parts)
    return json.dumps({"action": action_id, "reason": f"{head}; {action_id}: {effect}"})


def parse_response(text: str, available_actions: list[str]) -> tuple[str | None, str | None]:
    """Extract the chosen action id from model output.

    Tolerates code fences and extra text around a JSON object. Returns (action, None)
    on success or (None, error) with error in {"no_json", "unknown_action",
    "unavailable_action"}.
    """
    if not isinstance(text, str):
        return None, _ERR_NO_JSON
    dec = json.JSONDecoder()
    action = None
    for i, ch in enumerate(text):
        if ch != "{":
            continue
        try:
            obj, _ = dec.raw_decode(text[i:])
        except ValueError:
            continue
        if isinstance(obj, dict) and isinstance(obj.get("action"), str):
            action = obj["action"].strip()
            break
    if action is None:
        return None, _ERR_NO_JSON
    if action not in ACTION_IDS:
        return None, _ERR_UNKNOWN
    if action not in available_actions:
        return None, _ERR_UNAVAILABLE
    return action, None


def estimate_tokens(text: str) -> int:
    """Rough token count: 4 characters per token."""
    return math.ceil(len(text) / 4)
