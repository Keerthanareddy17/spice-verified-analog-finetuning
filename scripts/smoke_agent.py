"""Agent-harness smoke test on ~10 real test episodes: proves every failure class is detected and every recovery fires.

Usage: python scripts/smoke_agent.py   (needs ngspice, no GPU)
"""
from analogft.agent import SimPool
from analogft.agent_eval import load_episodes, run_and_save
from analogft.mock import FaultySim, MockBackend
from analogft.policies import LLMPolicy, RandomPolicy, RulesPolicy
from analogft.tracing import FAILURE_CLASSES, RECOVERIES


def main() -> None:
    eps = load_episodes("test")[:10]
    runs = [("rules", RulesPolicy(), None), ("random", RandomPolicy(0), None),
            ("mock-hf", LLMPolicy(MockBackend()), None), ("mock-hf+faulty-sim", LLMPolicy(MockBackend()), 4)]
    totals = {True: {}, False: {}}
    with SimPool() as pool:
        for name, pol, every in runs:
            for rec in (False, True):
                sim = FaultySim(pool, every) if every else pool
                m = run_and_save(__import__("tempfile").mkdtemp(), f"{name}-{rec}", pol, eps, recovery=rec, sim=sim,
                                 log=lambda *_: None)
                print(f"{name:20s} recovery={rec!s:5s} solved={m['outcomes']['solved']}/{m['n_episodes']} "
                      f"invalid/step={m['invalid_output_rate']:.2f}")
                print("   failures :", {k: v for k, v in m["failure_classes"].items() if v})
                print("   recovery :", {k: v for k, v in m["recoveries"].items() if v})
                for k, v in m["failure_classes"].items():
                    totals[rec][k] = totals[rec].get(k, 0) + v
                for k, v in m["recoveries"].items():
                    totals[rec][k] = totals[rec].get(k, 0) + v
    print("\nTOTAL over all smoke runs, recovery OFF:", {k: totals[False].get(k, 0) for k in FAILURE_CLASSES})
    print("TOTAL over all smoke runs, recovery ON :", {k: totals[True].get(k, 0) for k in FAILURE_CLASSES + RECOVERIES})
    # UNAVAILABLE_ACTION needs a shortened action list (a blocked or clipped action), which mostly exists with recovery on
    assert all(totals[False].get(k, 0) + totals[True].get(k, 0) > 0 for k in FAILURE_CLASSES), "a failure class was never detected"
    assert all(totals[True][k] > 0 for k in RECOVERIES), "a recovery path never fired"
    assert not any(totals[False].get(k, 0) for k in RECOVERIES), "recoveries fired with recovery off"
    print("\nSMOKE OK: every failure class detected, every recovery path fired, none fired with recovery off.")


if __name__ == "__main__":
    main()
