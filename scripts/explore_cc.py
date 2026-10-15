"""Sweep the Miller capacitor Cc: table, Bode overlay, CSV."""
import subprocess
import tempfile
from dataclasses import replace
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from analogft import paths
from analogft.circuit import nominal_design, simulate
from analogft.circuit.netlist import build_netlist
from analogft.circuit.simulator import ngspice_bin, parse_ac

CCS_PF = [0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0, 4.0]


def bode(design):
    with tempfile.TemporaryDirectory() as t:
        p = Path(t)
        (p / "n.cir").write_text(build_netlist(design))
        subprocess.run([ngspice_bin(), "-b", "n.cir"], cwd=p, capture_output=True, timeout=20)
        f, h = parse_ac(p / "ac.dat")
    ph = np.degrees(np.unwrap(np.angle(h)))
    return f, 20 * np.log10(np.abs(h)), ph - 360 * np.round(ph[0] / 360)


def main() -> None:
    rows = []
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(7, 7), sharex=True)
    for cc in CCS_PF:
        d = replace(nominal_design(), cc=cc * 1e-12)
        r = simulate(d)
        m = r.metrics
        rows.append({"cc_pf": cc, "ok": r.ok, "gain_db": m.get("dc_gain_db"), "ugf_mhz": m.get("ugf_hz", np.nan) / 1e6,
                     "pm_deg": m.get("pm_deg"), "power_uw": m["power_w"] * 1e6 if m else None})
        f, mag, ph = bode(d)
        ax1.semilogx(f, mag, label=f"Cc={cc} pF")
        ax2.semilogx(f, ph)
    ax1.axhline(0, color="k", lw=0.6)
    ax1.set_ylabel("gain (dB)"); ax2.set_ylabel("phase (deg)"); ax2.set_xlabel("frequency (Hz)")
    ax1.set_ylim(-40, 90); ax1.legend(fontsize=7); ax1.grid(alpha=.3); ax2.grid(alpha=.3)
    fig.suptitle("Cc sweep around the nominal design")
    fig.tight_layout()
    out = paths.FIGURES_DIR / "cc_sweep_bode.png"
    fig.savefig(out, dpi=130)
    df = pd.DataFrame(rows)
    df.to_csv(paths.RESULTS_DIR / "cc_sweep.csv", index=False)
    print(df.round(3).to_string(index=False))
    print(f"\nsaved {out} and cc_sweep.csv")


if __name__ == "__main__":
    main()
