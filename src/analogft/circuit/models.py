"""Device models: SPICE Level-1 with channel-length modulation lambda ~ 1/L.

BSIM PTM cards were the preferred choice but the ASU PTM site was unreachable
(see docs/DECISIONS.md), so these are textbook 180 nm-class Level-1 parameters.
"""
from __future__ import annotations

VDD = 1.8          # V, 180 nm-class supply
L_MIN = 0.18e-6    # m
CL = 2e-12         # F, fixed load
VCM_FRAC = 0.5     # input common-mode = 0.5 * VDD
W_BIAS = 10e-6     # m, width of diode-connected reference M8
TEMP_NOM = 27.0

# lambda = LAMBDA_K / L[um]  (1/V). Longer L -> smaller lambda -> more gain.
LAMBDA_K = {"n": 0.04, "p": 0.05}

_COMMON = ("TOX=4.1n LD=0 CGSO=3.0e-10 CGDO=3.0e-10 CGBO=0 "
           "CJ=1e-3 MJ=0.5 PB=0.8 CJSW=2e-10 MJSW=0.33 PHI=0.85 GAMMA=0.4")
_BASE = {
    "n": f"NMOS LEVEL=1 VTO=0.45 KP=170u {_COMMON}",
    "p": f"PMOS LEVEL=1 VTO=-0.45 KP=60u {_COMMON}",
}


def model_card(name: str, polarity: str, l_m: float) -> str:
    """One .model line for a device of channel length l_m (metres)."""
    lam = LAMBDA_K[polarity] / (l_m * 1e6)
    return f".model {name} {_BASE[polarity]} LAMBDA={lam:.6g}"
