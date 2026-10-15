"""Simulate the nominal design (or one from a JSON file) and print a clean report.

Usage: python scripts/simulate_one.py [design.json]
"""
import json
import sys

from analogft.circuit import nominal_design, simulate
from analogft.circuit.design import Design
from analogft.specs import Spec, check, spec_distance

SAMPLE_SPEC = Spec(gain_db_min=60, ugf_hz_min=10e6, pm_deg_min=50, power_w_max=1e-3)


def main() -> None:
    design = Design.from_dict(json.load(open(sys.argv[1]))) if len(sys.argv) > 1 else nominal_design()
    r = simulate(design)
    print("Design:", {k: f"{v:.4g}" for k, v in design.to_dict().items()})
    print(f"\nok={r.ok} failure={r.failure.value if r.failure else None} {r.message}"
          f"  ({r.runtime_s*1e3:.0f} ms, ngspice-{r.ngspice_version})")
    m = r.metrics
    if m:
        print("\nMetrics")
        for k, unit in (("dc_gain_db", "dB"), ("ugf_hz", "Hz"), ("pm_deg", "deg"),
                        ("power_w", "W"), ("vout_dc", "V")):
            if k in m:
                print(f"  {k:<11} {m[k]:>12.4g} {unit}")
    if r.regions:
        print("\nDevices        Vgs     |Vth|     Vds   |Vdsat|   region")
        for name, d in r.regions.items():
            print(f"  {name}   {abs(d['vgs']):8.3f} {abs(d['vth']):8.3f} {abs(d['vds']):8.3f} "
                  f"{abs(d['vdsat']):8.3f}   {'saturated' if d['saturated'] else 'NOT saturated'}")
    print(f"\nSample spec: {SAMPLE_SPEC}")
    c = check(r, SAMPLE_SPEC)
    print("  " + "  ".join(f"{k}={'PASS' if v else 'FAIL'}" for k, v in c.items()))
    print(f"  spec_distance = {spec_distance(r, SAMPLE_SPEC):.4f}")


if __name__ == "__main__":
    main()
