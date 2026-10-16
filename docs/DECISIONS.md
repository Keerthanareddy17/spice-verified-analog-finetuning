# Architecture decision log

Each entry records the context, the decision (with the options considered) and its consequences, including trade-offs.
Entries are grouped by project phase. D9 is superseded by D23.

# Phase 1: simulation environment

## D1. Device models: SPICE Level-1 with lambda proportional to 1/L, not a PTM BSIM card
**Context.** The preferred model source was the ASU Predictive Technology Model (PTM) 180 nm bulk BSIM card. `ptm.asu.edu` was unreachable (DNS failure) when the environment was built, and the only public copies found were third-party netlists of unverifiable provenance.
**Decision.** Use textbook Level-1 parameters (`src/analogft/circuit/models.py`): VDD 1.8 V, Lmin 0.18 um, NMOS Vto 0.45 V / KP 170 uA/V^2, PMOS Vto -0.45 V / KP 60 uA/V^2, gamma 0.4, phi 0.85, TOX 4.1 nm, overlap capacitance 0.3 fF/um, junction capacitances from a 0.5 um diffusion. Channel-length modulation is lambda = 0.04/L[um] (NMOS) and 0.05/L[um] (PMOS), generated per device by the netlist builder, so longer channels give more gain (`test_longer_l_gives_more_gain`). The threshold is read from ngspice's `von`, which includes the body effect.
**Consequences.** Level-1 has no short-channel effects, velocity saturation or subthreshold conduction: results are realistic in shape, not silicon-accurate. This is adequate for the research question (can a model learn design moves from simulator feedback) and is stated as a limitation in the README. If a PTM card becomes available, only `models.py` changes.

## D2. Fixed circuit values
**Decision.** CL = 2 pF; VDD = 1.8 V; input common mode 0.5 VDD (0.9 V), which leaves headroom for the NMOS pair and tail below and the PMOS mirror above and puts the closed-loop DC output mid-rail; temperature 27 C. M8 width is fixed at 10 um; M5 and M7 widths are `tail_ratio` and `out_ratio` times that, so branch currents scale with Ibias. Knob bounds (`design.py`) span one to two decades each.
**Consequences.** Random designs mostly simulate but many are broken, which is what dataset construction needs. One load, supply and temperature: no PVT coverage.

## D3. Open-loop AC measurement with DC feedback (loop break)
**Context.** An op-amp with about 75 dB of gain has a systematic offset; in open loop at DC the offset times the gain drives the output to a rail, so the operating point and the AC response are meaningless.
**Decision.** Connect the inverting input to the output through a 1e9 H inductor and to AC ground through a 1e9 F capacitor. At DC the inductor is a short, so the operating point is that of a unity-gain buffer; from 1 Hz upward the loop is open and the true open-loop response is measured with the AC stimulus on the non-inverting input. The stage-1 output rises with M1's gate and stage 2 inverts, so M1's gate is the inverting input; a test checks that the low-frequency phase is about 0 deg.
**Consequences.** Verified on the nominal design: gain flat within 0.2 dB from 1 Hz to 1 kHz and phase at 1 Hz under 5 deg (`test_lowfreq_response_flat_and_in_phase`); the simulator rejects any result with |low-frequency phase| above 30 deg. A failed DC solve at an extreme design appears as a saturation or measurement failure; such designs are invalid either way.

## D4. Measurements and failure types
**Decision.**
- AC sweep 1 Hz to 10 GHz, 30 points per decade.
- `dc_gain_db`: magnitude at 1 Hz. `ugf_hz`: first downward 0 dB crossing, interpolated in log-frequency. `pm_deg`: 180 deg plus the unwrapped phase at UGF (shifted by a multiple of 360 deg into (-180, 180]). `power_w`: VDD times the absolute supply current (including the bias branch). `vout_dc`: operating-point output.
- Saturation rule: |Vds| >= |Vdsat| + 50 mV and |Vgs| > |Vth|, from ngspice operating-point values.
- Two failure kinds. The simulation failed and produced no numbers (NONCONVERGENCE, TIMEOUT, PARSE_ERROR, NGSPICE_ERROR). Or it ran but the design is invalid (DEVICE_NOT_SATURATED keeps all metrics with `ok=False`; MEASUREMENT_MISSING keeps operating-point data but no AC metrics, e.g. no 0 dB crossing). `SimResult.ran` distinguishes them. A design with all devices saturated and a negative phase margin is `ok=True` and simply fails the spec.
- Each simulation runs in its own temporary directory with a 10 s timeout. Results other than TIMEOUT are cached by the SHA-256 of the netlist text plus the ngspice version, written atomically so parallel workers are safe.

## D5. Hand-sized nominal design
**Decision.** Sizing procedure: targets UGF about 30 MHz, Cc = 1 pF, PM 50-70 deg, power at most 1 mW. UGF = gm1/(2 pi Cc) gives gm1 = 188 uS. With Vov1 = 0.15 V, ID1 = 14 uA and the tail is 28 uA (tail_ratio 1.4 at Ibias = 20 uA). Square law gives W1/L1 = 7.4, so W1 = 3.7 um at L = 0.5 um. Second stage: gm6 about 10 gm1 = 1.9 mS, Vov6 = 0.2 V, I6 = 190 uA (out_ratio 9.5), W6/L6 = 158, so W6 = 79 um. Mirror load: Vov3 = 0.2 V at 14 uA, W3/L3 = 11.7, so W3 = 5.8 um.
**Consequences.** Simulated nominal result: gain 74.2 dB, UGF 27.9 MHz (target 30), PM 67.8 deg, power 0.436 mW, all 8 devices saturated, Vout = 0.90 V, with no target adjusted. PM sits at the upper end of the 50-70 deg window, leaving room for actions to move it either way. An earlier arbitrary sizing (40 um / 20 / 100 um) gave PM 26 deg and UGF 85 MHz.

## D6. Action set
**Decision.** 14 actions: multiply or divide one of cc, ibias, w_in, l_in, l_load, w_cs, out_ratio by 1.3. Action ids (`cc_up`, `cc_down`, ...) are the model's output vocabulary and must stay stable. Descriptions are factual and never state the effect of an action (enforced by a test). An action that clipping turns into a no-op is unavailable. The other knobs (w_load, l_cs, l_bias, tail_ratio) stay fixed after the start state.
**Consequences.** A label space of at most 14 keeps the problem learnable; the design space reachable by the agent is a 7-dimensional lattice.

## D7. Spec distance
**Decision.** gain: shortfall in dB / 10; UGF and power: log10 ratio (decades); PM: shortfall in deg / 15; +1.0 per unsaturated device; 10.0 when no complete metrics exist (also for MEASUREMENT_MISSING, as a simple conservative rule). One unit is roughly 10 dB, one decade, 15 deg or one broken device.
**Consequences.** Terms are comparable, bounded and smooth, which is what ranking (labels) and reward (Phase 4) need. Observed concern, not changed: among 500 random designs the 5th-percentile PM was -71 deg, which alone scores (50+71)/15 = 8.1, close to the 10.0 failure penalty, so a spec-failing design can score nearly as badly as a failed simulation; ordering remains correct. Labels depend on this hand-chosen weighting.

## D8. Parallelism and speed
**Decision.** A `multiprocessing` spawn pool with `cpu_count - 1` workers and chunked jobs. Scripts using `simulate_batch` need an `if __name__ == "__main__":` guard because of `spawn`.
**Consequences.** On a MacBook Air M4 (9 workers): about 165-170 simulations/s uncached (500 random designs in about 3 s) and about 890/s on a fully cached rerun (dominated by pool overhead); 60k simulations take roughly 6 minutes.

## D9. Drive synchronisation (superseded by D23)
**Decision.** Originally `rsync` between the repository and a locally mounted Drive folder, with a manifest (names, sizes, row counts) written before each push and checked by the Colab notebooks. `.gitignore` excludes `.simcache/`, `.env` and `CLAUDE.md`.
**Consequences.** Replaced by D23; the manifest mechanism (`drive_check.py`) is retained.

# Phase 2: dataset

## D10. Targets, specs and start states
**Decision.**
- Targets: each of the 11 knobs log-uniform in [nominal/3, nominal*3], clipped to bounds; kept if the simulation ran, all devices are saturated and PM >= 50 deg. Yield 600/1133 (53%).
- Spec from the target's own metrics with slack: gain minus U(0,3) dB, UGF times U(0.75,0.95), PM minus U(0,10) deg clamped to [45,70], power times U(1.05,1.3). Values are rounded toward slack (floor for minimums, ceiling for the power maximum) at 0.1 dB / 10 kHz / 0.1 deg / 1 uW, so the prompt shows exactly the number used for scoring and the target still passes (asserted for every target).
- Start states: only the 7 action knobs move, by 1.3^k with k in [-3,3] and total |k| in [2,6]. Rejection sampling requires that no perturbed knob hits a bound; otherwise clipping would move the start off the lattice and inverse moves would not recover the target (tested by applying real inverse actions).
- Filter: the simulation ran and spec_distance is in (0, 5]. The farthest start is 4.14; 3 of 3600 candidates were rejected as too far and 797 (22%) already met the spec because of the slack, so 2x candidates are sampled per wanted start (3 per target). 42 starts fall short of 1800 because a few targets had too few failing candidates.
- States that converge to the same design within a target are labeled once.
**Consequences.** Every spec is achievable and every start is at most 6 inverse moves from a solution. Starts are slightly biased away from the bounds.

## D11. Labeling and ties
**Decision.**
- Every available action is simulated from each state (about 15 simulations per labeled state); `improvement = distance_before - distance_after`. Failed or unsaturated outcomes keep their natural distance and rank last; they are not dropped.
- Greedy trajectory: after labeling a state, the best action is applied if it improves the distance and the result still fails the spec, for up to 3 more steps, so later steps are states an agent would actually see (step 0: 1758, 1: 1088, 2: 586, 3: 247).
- 27.5% of states have a tie for the best action, and 98% of those are several actions that each fully solve the spec. Top-1 and top-3 are therefore tie-aware (a pick matching the best improvement is correct; rank = 1 + number of strictly better actions) and `top1_exact` is reported alongside.
**Consequences.** Labels are one-step greedy, not an optimal plan, and can disagree with the best two-step plan; in exchange they are cheap and exactly scoreable by lookup. The tie-break of the training label is revisited in D16.

## D12. Textbook-rules baseline (`src/analogft/baselines.py`)
**Decision.** Compute each normalized shortfall in the same units as the spec distance (`shortfall.py`, tested to sum to the distance), take the largest, apply one fixed move, and fall back to the next-largest if the move is unavailable. The rules were fixed before any result was seen: PM low -> cc_up (raises Cc, lowers the dominant pole and splits the poles); UGF low -> w_in_up (UGF is about gm1/(2 pi Cc) and gm1 grows with W/L); gain low -> l_load_up (longer load devices raise output resistance); power high -> ibias_down (all branch currents scale with Ibias); unsaturated devices: M1, M2, M5 -> w_in_up, M3, M4 -> l_load_down, M6 -> w_cs_up, M7, M8 -> ibias_down, tried in name order.
**Consequences.** A deliberately simple bar: one rule per shortfall, no look-ahead, no knowledge of magnitudes or side effects. A model must beat it to show it learned more than a designer's first instinct.

## D13. Scoring conventions (`src/analogft/evaluation.py`)
**Decision.** An invalid or unavailable pick counts as a no-move: wrong for top-1, top-3 and improvement rate, and improvement 0 for regret (regret = best improvement minus picked improvement). Random is the exact expectation over each state's available actions. Majority returns the most frequent training label and is invalid where that action is unavailable. Regret is averaged over all states, including those where no action improves.
**Consequences.** Penalizing invalid output like the worst action would make it look worse still; the no-move rule is the simplest meaningful convention.

## D14. Prompt and response format (`src/analogft/prompting.py`)
**Decision.** One user message holds the spec, current metrics, failing specs with shortfalls, unsaturated devices only, knobs in engineering units (action knobs, then the 4 fixed knobs, which affect gain and headroom) and the available actions with neutral descriptions. The system prompt carries the output contract. The reply is one JSON line `{"action", "reason"}`, with the reason generated from data: the largest normalized shortfall plus the simulated effect of the chosen action on that metric and on the metric that moved most (if at least 0.03 distance units). `format_response` takes the spec as a fourth argument because "largest shortfall" is undefined without it. `parse_response` accepts a JSON object anywhere in the text (code fences, chatter) and requires a string `action` field; truncated or malformed JSON is invalid (`no_json`).
**Consequences.** The user message has a median of 258 estimated tokens (330 with the system prompt; measured Qwen token counts are in D20). Strict parsing keeps the valid-output rate a real measure of format discipline.

## D15. Splits and files
**Decision.** Split by target (`group_id`) 80/10/10 with a seeded permutation: 480/60/60 targets. All states and episodes of a target stay together (asserted in the build and tested). Pilot output goes to `data/phase2_pilot/` (not tracked); all settings live in `configs/phase2.json` (seed 0). Starts are simulated in one batch for all targets.
**Consequences.** Test designs come from targets never seen in training.

# Phase 3: fine-tuning and evaluation

## D16. Training-label tie-break: largest margin beyond the spec
**Context.** 27.5% of states have several equally good best actions. Taking the lowest action id biases labels toward cc_down and ibias_down without physical reason.
**Decision.** Among tied best actions choose the one whose resulting design has the largest margin beyond the spec, then action-id order if margins also tie. Margin is the minimum over the 4 specs of the normalized slack after the action, in the units of the spec distance (gain dB/10, UGF and power in decades, PM deg/15; `shortfall.slack_terms`). Options considered: keep id order; random among ties (adds noise); drop tied states (discards the states where "any solving move is fine" must be learned). The margin rule prefers a robust fix over one that barely passes, is deterministic, and is computed from the stored `action_outcomes` with no new simulation.
**Consequences.** Applied by `scripts/relabel_dataset.py` (a label may only change among tied actions; every unchanged label regenerates a byte-identical assistant message); `dataset.label_nodes` uses the same rule for new builds. 370 of 1012 tied states changed label. Tie-aware metrics are unchanged, exact-id metrics changed, and tie-aware scoring remains the headline metric. Later states of an episode (steps 1-3) were reached by following the previous greedy action; their labels are valid for their own states, only the set of states reflects the old tie-break.

## D17. Evaluation subset
**Decision.** 150 of the 375 test examples, seeded (0) and stratified by `step_index` with proportional allocation (largest remainder); ids in `results/phase3/eval_subset_ids.json`. Every method is scored on the subset and on the full test split, except Groq models (subset only). Groq examples run in a fixed shuffled order, so a run stopped early by a daily cap would still be an unbiased sample.
**Consequences.** The Groq free tier cannot score 375 reasoning-model calls per day, and all methods are compared on identical examples. Confidence intervals on the subset are wider (n=150) and are reported.

## D18. Large-model baselines: openai/gpt-oss-120b (main), qwen/qwen3.8-27b (additional)
**Context.** The research question is whether a small specialist can beat a large general model, so the baseline should be the strongest open-weight general model available on Groq.
**Decision.** gpt-oss-120b is a reasoning model with production status on Groq and open weights; it runs at its medium reasoning effort so that it is not a weak baseline. Qwen3.8-27B (preview) is the same family as the small model but about 50x larger and untrained on this data, which isolates size from specialization; it runs in its default mode (no reasoning-effort parameter, no reasoning tokens). Fairness: identical system and user messages as the small models (`predict.build_messages`), temperature 0, only the final message content is parsed, `max_completion_tokens` 2048 so reasoning does not cut off the JSON (truncations are counted), and responses cached on disk by (model, example id). Both model ids were confirmed present in the account's model list.
**Consequences.** Observed: limits from response headers are 8,000 tokens/min and 1,000 requests/day per model (the 200,000 tokens/day cap is not exposed in headers; gpt-oss used about 159K). gpt-oss: about 1060 tokens per example (498 prompt, 562 completion of which about 520 reasoning), 1.6 s per call, 2 of 150 outputs truncated at 2048 tokens (counted invalid), about 45 minutes wall time because of the per-minute cap. qwen3.8-27b: about 541 tokens per example, no truncation, 100% valid.

## D19. Small model: Qwen2.5-0.5B/1.5B-Instruct instead of Qwen3-0.6B/1.7B
**Decision.** Qwen3's chat template has a thinking mode (`<think>` blocks) that complicates training targets and output parsing. Qwen2.5-Instruct has a plain, stable template, mature TRL/PEFT support, and fits a free T4. The 0.5B model is the first run; 1.5B is the intended larger run.
**Consequences.** Deviation from the original model choice; the 1.5B configuration is available in the notebook but has not been run.

## D20. Fine-tuning setup
**Decision.**
- LoRA r=16, alpha=32, dropout 0.05 on all attention and MLP projections (q, k, v, o, gate, up, down); 8,798,208 trainable parameters for the 0.5B model. The task is narrow (one of at most 14 labels plus a one-line reason), so a small adapter suffices, and all-linear targeting is closer to full fine-tuning than attention-only.
- Learning rate 2e-4, cosine decay, 5% warmup, 2 epochs, effective batch 16, seed 0: 183 steps per epoch, 366 in total; logging every 10 steps, validation and checkpoints every 50.
- fp16 mixed precision (the T4 has no bf16): base weights in fp16, LoRA weights in fp32 (PEFT), fp16 autocast with loss scaling. Because fp16 can overflow, one forward pass before training checks that the loss is finite and otherwise reloads in fp32 (slower, twice the memory, still fits). A non-finite logged training loss fails the run.
- Loss on the reply only (prompt/completion format with `completion_only_loss=True`), verified by printing the tokens that carry loss for one example (the JSON reply and `<|im_end|>`).
- `max_length` 640. The initial value of 512 was based on a 4-characters-per-token estimate; measured Qwen token counts are prompt 428-502, reply 38-49, full conversation up to 550, so 512 would have truncated the reply of 84% of examples (3104 of 3679). `train()` asserts that the longest example fits; padding is per batch, so the larger limit has no cost.
- Generation is greedy with `max_new_tokens` 64 (replies are at most 49 tokens) and the training chat template.
- Checkpoints (`runs/phase3/<run>/checkpoints/`, resumable, `save_total_limit` 2) are kept separate from evaluation outputs so that metrics can be exported without weights.
**Consequences.** Training took 366 steps in 19.3 minutes on a T4 with fp16 retained.

## D21. Library versions and local environment
**Decision.** Pinned in `requirements-colab.txt`: transformers 5.20.0, trl 1.16.0, peft 0.21.2, accelerate 1.15.0, datasets 5.1.0 (torch is not pinned on Colab; 2.14.1 locally). Verified together by the local smoke test. API changes encoded in the code: transformers 5 renamed `torch_dtype` to `dtype` and replaced `warmup_ratio` by `warmup_steps` (a float below 1 is a ratio); TRL 1.x tokenizes inside the trainer and exposes `labels` with -100 on the prompt.
**Consequences.** On macOS, the editable-install `.pth` file can acquire the "hidden" flag, which makes Python 3.13+ ignore it. `pyproject.toml` therefore sets `pythonpath = ["src"]` for pytest and scripts can be run with `PYTHONPATH=src`.

## D22. Statistics
**Decision.** 95% CIs are percentile bootstrap intervals over states (2000 resamples, seed 0) of the per-state score, for tie-aware top-1, improvement rate and mean regret; for `random` the per-state score is its exact expectation.
**Consequences.** Methods are compared on the same states, so overlap of unpaired intervals is only a rough guide; paired tests (used in Phase 4) are tighter.

## D23. Dataset versioned in git for reproducibility; run artifacts exchanged as a weights-free results archive
**Context.** Training and evaluation on Colab need an exact, versioned copy of the data. A locally mounted Drive folder proved unreliable as the transport for it.
**Decision.** Options considered: a synchronised Drive folder; manual upload through the Drive web UI; committing the dataset to git; Git LFS. The dataset is committed (about 23 MB; `train.jsonl` is 16.8 MB, below GitHub's 50 MB warning): `data/phase2/*.jsonl`, `data/phase2/build_stats.json`, `data/samples/` and `data/manifest.json`. Everything else under `data/` and `runs/` stays untracked, and `scripts/check_large_files.sh` keeps a 10 MB warning for all other files (50 MB for the allowed data files). On Colab, `DATA_DIR` is the checked-out repository, verified against `manifest.json`; `RUNS_DIR` and `RESULTS_DIR` are on the mounted Drive. Results leave Colab as a small archive written by the notebook (`runs/phase3/<run>_results.zip`, `runs/phase4_results.zip`: eval, logs, figures, config, traces and metrics; no checkpoints or adapters), unpacked by `scripts/import_results_zip.py`, which accepts only that layout (path traversal is rejected; tested).
**Consequences.** The repository grows by about 23 MB per dataset version, so relabeling or rebuilding should be rare; the dataset is public with the code (it is simulator-generated, so nothing private is exposed). `ANALOGFT_STORAGE_ROOT` still relocates all storage paths (used by tests).

## D24. Colab dependency conflict: preinstalled torchao
**Context.** The first T4 run failed with `ImportError: Found an incompatible version of torchao. Found version 0.10.0, but only versions above 0.16.0 are supported`, raised in `peft.import_utils.is_torchao_available` while `get_peft_model` (called from `SFTTrainer.__init__`) built the LoRA layers. Colab preinstalls torchao 0.10.0; peft 0.21.2 probes for it when creating a LoRA layer and rejects versions below 0.16. torchao is not used by this project.
**Decision.** Options: upgrade torchao (its binary extensions are built against a specific torch, and Colab's torch was 2.11.0+cu130, so this risks a new conflict); downgrade peft (loses the versions verified together); uninstall torchao. The notebook runs `pip uninstall -y torchao` before installing `requirements-colab.txt`. A check cell after the install prints versions of torch, transformers, trl, peft, accelerate, datasets, torchao and bitsandbytes, imports `get_peft_model` and calls every `is_*_available` check in `peft.import_utils`, failing before any model is loaded.
**Consequences.** The local smoke test could not catch this because a clean virtual environment lacks Colab's preinstalled extras; an environment check cell is now part of the Colab notebooks. Training logic and hyperparameters are unchanged.

## D25. Phase 3 outcome
**Result.** Qwen2.5-0.5B-Instruct with LoRA (D20 settings), fp16 retained, 366 steps in 19.3 minutes on a T4. Final train loss 0.188 (run average), validation loss 0.110 (down from 0.204 at step 50, no sign of overfitting). All 150 subset outputs were valid and none truncated. On the eval subset (n=150): tie-aware top-1 0.693 [0.620, 0.760] against gpt-oss-120b 0.513 [0.433, 0.593], textbook rules 0.400 and the untrained base 0.187; improvement rate 0.873, tied with textbook rules (0.880); mean regret 0.056, the lowest. Full test (n=375): top-1 0.717, regret 0.042.
**Interpretation.** The gain over the rules is in selecting the best move, not a helpful move. The evaluation is single-step and in-distribution, with Level-1 models. The weakest cells are step 3 (n=11) and phase-margin-limited states, where the rules still win top-1.
**Notes.** The loss curve is copied to `results/figures/phase3_loss_curve.png` because `runs/` is not tracked. `import_results_zip.py` also accepts an already extracted results folder.

# Phase 4: agent, observability, expert iteration

## D26. Agent loop (`src/analogft/agent.py`)
**Decision.**
- An episode is a (spec, start design) pair from `data/phase2/episodes_<split>.jsonl`. For up to 8 steps: build the prompt from the current state with `prompting.format_prompt` (the format used in training), ask the policy for one action, apply it, simulate, compute `spec_distance`; stop at distance 0, where the simulator is the judge.
- Memory (best design so far, visited designs, blocked actions, last action per state) lives in the harness, not the prompt. Putting history in the prompt would be richer but outside the training distribution of the fine-tuned model; memory reaches the model only through a shorter action list (blocked actions removed) and, on a re-ask, one appended sentence.
- Episodes run in lock-step: each step makes one batched policy call and one batched simulation (`SimPool`, a persistent spawn pool; creating a pool per step would dominate run time). A slow answer holds up the batch, which is acceptable on a GPU where batching makes generation fast.
- The reference path length of an episode is the sum of |k| of its `lattice_k` (inverse moves from the start design to its target). It is a known solution length, not a minimum; an agent may use fewer or more moves.
- Policies share one interface (`policies.py`: `choose(states, notes) -> Prediction`): textbook rules, random, any `predict.Backend` (Groq, Hugging Face + LoRA, mock). Sampling temperature is a property of the Hugging Face backend.
- Counting: `sims` per episode counts new designs simulated (a revisited design reuses its stored result). A step with an invalid output and no usable fallback is wasted (no simulation) and still uses budget.

## D27. Failure taxonomy (`src/analogft/tracing.py`)
**Decision.** INVALID_OUTPUT (unparseable output, unknown action id, API error, or a rules policy with no move); UNAVAILABLE_ACTION (a real id not in this state's list, which includes blocked actions); SIM_FAILURE (the new design has no complete metrics); LOOP (the move returns to a design already visited in the episode); NO_PROGRESS (3 consecutive steps without improving the best distance; wasted steps, failed simulations and loops all count); BUDGET_EXHAUSTED (budget used without meeting the spec, once per unsolved episode). Classes are detected in both modes, so the agent without recovery is diagnosed as well; the recovery flag only decides whether the harness reacts.
**Consequences.** Design identity for loop detection uses the rounded log of every knob (4 decimals), because multiplying by 1.3 and dividing by 1.3 is not bit-exact in floating point (covered by a test).

## D28. Recovery paths (one flag: `recovery=True`)
**Decision.**
- INVALID_OUTPUT / UNAVAILABLE_ACTION: re-ask once with the error sentence appended to the user message; if still invalid, fall back to the textbook-rules action for that state (logged as `fallback_rules`; the episode gives up if the rules also have no move).
- LOOP: block the looping action at that state, remove it from the action list and re-ask (no note). If the re-ask is invalid, fall back to the rules; if it loops again it is accepted, and NO_PROGRESS will catch a genuine cycle.
- SIM_FAILURE: do not adopt the failed design (rollback means staying at the previous design) and block the action at that state.
- NO_PROGRESS: roll back to the best design so far and block the action last taken there.
- Without recovery the agent keeps going: an invalid output wastes the step, a loop is taken, a failed simulation is adopted as the new state.
**Consequences.** Recoveries cost extra policy calls and sometimes simulations, but a re-ask inside a step does not consume an additional step of the 8-step budget. This slightly favors the recovering agent, so policy calls and simulations per episode are reported next to success, and the ablation is paired (same episodes) with a bootstrap CI on the difference. `mock.MockBackend` (invalid JSON, unknown id, unavailable id, oscillating cc_up/cc_down) and `mock.FaultySim` (every n-th simulation fails) make every class and path fire on real ngspice episodes (`scripts/smoke_agent.py`, `tests/test_agent.py`).

## D29. Agents compared and the Groq subset
**Decision.** Random and textbook rules (each with and without recovery) run on all 174 test episodes locally; the fine-tuned model without recovery, with recovery and after expert iteration run on Colab. Groq agents run on a fixed seeded subset of 30 test episodes (`results/phase4/groq_episode_ids.json`), because the free tier's token limits cannot cover 174 episodes of a multi-step reasoning model. The Groq cache is keyed by a hash of the whole prompt, so the identical step-0 prompts of Phase 3 are reused at no cost and an interrupted run resumes without new tokens. Every other agent is also re-scored on exactly the episodes the Groq agent finished. If a cap stops a run, n is whatever finished; nothing is estimated.
**Outcome.** The gpt-oss-120b agent did not complete: the daily cap stopped it ("Limit 200000, Used 198046, Requested 2399") after 58 uncached calls, and a lock-step run that aborts scores nothing, so no gpt-oss agent number is reported. Its 58 responses are cached in `results/phase4/groq_openai_gpt-oss-120b_recovery/cache.jsonl`; rerunning `python scripts/run_agent.py --policy groq --model openai/gpt-oss-120b --n-episodes 30 --recovery on` after the cap resets resumes from the cache. qwen/qwen3.8-27b (default mode, about 540 tokens per call, separate daily budget) completed both modes on the same 30 episodes and is the large-model agent in the tables.

## D30. Expert iteration, one round (`src/analogft/expert_iteration.py`)
**Decision.**
- Rollouts: the Phase 3 model with recovery, sampling at temperature 0.8, k=2 rollouts per training episode over a seeded subset (704 of 1408 episodes by default, so that rollouts fit a 60-minute Colab budget; all settings are in the notebook's configuration cell).
- The simulator is the reward. Only rollouts that reached the spec are kept. From those, only steps that (a) improved spec_distance (no detours), (b) were the model's own choice (no rules-fallback steps) and (c) are not exact duplicates of a Phase 2 training example (a duplicate would only double-weight what the model already knows). One label per prompt: the largest improvement.
- The new (prompt -> action) examples, written in the same reply format (`format_response` from the stored before/after metrics), are mixed with the Phase 2 training set to limit forgetting; training continues from the Phase 3 adapter for 1 epoch at lr 1e-4 with the same LoRA configuration and fp16 handling (`FTConfig.init_adapter`, `train_file`).
**Rationale for calling it RL.** It is policy improvement with a verifiable reward from the environment: sample from the current policy, score trajectories with the simulator, and increase the probability of actions on successful trajectories (filtered behavior cloning, as in expert iteration, ReST and RFT). It is not policy-gradient RL: there is no value function, no negative signal from failures and only one round.
**Expected effect.** Training on its own successes mostly reinforces moves the model already makes, so gains are expected to be small; the new information is in later-step states and alternative good moves. Before/after results are reported with paired CIs.

## D31. Results transport for Phase 4
**Decision.** Notebook 02 writes `runs/phase4_results.zip` (agent traces and metrics, RL dataset statistics, per-chunk rollout episode records, RL evaluation, logs and figures; never weights, `rl_train.jsonl` or the large per-step rollout states; tested). `import_results_zip.py` detects the `phase4/` layout, and `make_phase4_table.py` copies the Colab agents into `results/phase4/` so they are tracked next to the locally run agents. This follows D23.

## D32. Phase 4 outcome
**Result.** On the 174 test episodes with an 8-step budget: textbook rules 0.759 [0.690, 0.822]; fine-tuned agent without recovery 0.782 [0.718, 0.845]; with recovery 0.902 [0.856, 0.948]; after expert iteration with recovery 0.943 [0.908, 0.977]. Paired differences: recovery +0.121 [+0.075, +0.167]; expert iteration +0.040 [+0.006, +0.075]. LOOP events: 194 without recovery, 82 with recovery, 47 after expert iteration. Simulations per episode: 2.3, 2.9 and 2.7 for the three fine-tuned agents against 4.0 for the rules. The round sampled 1408 rollouts, 1293 solved (91.8%), and added 1579 new examples to 2926 original ones (1196 exact duplicates and 295 non-improving steps dropped).
**Caveats.** The rollouts used training episodes whose start states were part of supervised training, so their success rate is optimistic. Test targets are unseen but come from the same circuit and spec generator, and every start is solvable by construction. The gpt-oss agent has no result (D29), and the 30-episode qwen3.8-27b pilot is inconclusive.
