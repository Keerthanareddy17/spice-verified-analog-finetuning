# Project walkthrough (for the code walkthrough interview)

One-line pitch: **a 0.5B-parameter model, fine-tuned only on ngspice feedback, is used as an agent that repairs failing op-amp designs; a harness with failure detection and recovery turns it from 78% to 90% of test episodes solved, and one round of expert iteration takes it to 94%, beating textbook rules (76%) with fewer simulations.**

---

## 1. Module map: `src/analogft/`

**Circuit and simulation (Phase 1)**
- `circuit/design.py`: the 11 sizing knobs (`Design`, frozen dataclass), their bounds, `clip()`, the hand-sized nominal design (74.2 dB, 27.9 MHz, PM 67.8 deg, 0.44 mW).
- `circuit/models.py`, `circuit/netlist.py`: Level-1 MOS model cards and the SPICE netlist template for the two-stage Miller op-amp (diff pair, mirror load, tail, second stage, bias mirror, Cc, CL).
- `circuit/simulator.py`: `simulate(design) -> SimResult` runs ngspice (DC + AC with a loop-break), extracts gain/UGF/PM/power and a per-device saturation check, returns a typed failure (`NONCONVERGENCE`, `MEASUREMENT_MISSING`, ...) instead of raising, and caches by netlist hash.
- `circuit/batch.py`: `simulate_batch` with a spawn process pool (about 165 sims/s on the M4).
- `actions.py`: the 14 actions (x1.3 or /1.3 on 7 knobs); ids are the model's output vocabulary; descriptions are neutral and never say what an action does.
- `specs.py`: `Spec`, pass/fail check, and `spec_distance` (gain dB/10, UGF and power in decades, PM deg/15, +1 per unsaturated device, 10 for no metrics): the ranking signal and the reward.
- `shortfall.py`: the per-spec pieces of the distance (and the slack/margin used for tie-breaking).

**Dataset and prompts (Phase 2)**
- `dataset.py`: builds the dataset: achievable targets, spec with slack, failing start states on the action lattice, simulates ALL actions per state, ranks them, follows the greedy path for later steps, splits by target (no leakage).
- `relabel.py`: tie-break among equally good best actions by largest margin beyond the spec (D16).
- `prompting.py`: `SYSTEM_PROMPT`, `format_prompt(state)`, `format_response`, `parse_response`: the one prompt/answer format shared by dataset, training, evaluation and the agent.
- `dataset_stats.py`: summary numbers for the dataset card.

**Evaluation (Phase 2-3)**
- `evaluation.py`: lookup-based scoring of a pick against the precomputed outcomes of every action (valid rate, tie-aware top-1, exact top-1, top-3, improvement rate, regret), bootstrap CIs, error-analysis breakdowns.
- `baselines.py`: random (exact expectation), majority label, and the textbook rules (one fixed fix per largest shortfall).
- `harness.py`: the fixed 150-example eval subset, scoring and saving predictions + metrics for any model.
- `predict.py`: one interface over Groq (OpenAI-compatible API, cached, rate-limit aware) and local Hugging Face models (+ LoRA, greedy or sampling).
- `report.py`: Phase 3 results tables.

**Fine-tuning (Phase 3)**
- `finetune.py`: LoRA SFT with TRL + PEFT (loss on the reply only, fp16 with an fp32 fallback, resumable checkpoints, token-length guard); can continue from an existing adapter; evaluates base vs fine-tuned on val, test and the subset.

**Agent, observability, RL (Phase 4)**
- `agent.py`: the multi-step loop, run in lock-step across episodes (one batched model call + one batched simulation per step), harness-side memory, failure detection and the four recovery paths; `SimPool` is the persistent simulation pool.
- `tracing.py`: the failure taxonomy, recovery names, step/episode record schema and the JSONL writer.
- `policies.py`: random, textbook rules and an LLM policy (any `predict` backend) behind one `choose(states)` interface.
- `agent_eval.py`: episode loading, agent metrics (success with CI, steps vs reference path, sims, recoveries, success-vs-budget).
- `expert_iteration.py`: builds the RL dataset from simulator-verified successes and mixes it with the Phase 2 train set.
- `phase4_run.py`: chunked, resumable rollouts for Colab.
- `mock.py`: a deliberately misbehaving fake model and a fault-injecting simulator, used to prove every failure class and recovery path fires.
- `report4.py`: Phase 4 tables, figure and readable traces.

**Plumbing**
- `paths.py`: the single source of truth for paths (Colab vs Mac); `drive_check.py`: manifests and `verify_manifest`; `resultszip.py`: weight-free results zips and their safe import.

Scripts in `scripts/` are thin command-line wrappers (build/relabel dataset, run baselines, run Groq, make tables, smoke tests); notebooks `01_finetune_eval` and `02_agent_rl` are the Colab runs.

---

## 2. Data flow

1. **Simulator** (ngspice, Level-1 devices) turns a `Design` into gain/UGF/PM/power/saturation; `spec_distance` turns that into one number.
2. **Dataset builder:** 600 random designs that meet their own (slackened) spec become targets; start states are targets pushed 2-6 lattice moves away; for each start state every action is simulated and ranked by distance improvement. Result: 3679 labeled states, 55,236 simulations, split 480/60/60 by target. Stored in git.
3. **Fine-tuning:** the best action (and a generated one-line reason) is the assistant message; Qwen2.5-0.5B + LoRA learns prompt -> action. Scored by lookup, no re-simulation.
4. **Agent:** the model is called on the *current* design at every step; its action is simulated for real; the harness remembers, detects failures and recovers.
5. **Expert iteration:** the agent is rolled out with sampling on training episodes; the simulator marks successes; improving, self-chosen, non-duplicate steps become new training examples; one more epoch from the adapter; re-evaluate.

---

## 3. The ten most important design decisions

1. **Simulator-only supervision.** Labels, rewards and evaluation all come from ngspice, never from a person or another model; this is also what makes expert iteration possible.
2. **Label = best of ALL simulated actions, and store every outcome.** Evaluation of any model is then a lookup (no GPU, no re-simulation), and regret and top-k are exact.
3. **Tie-aware top-1 as the headline metric** and a margin-based tie-break (D16): 27.5% of states had several equally good actions, so "exact id" would punish correct answers.
4. **Spec distance in normalized units** (dB/10, decades, deg/15, +1 per unsaturated device): terms are comparable, bounded and smooth, so it works as both ranking signal and reward.
5. **Split by target, not by state:** all states from one target stay together, so test designs are genuinely unseen.
6. **Same prompt everywhere** (`prompting.py`): the agent builds prompts from live states in exactly the training format; memory stays in the harness, not the prompt.
7. **Fair baselines:** same prompt for Groq and the small model, temperature 0, a fixed seeded eval subset for every method, and a strong rules baseline written before looking at results.
8. **Loss on the reply only, fp16 on the T4 with a finite-loss check and fp32 fallback;** a token-length assertion (the first plan of 512 would have cut 84% of replies).
9. **A failure taxonomy first, recovery second,** all behind one flag, so every recovery is an ablation with a paired CI (and tested with a mock that misbehaves on purpose).
10. **Expert iteration with strict selection:** only simulator-verified successes, only improving steps the model chose itself (no rules fallback), no duplicates, mixed with the original data to avoid forgetting; honest about being filtered behavior cloning rather than full RL.

---

## 4. Verbal walkthrough scripts

### 2-minute version
"The problem: a two-stage op-amp misses its spec; which parameter should an engineer change next? I built a simulator-verified pipeline for that. ngspice evaluates a design; for 3,679 failing designs I simulated all 14 possible moves and labeled the best one, so the supervision is pure simulator feedback. I fine-tuned a 0.5B Qwen with LoRA on that and scored it by lookup: on 150 held-out states its top-1 is 0.69, versus 0.51 for gpt-oss-120b and 0.40 for textbook rules, with the lowest regret. Then I made it an agent: up to eight steps, each step the model sees the current design, picks a move, the simulator applies it. I added tracing and a failure taxonomy; the main failure was loops, 194 of them, because the model is stateless. A harness-side recovery that blocks the looping move and re-asks lifts success from 78% to 90%. One round of expert iteration, training on its own simulator-verified successes, takes it to 94%, beating the rules agent at 76% while using fewer simulations. Caveats: same circuit family, Level-1 models, and the RL gain is small."

### 10-minute version
1. **Problem and why it is hard (1 min).** Analog sizing is a search over coupled knobs; each move helps one metric and hurts another. Goal: a small private model that chooses the next move, trained only on simulator feedback. Compare with a large general model.
2. **Simulator (1 min).** Two-stage Miller op-amp, Level-1 models (PTM was unreachable), ngspice, typed failures, cache, 165 sims/s. `spec_distance` is the single scalar everything uses.
3. **Dataset (2 min).** Targets from random designs with their own metrics as spec (so every spec is achievable); start states are inverse lattice moves from the target; every action simulated; ranking, ties, margin tie-break; split by target; dataset card. 3,679 states, 55k sims.
4. **Evaluation harness and baselines (1 min).** Lookup scoring: valid, tie-aware top-1, improvement rate, regret, CIs. Random 0.12, majority 0.33, textbook rules 0.44 on the full test split.
5. **Fine-tuning (1.5 min).** Qwen2.5-0.5B, LoRA r=16, 366 steps, 19 minutes on a free T4; the length bug and the torchao conflict as war stories. Results: 0.717 top-1 on 375 test examples (0.693 vs gpt-oss 0.513 on the 150-subset); improvement rate ties the rules, the gain is in choosing the *best* move.
6. **Agent and observability (1.5 min).** Lock-step batching, memory in the harness, taxonomy (six classes), four recoveries, one JSONL line per step. Show an example trace (the loop that gets blocked, then solved).
7. **Recovery ablation and RL (1.5 min).** 0.782 -> 0.902 with recovery (paired +0.121 [+0.075, +0.167]); expert iteration 0.943 (+0.040 [+0.006, +0.075]); LOOP events 194 -> 82 -> 47; sims per episode 2.9 vs rules 4.0.
8. **Limits and next steps (0.5 min).** In-distribution, solvable starts, one round, Level-1, one topology, no gpt-oss agent result; next: more rounds with negative signal, history in the prompt, OOD topologies and corners.

---

## 5. Fifteen likely questions

1. **Why a small model instead of GPT-class?** Privacy, cost and latency in a design loop that calls the model thousands of times. On this task the specialist is better as well: 0.693 top-1 vs 0.513 for gpt-oss-120b (n=150, CIs [0.620, 0.760] vs [0.433, 0.593]) and lower regret (0.056 vs 0.103), at about 8.8M trainable parameters.
2. **Is the comparison with gpt-oss fair?** Same system+user prompt, temperature 0, same 150 examples, medium reasoning effort, only the final message parsed, 2048 max tokens (2 of 150 were truncated and counted invalid). It is a one-shot, zero-example prompt, so a few-shot or tool-using large model could close some of the gap.
3. **Why does improvement rate tie the rules but top-1 does not?** Rules already find *a* helpful move 88% of the time (0.880 vs 0.873). The fine-tuned model picks the *best* move far more often (0.693 vs 0.400) and has lower regret (0.056 vs 0.073).
4. **How do you know the labels are right?** They are the argmax of simulated outcomes; 99.3% of labels improve the distance. Caveat: labels are one-step greedy and depend on my hand-weighted distance (D7), so a different weighting could change them.
5. **What was the tie problem?** 27.5% of states had several equally good actions (98% of them all solve the spec). Id-order labels favored cc_down/ibias_down; I switched to the largest-margin tie-break (370 labels changed) and kept tie-aware scoring as the headline.
6. **Where could there be leakage?** Split by target (480/60/60), asserted leak-free. Within the agent, rollouts used training episodes whose step-0 states were in SFT, which makes expert-iteration success (91.8%) optimistic; test numbers are on unseen targets.
7. **What does the harness do that the model cannot?** Memory. The model is stateless, so without it the model loops (194 LOOP events); recovery blocks the move and re-asks. That is why recovery adds +0.121 for the fine-tuned model but nothing for the rules agent (-0.006).
8. **Is recovery "cheating" by using extra calls?** Re-asks do not consume steps, so recovering agents get more model calls per step. I report policy calls (3.4 vs 4.1 per episode for rules) and simulations per episode (2.9 vs 4.0), and the ablation is paired.
9. **Why does the agent beat rules when its single-step accuracy is only 0.69?** Because it can choose different moves as the state changes and the harness prevents repeats; steps/reference is 0.45, so it solves with fewer moves than the construction used.
10. **Is the expert-iteration gain real?** +0.040 paired, CI [+0.006, +0.075]: positive but small, and single-step top-1 moved only 0.717 -> 0.731. It is one round of filtered behavior cloning with no negative signal; I would not claim more.
11. **Why is that RL?** The reward is verifiable and comes from the environment (the simulator says solved or not); we sample from the current policy, score trajectories, and raise the probability of actions on successful ones (expert iteration / ReST style). It is not policy-gradient RL: no value function, no failure signal.
12. **What would you change to improve it?** More rounds with a negative signal (DPO-style pairs from good vs bad moves at the same state), history in the prompt, and out-of-distribution training (topologies, corners).
13. **What are the model's weaknesses?** Step-3 states and phase-margin-limited states (top-1 0.56 vs 0.75 for rules), and phase-margin-limited failures in general; the failure example trace shows it oscillating around the spec boundary with cc_up/cc_down.
14. **How realistic is the circuit?** Not very: Level-1 devices (lambda ~ 1/L), one topology, nominal temperature and supply, ideal bias current. The approach and tooling transfer; the numbers do not. A BSIM/PTM card and PVT corners are the first things to add.
15. **What went wrong along the way?** Three real bugs, each caught by a test or a smoke run: replies truncated at max_length 512 (84% of examples; fixed to 640 with an assertion), a Colab-preinstalled torchao 0.10 that broke peft (uninstall + fail-early check cell), and an Apple-silicon quirk where the editable-install file gets hidden (worked around with `PYTHONPATH` and `pythonpath` in pytest).
