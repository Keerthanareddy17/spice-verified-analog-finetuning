# SPICE-Verified Fine-Tuning and Reinforcement Learning for Analog Amplifier Design

A small specialist language model looks at a failing two-stage op-amp design and decides what to change next. It is trained and graded only by a circuit simulator (ngspice), then used inside an agent that repairs designs step by step.
**Research question:** can a small, privately runnable model, trained only on simulator feedback, choose better design moves than a large general model?

## Roadmap
| Phase | Scope | Status |
|---|---|---|
| 1 | Simulation environment: netlist, simulator, actions, specs, batch + cache, Drive sync | **Done** |
| 2 | Simulator-labeled dataset: rank all actions per failing start state, split by start design | **Done** |
| 3 | Eval harness, LoRA fine-tune of a small open model, baselines (large model via Groq) | **Done** |
| 4 | Multi-step agent, traces, failure taxonomy and recovery, one round of expert iteration | Not started |

## Phase 1 results
Circuit: Miller-compensated two-stage op-amp (NMOS diff pair, PMOS mirror, PMOS common-source second stage), CL = 2 pF, VDD = 1.8 V. Open-loop AC is measured with a DC-feedback loop-break (see `docs/DECISIONS.md`).

Hand-sized nominal design (simulated): **DC gain 74.2 dB, UGF 27.9 MHz, phase margin 67.8°, power 0.44 mW, all 8 devices saturated.**
Throughput: about 165 simulations/s uncached on a MacBook Air M4 (9 workers).

Cc sweep (more Cc: more phase margin, lower UGF):

![Cc sweep](results/figures/cc_sweep_bode.png)

What each action does to the nominal design (from `results/action_effects.csv`):

| action | Δgain (dB) | ΔPM (deg) | UGF ratio | power ratio |
|---|---|---|---|---|
| cc_up / cc_down | 0.0 / 0.0 | +3.9 / -4.7 | 0.79 / 1.25 | 1.00 / 1.00 |
| ibias_up / ibias_down | -2.3 / +2.3 | +0.2 / -0.1 | 1.13 / 0.88 | 1.30 / 0.77 |
| w_in_up / w_in_down | +1.1 / -1.1 | -2.8 / +2.5 | 1.13 / 0.88 | 1.00 / 1.00 |
| l_in_up / l_in_down | -0.3 / +0.2 | +2.6 / -2.9 | 0.88 / 1.14 | 1.00 / 1.00 |
| l_load_up / l_load_down | +1.1 / -1.3 | -0.6 / +0.4 | 1.00 / 1.00 | 1.00 / 1.00 |
| w_cs_up / w_cs_down | +1.1 / -1.1 | +1.4 / -1.7 | 1.00 / 1.00 | 1.00 / 1.00 |
| out_ratio_up / out_ratio_down | -1.1 / +1.1 | +1.6 / -2.0 | 1.00 / 1.00 | 1.24 / 0.81 |

## Phase 3 results: LoRA fine-tune vs a large model

**Setup.** Qwen2.5-0.5B-Instruct with a LoRA adapter (r=16, all attention and MLP projections), trained 2 epochs (366 steps, 19.3 min on a free T4, fp16) on 2926 simulator-labeled states. The loss is on the reply only. Every method sees the same prompt and is scored by lookup into the simulator's precomputed outcome of every action, so no model output is ever re-simulated. Intervals are 95% bootstrap CIs over states. Full details are in [docs/DECISIONS.md](docs/DECISIONS.md) (D16-D24) and the numbers in [results/phase3_results.md](results/phase3_results.md).

**Main comparison: 150-example eval subset** (a fixed, step-stratified sample of the test split, so the Groq models could be run on exactly the same states):

| method | n | valid | top-1 tie-aware (95% CI) | top-1 exact | top-3 | improvement rate (95% CI) | mean regret (95% CI) |
|---|---|---|---|---|---|---|---|
| random | 150 | 1.000 | 0.107 [0.097, 0.118] | 0.073 | 0.230 | 0.401 [0.381, 0.419] | 0.243 [0.204, 0.282] |
| majority action | 150 | 1.000 | 0.313 [0.247, 0.387] | 0.293 | 0.393 | 0.480 [0.400, 0.553] | 0.097 [0.080, 0.115] |
| textbook rules | 150 | 1.000 | 0.400 [0.320, 0.480] | 0.287 | 0.733 | 0.880 [0.827, 0.927] | 0.073 [0.050, 0.102] |
| Groq openai/gpt-oss-120b | 150 | 0.987 | 0.513 [0.433, 0.593] | 0.447 | 0.627 | 0.827 [0.767, 0.887] | 0.103 [0.072, 0.141] |
| Groq qwen/qwen3.8-27b | 150 | 1.000 | 0.333 [0.260, 0.407] | 0.253 | 0.493 | 0.787 [0.720, 0.847] | 0.179 [0.128, 0.233] |
| Qwen2.5-0.5B base model (untrained) | 150 | 1.000 | 0.187 [0.127, 0.253] | 0.167 | 0.213 | 0.273 [0.200, 0.347] | 0.211 [0.168, 0.259] |
| Qwen2.5-0.5B fine-tuned | 150 | 1.000 | 0.693 [0.620, 0.760] | 0.627 | 0.740 | 0.873 [0.820, 0.920] | 0.056 [0.033, 0.082] |

**Full test split** (375 examples; the Groq models were only run on the subset):

| method | n | valid | top-1 tie-aware (95% CI) | top-1 exact | top-3 | improvement rate (95% CI) | mean regret (95% CI) |
|---|---|---|---|---|---|---|---|
| random | 375 | 1.000 | 0.117 [0.109, 0.125] | 0.073 | 0.232 | 0.406 [0.395, 0.417] | 0.232 [0.208, 0.258] |
| majority action | 375 | 1.000 | 0.325 [0.280, 0.373] | 0.304 | 0.389 | 0.464 [0.416, 0.515] | 0.092 [0.081, 0.103] |
| textbook rules | 375 | 1.000 | 0.440 [0.392, 0.488] | 0.261 | 0.768 | 0.904 [0.875, 0.933] | 0.070 [0.055, 0.088] |
| Qwen2.5-0.5B base model (untrained) | 375 | 1.000 | 0.173 [0.133, 0.211] | 0.157 | 0.213 | 0.261 [0.216, 0.307] | 0.203 [0.175, 0.235] |
| Qwen2.5-0.5B fine-tuned | 375 | 1.000 | 0.717 [0.669, 0.763] | 0.661 | 0.803 | 0.893 [0.861, 0.923] | 0.042 [0.028, 0.059] |

Training curve (loss on reply tokens; the reply is a JSON action plus a short generated reason, so the loss mixes action choice with reason text):

![Loss curve](results/figures/phase3_loss_curve.png)

**Where each method wins or loses** (subset; top-1 / improvement rate / regret). By step, the fine-tuned model is strongest on first-look designs (step 0: 0.75 / 0.93 / 0.028) and weakest at step 3 (0.36 / 0.64 / 0.187, but only n=11). By largest shortfall, it is clearly ahead on UGF (0.71 top-1 vs 0.23 for textbook rules) and gain (0.78 vs 0.22), and behind textbook rules on phase margin (0.56 vs 0.75). The full breakdown is in `results/phase3_results.md`.

**Interpretation.** On this task a 0.5B model fine-tuned only on simulator labels picks the best move far more often than the untrained model (0.693 vs 0.187 tie-aware top-1) and more often than gpt-oss-120b (0.513) and the textbook rules (0.400); its mean regret (0.056) is the lowest of all methods. The gain is in choosing the *best* move, not in choosing a *helpful* one: its improvement rate (0.873) is statistically tied with textbook rules (0.880, CIs overlap almost entirely), which already find a move that helps about 88% of the time. The margin over gpt-oss-120b is clear but not huge at n=150 (top-1 CIs [0.620, 0.760] vs [0.433, 0.593] just separate; the regret CIs still overlap), and the full-test result (0.717, n=375) points the same way. Caveats: the evaluation is in-distribution (the same circuit and spec generator, with unseen designs, split by target), the task is single-step (Phase 4 tests the multi-step agent), and the circuit uses Level-1 device models, so this shows the approach works against a simulator, not that these numbers hold on silicon-accurate models or other topologies.

## Limitations
Devices are SPICE Level-1 models (lambda ∝ 1/L), not a BSIM/PTM card (the PTM site was unreachable when this was built). They show the right trends but ignore short-channel effects, so absolute numbers are not silicon-accurate.

## Run Phase 1
Requires Python ≥ 3.10 and ngspice (`brew install ngspice`).
```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
pytest
python scripts/simulate_one.py      # nominal design report
python scripts/explore_cc.py        # Cc sweep: table, figure, CSV
python scripts/explore_actions.py   # what each of the 14 actions does
# data/phase2 is committed to git; Colab results come back as a zip: python scripts/import_results_zip.py <zip>
```
Design decisions are logged in [docs/DECISIONS.md](docs/DECISIONS.md). `notebooks/00_colab_bootstrap.ipynb` checks Colab's ngspice against the Mac's.
