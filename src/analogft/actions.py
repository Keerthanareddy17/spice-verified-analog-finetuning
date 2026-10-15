"""The action set: multiply or divide one knob by 1.3.

Ids are the model's output vocabulary in Phase 3, so they must stay stable.
Descriptions are neutral and factual on purpose: they never say what an action
does to the metrics. Learning that is the model's job.
"""
from __future__ import annotations

from dataclasses import dataclass, replace

from .circuit.design import Design

STEP = 1.3

_KNOB_LABELS = {
    "cc": "compensation capacitor Cc",
    "ibias": "bias current Ibias",
    "w_in": "input pair width W1",
    "l_in": "input pair length L1",
    "l_load": "mirror load length L3",
    "w_cs": "second-stage width W6",
    "out_ratio": "second-stage current ratio",
}


@dataclass(frozen=True)
class Action:
    id: str
    knob: str
    factor: float
    description: str


ACTIONS: list[Action] = [
    Action(f"{knob}_{name}", knob, factor,
           f"{verb} {label} by 30%")
    for knob, label in _KNOB_LABELS.items()
    for name, factor, verb in (("up", STEP, "increase"), ("down", 1 / STEP, "decrease"))
]
ACTION_BY_ID: dict[str, Action] = {a.id: a for a in ACTIONS}
ACTION_IDS: list[str] = [a.id for a in ACTIONS]


def apply(design: Design, action: Action | str) -> Design:
    """Return a new clipped design with the action applied."""
    a = ACTION_BY_ID[action] if isinstance(action, str) else action
    return replace(design, **{a.knob: getattr(design, a.knob) * a.factor}).clip()


def available_actions(design: Design) -> list[Action]:
    """Actions that actually change the design (clipping can turn one into a no-op)."""
    return [a for a in ACTIONS if apply(design, a) != design]
