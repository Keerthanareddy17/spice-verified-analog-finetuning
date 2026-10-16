"""Policies for the agent: each maps a list of states to one Prediction (action or error) per state.

All of them see the same state dict ({spec, design, metrics, regions, available_actions}). The LLM policies build
exactly the prompt the model was trained on (`predict.build_messages` -> `prompting.format_prompt`); the agent's
memory (best design, visited states, blocked actions) stays in the harness and only shows up as a shorter action list.
"""
from __future__ import annotations

import random

from .baselines import textbook_pick
from .predict import Backend, Prediction, Predictor, build_messages, messages_key


class Policy:
    name = "policy"

    def choose(self, states: list[dict], notes: list[str | None] | None = None) -> list[Prediction]:
        raise NotImplementedError


class RulesPolicy(Policy):
    """Textbook rules (baselines.textbook_pick): fix the largest shortfall with its fixed move."""
    name = "textbook_rules"

    def choose(self, states, notes=None):
        out = []
        for s in states:
            a = textbook_pick(s)
            out.append(Prediction("", a, None if a else "no_action", {}))
        return out


class RandomPolicy(Policy):
    """Uniform over the available actions (seeded)."""
    name = "random"

    def __init__(self, seed: int = 0):
        self.rng = random.Random(seed)

    def choose(self, states, notes=None):
        return [Prediction("", self.rng.choice(s["available_actions"]), None, {}) if s["available_actions"]
                else Prediction("", None, "no_action", {}) for s in states]


class LLMPolicy(Policy):
    """Any `predict.Backend` (Groq, HF base/LoRA, or a mock): prompt -> raw text -> parse_response."""

    def __init__(self, backend: Backend, name: str | None = None):
        self.predictor = Predictor(backend)
        self.name = name or backend.name

    def choose(self, states, notes=None):
        notes = notes or [None] * len(states)
        keys = [messages_key(build_messages(s, n)) for s, n in zip(states, notes)]
        return self.predictor.predict_batch(states, keys, notes)
