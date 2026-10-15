"""Apply each of the 14 actions once to the nominal design and print the metric changes."""
import pandas as pd

from analogft import paths
from analogft.actions import ACTIONS, apply
from analogft.circuit import nominal_design, simulate

METRICS = ["dc_gain_db", "ugf_hz", "pm_deg", "power_w"]


def main() -> None:
    base = nominal_design()
    r0 = simulate(base)
    rows = []
    for a in ACTIONS:
        r = simulate(apply(base, a))
        row = {"action": a.id, "ok": r.ok, "failure": r.failure.value if r.failure else ""}
        for k in METRICS:
            row[f"d_{k}"] = r.metrics[k] - r0.metrics[k] if k in r.metrics else float("nan")
        row["ugf_ratio"] = r.metrics["ugf_hz"] / r0.metrics["ugf_hz"] if "ugf_hz" in r.metrics else float("nan")
        row["power_ratio"] = r.metrics["power_w"] / r0.metrics["power_w"] if "power_w" in r.metrics else float("nan")
        row["n_unsat"] = sum(not v["saturated"] for v in r.regions.values())
        rows.append(row)
    df = pd.DataFrame(rows)
    df.to_csv(paths.RESULTS_DIR / "action_effects.csv", index=False)
    print("Nominal:", {k: round(v, 4) for k, v in r0.metrics.items()})
    print(df.drop(columns=["d_ugf_hz", "d_power_w"]).round(3).to_string(index=False))
    print("\nsaved results/action_effects.csv")


if __name__ == "__main__":
    main()
