"""Build the ngspice netlist text for a Design.

Topology (see CLAUDE.md): NMOS diff pair M1/M2, PMOS mirror M3/M4, tail M5,
PMOS CS stage M6, sink M7, diode-connected reference M8, Miller cap Cc, load CL.
M2's gate is the NON-inverting input (stage 1 + stage 2 give out ~ +M2).
"""
from __future__ import annotations

from .design import Design
from .models import CL, TEMP_NOM, VCM_FRAC, VDD, W_BIAS, model_card

DEVICES = ["m1", "m2", "m3", "m4", "m5", "m6", "m7", "m8"]
JUNCTION = 0.5e-6  # m, drain/source diffusion length for area/perimeter

# Loop-break values: huge L and C so the DC loop is closed and the AC loop open.
L_BREAK = 1e9
C_BREAK = 1e9


def _mos(name: str, d: str, g: str, s: str, b: str, model: str, w: float, l: float) -> str:
    ad = w * JUNCTION
    pd = 2 * (w + JUNCTION)
    return (f"{name} {d} {g} {s} {b} {model} W={w:.6g} L={l:.6g} "
            f"AD={ad:.6g} AS={ad:.6g} PD={pd:.6g} PS={pd:.6g}")


def build_netlist(design: Design, temp_c: float = TEMP_NOM, vdd_scale: float = 1.0) -> str:
    """Return the full netlist (including the .control block) as text."""
    d = design
    vdd = VDD * vdd_scale
    vcm = VCM_FRAC * vdd
    w5 = d.tail_ratio * W_BIAS
    w7 = d.out_ratio * W_BIAS
    lines = [
        "* two-stage Miller op-amp, open-loop AC with DC feedback",
        f".options temp={temp_c:g} gmin=1e-12 reltol=1e-4",
        f"Vdd vdd 0 {vdd:.6g}",
        f"Ibias vdd nb {d.ibias:.6g}",
        f"Vcm cm 0 {vcm:.6g}",
        "Vin inp cm DC 0 AC 1",
        # DC loop closed through L; AC inverting input grounded through C.
        f"Lfb out inn {L_BREAK:g}",
        f"Cfb inn 0 {C_BREAK:g}",
        # Bias branch and mirrors
        _mos("m8", "nb", "nb", "0", "0", "mn_bias", W_BIAS, d.l_bias),
        _mos("m5", "tail", "nb", "0", "0", "mn_bias", w5, d.l_bias),
        _mos("m7", "out", "nb", "0", "0", "mn_bias", w7, d.l_bias),
        # Stage 1
        _mos("m1", "n1", "inn", "tail", "0", "mn_in", d.w_in, d.l_in),
        _mos("m2", "n2", "inp", "tail", "0", "mn_in", d.w_in, d.l_in),
        _mos("m3", "n1", "n1", "vdd", "vdd", "mp_load", d.w_load, d.l_load),
        _mos("m4", "n2", "n1", "vdd", "vdd", "mp_load", d.w_load, d.l_load),
        # Stage 2
        _mos("m6", "out", "n2", "vdd", "vdd", "mp_cs", d.w_cs, d.l_cs),
        f"Cc n2 out {d.cc:.6g}",
        f"CL out 0 {CL:.6g}",
        model_card("mn_bias", "n", d.l_bias),
        model_card("mn_in", "n", d.l_in),
        model_card("mp_load", "p", d.l_load),
        model_card("mp_cs", "p", d.l_cs),
        ".control",
        "set noaskquit",
        "op",
        "print v(out) v(n1) v(n2) v(tail)",
        "print @vdd[i]",
    ]
    for m in DEVICES:
        lines.append(f"print @{m}[vgs] @{m}[vds] @{m}[von] @{m}[vdsat] @{m}[id]")
    lines += [
        "ac dec 30 1 10G",
        "wrdata ac.dat v(out)",
        "quit",
        ".endc",
        ".end",
    ]
    return "\n".join(lines) + "\n"
