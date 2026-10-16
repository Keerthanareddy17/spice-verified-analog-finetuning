"""Mock pieces for testing the agent harness without a GPU: a model-like backend that misbehaves on purpose,
and a simulator wrapper that injects simulation failures."""
from __future__ import annotations

import hashlib
import json
import re

from .actions import ACTION_IDS
from .circuit.simulator import FailureType, SimResult
from .predict import Backend


class MockBackend(Backend):
    """Behaves like a sloppy model: sometimes invalid JSON, an unknown id, an action missing from the list,
    otherwise it oscillates cc_up / cc_down around a Cc threshold (which creates LOOPs). A re-ask (note in the
    prompt) gets a valid first-listed action, like a model that corrects itself."""
    name = "mock"

    def __init__(self, p_invalid=0.12, p_unknown=0.08, p_unavailable=0.08, cc_threshold_pf=1.2):
        self.p = (p_invalid, p_unknown, p_unavailable)
        self.threshold = cc_threshold_pf

    def generate(self, batch, keys=None):
        return [(self._one(m[1]["content"]), {"completion_tokens": 20}) for m in batch]

    def _one(self, user: str) -> str:
        listed = re.findall(r"^([a-z_]+): ", user.split("Actions:")[1], flags=re.M)
        r = int(hashlib.sha1(user.encode()).hexdigest()[:8], 16) / 0xFFFFFFFF
        reask = "Your previous answer was invalid" in user
        ok = lambda a: json.dumps({"action": a, "reason": "mock"})
        if not reask:
            if r < self.p[0]:
                return "I would reduce the bias current a bit."
            if r < self.p[0] + self.p[1]:
                return ok("cc_sideways")
            if r < sum(self.p):
                missing = [a for a in ACTION_IDS if a not in listed]
                if missing:
                    return ok(missing[0])
        cc = float(re.search(r"Cc=([0-9.eE+-]+)pF", user).group(1))
        want = "cc_up" if cc < self.threshold else "cc_down"
        return ok(want if want in listed else listed[0])


class FaultySim:
    """Wraps a SimPool: every `every`-th simulated design comes back as a non-converged run (no metrics).
    The first `skip_calls` run() calls (the episodes' start states) are passed through untouched."""

    def __init__(self, inner, every: int = 4, skip_calls: int = 1):
        self.inner, self.every, self.count, self.skip_calls = inner, every, 0, skip_calls

    def run(self, designs):
        out = self.inner.run(designs)
        if self.skip_calls > 0:
            self.skip_calls -= 1
            return out
        for i in range(len(out)):
            self.count += 1
            if self.count % self.every == 0:
                out[i] = SimResult(ok=False, failure=FailureType.NONCONVERGENCE, message="injected")
        return out

    def close(self):
        self.inner.close()
