"""Write results/reference_nominal.json: the Mac's answer for the nominal design.

Colab's bootstrap notebook re-simulates the same design and must agree.
"""
import json

from analogft import paths
from analogft.circuit import nominal_design, simulate


def main() -> None:
    d = nominal_design()
    r = simulate(d, use_cache=False)
    out = {"design": d.to_dict(), "ngspice_version": r.ngspice_version, "ok": r.ok,
           "metrics": r.metrics, "all_saturated": all(x["saturated"] for x in r.regions.values())}
    (paths.RESULTS_DIR / "reference_nominal.json").write_text(json.dumps(out, indent=2) + "\n")
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
