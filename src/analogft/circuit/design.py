"""Design knobs, bounds and the nominal hand-sized design."""
from __future__ import annotations

from dataclasses import asdict, dataclass, fields, replace

U = 1e-6
P = 1e-12

# name -> (min, max). Widths/lengths in metres, ibias in A, cc in F, ratios unitless.
KNOBS: dict[str, tuple[float, float]] = {
    "w_in": (2 * U, 200 * U),
    "l_in": (0.18 * U, 2 * U),
    "w_load": (1 * U, 100 * U),
    "l_load": (0.18 * U, 2 * U),
    "w_cs": (2 * U, 400 * U),
    "l_cs": (0.18 * U, 2 * U),
    "l_bias": (0.18 * U, 2 * U),
    "ibias": (5 * U, 100 * U),
    "tail_ratio": (0.5, 4.0),
    "out_ratio": (1.0, 20.0),
    "cc": (0.1 * P, 10 * P),
}


@dataclass(frozen=True)
class Design:
    """Sizing knobs of the two-stage op-amp. M1=M2 and M3=M4 by construction."""
    w_in: float
    l_in: float
    w_load: float
    l_load: float
    w_cs: float
    l_cs: float
    l_bias: float
    ibias: float
    tail_ratio: float
    out_ratio: float
    cc: float

    def clip(self) -> "Design":
        """Return a copy with every knob clamped into its bounds."""
        return replace(self, **{k: min(max(getattr(self, k), lo), hi)
                                for k, (lo, hi) in KNOBS.items()})

    def to_dict(self) -> dict[str, float]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, float]) -> "Design":
        return cls(**{f.name: float(d[f.name]) for f in fields(cls)})


def nominal_design() -> Design:
    """Hand-sized starting point (procedure in docs/DECISIONS.md)."""
    return Design(w_in=3.7 * U, l_in=0.5 * U, w_load=5.8 * U, l_load=0.5 * U,
                  w_cs=79 * U, l_cs=0.5 * U, l_bias=0.5 * U, ibias=20 * U,
                  tail_ratio=1.4, out_ratio=9.5, cc=1.0 * P).clip()
