# Design decisions

Format: decision, options considered, why, trade-off.

## D1. Device models: SPICE Level-1 with lambda ~ 1/L (not PTM BSIM)
- **Options:** (a) ASU PTM 180 nm bulk BSIM card (preferred); (b) Level-1 textbook parameters.
- **What happened:** `ptm.asu.edu` did not resolve from this machine (DNS failure; WebFetch failed the same way). The only GitHub hits were third-party netlists, not the authoritative card, so I did not trust their provenance. Time-box hit, so (b).
- **Parameters** (`src/analogft/circuit/models.py`): VDD 1.8 V, Lmin 0.18 um, NMOS Vto 0.45 V / KP 170 uA/V^2, PMOS Vto -0.45 V / KP 60 uA/V^2, gamma 0.4, phi 0.85, TOX 4.1 nm, overlap caps 0.3 fF/um, junction caps with AD/AS/PD/PS from a 0.5 um diffusion. Lambda = 0.04/L[um] (NMOS), 0.05/L[um] (PMOS), generated **per device** by the netlist builder, so longer L really gives more gain (test `test_longer_l_gives_more_gain`).
- **Trade-off:** Level-1 has no short-channel effects, no velocity saturation, no subthreshold conduction. Numbers are realistic in shape, not silicon-accurate. This is fine for the research question (can a model learn design moves from simulator feedback?) but should be stated honestly in the README. Level-1 does not expose Vth directly; I use ngspice's `von` (threshold including body effect).
- **Future:** if the PTM card becomes reachable, swapping `models.py` is the only change; everything downstream uses the same interface.

## D2. Fixed values
- CL = 2 pF (reasonable for 180 nm; gives UGF in the tens of MHz with Cc ~1 pF). VDD = 1.8 V. Input common mode = 0.5 VDD (0.9 V): leaves headroom for the NMOS pair + tail below and the PMOS mirror above, and puts the closed-loop DC output at 0.9 V, mid-rail. Temperature 27 C. M8 width fixed at 10 um; M5 and M7 widths are `tail_ratio` and `out_ratio` times that, so currents scale with Ibias.
- Knob bounds (`design.py`) span roughly one to two decades each so random designs mostly simulate but many are broken, which is what Phase 2 needs.

## D3. Open-loop AC with DC feedback (the loop-break trick)
- **Problem:** an op-amp with ~75 dB gain has a systematic offset; in open loop at DC that offset times the gain slams the output to a rail, so the operating point is garbage and the AC response is meaningless.
- **Trick:** connect the inverting input to the output through a huge inductor (1e9 H) and from the inverting input to AC ground through a huge capacitor (1e9 F). At DC the inductor is a short, so ngspice solves the operating point as a unity-gain buffer (offset absorbed, output sits near Vcm). At AC (>= 1 Hz) the inductor is open and the capacitor is a short to ground, so the loop is broken and we measure the true open-loop response with the AC stimulus on the non-inverting input.
- **Polarity:** the stage-1 output rises with M1's gate (via the mirror) and stage 2 inverts, so M1's gate is the *inverting* input and M2's the non-inverting one. The test checks the low-frequency phase is ~0 deg.
- **Verified:** nominal gain is flat within 0.2 dB from 1 Hz to 1 kHz and phase at 1 Hz is under 5 deg (`test_lowfreq_response_flat_and_in_phase`). The simulator additionally rejects any result with |low-frequency phase| > 30 deg.
- **Trade-off:** a failed DC solve at an extreme design shows up as a saturation or measurement failure rather than a true "bad" operating point. That is acceptable, since those designs are invalid either way.

## D4. Measurements and failure types
- AC sweep 1 Hz to 10 GHz, 30 points/decade (301 points).
- `dc_gain_db`: magnitude at 1 Hz. `ugf_hz`: first downward 0 dB crossing, linearly interpolated in log-frequency. `pm_deg`: 180 + unwrapped phase at UGF (phase shifted by a multiple of 360 so it starts in (-180, 180]). `power_w`: VDD times |supply current| (includes the bias branch). `vout_dc`: operating-point output.
- **Saturation rule:** `|Vds| >= |Vdsat| + 50 mV` and `|Vgs| > |Vth|`, using ngspice's operating-point `vds`, `vdsat`, `vgs`, `von` (absolute values handle PMOS signs).
- **Two kinds of failure.** The simulation *failed*: no numbers (NONCONVERGENCE, TIMEOUT, PARSE_ERROR, NGSPICE_ERROR); metrics empty. The simulation *ran but the design is invalid*: DEVICE_NOT_SATURATED (all metrics kept, `ok=False`) or MEASUREMENT_MISSING (operating-point metrics and regions kept, AC metrics absent, e.g. no 0 dB crossing). `SimResult.ran` distinguishes them.
- A design with all devices saturated and a negative phase margin is `ok=True`; it just fails the spec (the spec distance penalizes it).
- Each simulation runs in its own temp dir with a 10 s timeout. Results (except TIMEOUT) are cached by SHA-256 of netlist text + ngspice version, written atomically so parallel workers are safe.

## D5. Nominal design, hand-sized
1. Targets: UGF ~30 MHz, Cc = 1 pF, PM 50-70 deg, power <= 1 mW.
2. Stage-1 gm: UGF = gm1 / (2 pi Cc) gives gm1 = 188 uS.
3. Pick Vov1 = 0.15 V so ID1 = gm1 * Vov1 / 2 = 14 uA, tail = 28 uA, so tail_ratio = 1.4 at Ibias = 20 uA.
4. Square law: W1/L1 = gm1^2 / (2 Kn ID1) = 7.4, so W1 = 3.7 um at L = 0.5 um.
5. Second stage: put the non-dominant pole well above UGF, gm6 ~ 10 gm1 = 1.9 mS; with Vov6 = 0.2 V, I6 = 190 uA, so out_ratio = 9.5.
6. W6/L6 = gm6^2 / (2 Kp I6) = 158, so W6 = 79 um at L = 0.5 um.
7. Mirror load Vov3 = 0.2 V at 14 uA: W3/L3 = 11.7, so W3 = 5.8 um.
- **Result (simulated):** gain 74.2 dB, UGF 27.9 MHz (target 30), PM 67.8 deg, power 0.436 mW, all 8 devices saturated, Vout = 0.90 V. All targets met without adjusting any target. PM is at the upper end of the 50-70 window, which leaves room for actions to move it either way.
- The first attempt at an arbitrary sizing (40 um / 20 / 100 um) had PM 26 deg and UGF 85 MHz; the procedure above fixed it.

## D6. Action set
- 14 actions = x1.3 or /1.3 on cc, ibias, w_in, l_in, l_load, w_cs, out_ratio. Ids like `cc_up`, `cc_down` become the model's output vocabulary, so they must not change. Descriptions are factual and give no hint of the effect (a test enforces this). An action that clipping turns into a no-op is unavailable (`available_actions`).
- Knobs not in the action set (w_load, l_cs, l_bias, tail_ratio) stay fixed after the start state; this keeps the label space at 14 and the problem learnable.

## D7. Spec distance
- gain: shortfall_dB / 10; ugf and power: log10 ratio (decades), since they span orders of magnitude; pm: shortfall_deg / 15; +1.0 per unsaturated device; 10.0 when no complete metrics exist.
- So one unit is about "10 dB, one decade, 15 deg, one decade, or one broken device", which keeps terms comparable and the distance bounded and smooth, which is what ranking (Phase 2) and reward (Phase 4) need.
- **Observed concern (not changed):** in 500 random designs, 5th-percentile PM was -71 deg, which alone scores (50+71)/15 = 8.1, close to the 10.0 failure penalty. A spec-failing design can therefore score nearly as bad as a failed simulation. It is still ordered correctly, so I left the scales as specified. Revisit if Phase 2 rankings look dominated by such cases.
- Runs where AC metrics are missing (MEASUREMENT_MISSING) get 10.0 even though devices are known; simple and conservative.

## D8. Parallelism and speed
- `multiprocessing` spawn pool, `cpu_count - 1` workers, chunked. Measured on the M4 (9 workers): **~165-170 sims/s** uncached (500 random designs in ~3 s); ~890/s on a fully cached rerun (dominated by process-pool overhead). 60k simulations is roughly 6 minutes.
- Scripts that use `simulate_batch` need an `if __name__ == "__main__":` guard because of `spawn`.

## D9. Drive sync
- `rsync -av` without `--delete`, between the repo folder and the Drive for desktop folder. Manifest (names, sizes, rows) is written before each push; the Colab bootstrap notebook compares sizes against it to detect an unfinished upload.
- `.gitignore` uses `.simcache/` for the local cache; `CLAUDE.md` and `.env` are ignored.

# Phase 2 decisions

## D10. Targets, specs and start states
- **Targets:** each of the 11 knobs log-uniform in [nominal/3, nominal*3] clipped to bounds (realistic amplifiers, not the full bounds); kept if ok, all saturated, PM >= 50. Yield 600/1133 = 53%.
- **Spec from the target's own metrics with slack** (gain -U(0,3) dB, UGF x U(0.75,0.95), PM -U(0,10) clamped [45,70], power x U(1.05,1.3)). Values are rounded *toward slack* (floor for minimums, ceil for the power maximum) at 0.1 dB / 10 kHz / 0.1 deg / 1 uW so the prompt shows exactly the number used for scoring and the target still passes (asserted for every target).
- **Start states:** only the 7 action knobs move, by 1.3^k with k in [-3,3], total |k| in [2,6]. Rejection sampling also requires that **no perturbed knob hits a bound**; otherwise clipping would move the start off the lattice and the inverse moves would not recover the target (checked by a test that applies real inverse actions). Trade-off: starts are slightly biased away from the bounds.
- **Filter:** sim ran, spec_distance in (0, 5]. This answers the D7 concern: the farthest start is 4.14, and 3 of 3600 candidates were rejected as too far. 797 of 3600 candidates (22%) already met the spec because of the slack, so I sample 2x candidates per wanted start (3 per target). 42 starts short of 1800 because a few targets had too few failing candidates.
- **Duplicates:** states that converge to the same design inside one target are labeled once (first occurrence).

## D11. Labeling and the tie problem
- Every available action is simulated from each state (about 15 sims per labeled state, including the 1-in-N cost of the next state's children), `improvement = distance_before - distance_after`. Failed or unsaturated outcomes get their natural distance, so they rank last, not silently dropped.
- **Greedy trajectory:** after labeling a state, apply the best action if it improves and the result still fails the spec, up to 3 more steps. Later steps are the states an agent would actually see (step 0: 1758, 1: 1088, 2: 586, 3: 247).
- **Ties:** per the plan, ties break by action-id order (deterministic) and are recorded in `tied_best`. Observed: **27.5% of states have a tie, and 98% of those are several actions that each fully solve the spec** (all improvement = distance_before). The exact-id label is then arbitrary and biased toward early ids (cc_down and ibias_down are 35% and 27% of tied labels). Decision: **top-1 and top-3 are tie-aware** (a pick that matches the best improvement is correct; rank = 1 + number of strictly better actions), and `top1_exact` is reported next to it. Trade-off: the training label is still the lowest id among ties; this is a mild label-noise/bias source that Phase 3 should keep in mind (an option later is to choose among tied solvers at random or by largest margin).
- **One-step greedy label, not an optimal plan.** Cheap and exactly scoreable by lookup; it can disagree with the best 2-step plan.

## D12. Textbook-rules baseline (src/analogft/baselines.py)
Compute each normalized shortfall in the same units as the spec distance (`shortfall.py`, tested to sum to spec_distance), take the largest, apply one fixed move; if that move is unavailable (clipped), try the next-largest. Rules, each written before looking at any result:
- **PM low -> cc_up.** Raising Cc moves the dominant pole lower and splits the poles further, which is the standard first fix for phase margin.
- **UGF low -> w_in_up.** UGF is about gm1/(2 pi Cc), and gm1 grows with the input pair's W/L.
- **Gain low -> l_load_up.** Longer load devices raise their output resistance (lambda ~ 1/L in our models, D1), which raises stage-1 gain.
- **Power high -> ibias_down.** All branch currents scale with Ibias.
- **Unsaturated device** (a device counts 1.0, like one 10 dB of gain): M1, M2, M5 (pair and tail) -> w_in_up (more W/L means smaller Vgs1 and more tail headroom); M3, M4 (PMOS load) -> l_load_down (more W/L, smaller Vov); M6 -> w_cs_up (smaller Vov6); M7, M8 (NMOS mirror) -> ibias_down (smaller Vov). Devices are tried in name order.
- Deliberately simple: one rule per shortfall, no look-ahead, no knowledge of magnitudes or side effects. It is the bar a model must clear to show it learned more than a designer's first instinct.

## D13. Baseline scoring conventions (src/analogft/evaluation.py)
- An invalid or unavailable pick is a no-move: wrong for top-1/top-3/improve-rate and improvement 0 for regret (regret = best improvement - picked improvement). Alternative (penalize like the worst action) would make invalid outputs look even worse; no-move is the simplest meaningful rule and matches what an agent that ignores a bad output would do.
- **Random** is the exact expectation over each state's available actions, not a sample. **Majority** returns the most frequent train label and is invalid when that action is unavailable at a state.
- Regret is averaged over all states, including those where no action improves.

## D14. Prompt and response format (src/analogft/prompting.py)
- One user message holds spec, current metrics, failing specs with shortfalls, unsaturated devices only, knobs in engineering units (action knobs, then the 4 fixed knobs, since they affect gain and headroom) and the available actions with their neutral descriptions. System prompt carries the output contract. Median 258 tokens for the user message and 330 with the system prompt (4 chars per token), max 342, under the 350 target.
- Reply is one JSON line `{"action", "reason"}`. The reason is generated from data: largest normalized shortfall (spec value vs current) plus the simulated effect of the chosen action on that metric and on the other metric that moved the most (if it moved by at least 0.03 distance units). Longest observed: 16 words.
- Deviation from the plan's signature: `format_response(action, before, after, spec)` takes the spec as a fourth argument because "largest shortfall" is undefined without it.
- `parse_response` accepts a JSON object anywhere in the text (code fences, chatter) and requires a string `action` field. **Truncated or malformed JSON is invalid ("no_json")**, even if an action id is readable. Trade-off: stricter than needed for the agent but keeps "valid-output rate" a real measurement of format discipline.

## D15. Splits and files
- Split by target (group_id) 80/10/10 with a seeded permutation: 480/60/60 targets. All states and episodes of a target stay together; asserted in the build and tested.
- Pilot output goes to data/phase2_pilot/ (never pushed); the real dataset to data/phase2/. All settings live in configs/phase2.json (seed 0).
- Starts are simulated in one batch for all targets (an earlier version created a process pool per target, which was far slower).

# Phase 3 decisions

## D16. Tie-break for the training label: largest margin beyond the spec
- **Problem:** 27.5% of states have several equally good best actions (98% of them each fully solve the spec). The label was the lowest action id, which favors cc_down/ibias_down for no physical reason, and a model trained on it learns "when unsure, say ibias_down".
- **Options:** (a) keep id order; (b) random among ties; (c) the tied action whose resulting design has the largest margin beyond the spec; (d) drop tied states.
- **Chosen: (c), then id order if margins are also tied.** margin = min over the 4 specs of the normalized slack after the action, in the same units as spec_distance (gain dB/10, UGF and power in decades, PM deg/15; `shortfall.slack_terms`). It prefers a robust fix over one that squeaks over the line, like a designer would, and it is deterministic and computed from the stored `action_outcomes` (no new simulation). (b) would add noise; (d) would throw away the 27.5% of states where the model most needs to learn "any solving move is fine".
- **Applied by** `scripts/relabel_dataset.py` (checks: a label only changes among tied actions; every unchanged label regenerates a byte-identical assistant message). `dataset.label_nodes` uses the same rule for future builds. Ranking order, `tied_best`, `label_solves`, the assistant message and its reason are all regenerated.
- **Known limitation:** the later states of an episode (step 1-3) were reached by following the OLD greedy action. Their labels are valid for their own states; only the choice of which states exist reflects the old tie-break. Phase 4 samples fresh trajectories anyway.
- **Result:** 370 of 1012 tied states changed label. Tie-aware metrics did not change (as they should not); exact-id metrics did. Tie-aware scoring stays the headline metric. See the Step 0 table in the Phase 3 write-up.

## D17. Eval subset
- 150 of the 375 test examples, seeded (0), stratified by step_index with proportional allocation (largest remainder), ids in `results/phase3/eval_subset_ids.json`. Reason: the Groq free tier cannot score 375 reasoning-model calls per day, and all methods must be compared on the identical examples. Every method is scored on the subset AND the full test split (except Groq: subset only). Cost: wider CIs on the subset (n=150), reported.
- Groq examples run in a fixed shuffled order, so if a daily cap stopped a run early the scored examples would still be an unbiased sample.

## D18. Large-model baseline: openai/gpt-oss-120b (main), qwen/qwen3.8-27b (optional)
- The research question is whether a small specialist beats a large general model, so the baseline must be the strongest general open-weight model available on Groq. gpt-oss-120b is a reasoning model, production status on Groq and open-weight (reproducible). Run at its medium reasoning effort (not low), so it is not a strawman.
- Qwen3.8-27B (preview) is the same family as the small Qwen but ~50x larger and untrained on our data, so it isolates "size vs specialization". It was run in its default mode (no reasoning-effort parameter sent; it does not emit reasoning tokens in that mode).
- Fairness: identical SYSTEM_PROMPT + user message as the small models (`predict.build_messages`), temperature 0, only the final message `content` is parsed (reasoning is returned separately), `max_completion_tokens=2048` so reasoning cannot cut off the JSON; truncations are counted. Responses are cached on disk by (model, example id).
- Both model ids were confirmed present in the key's model list before any run.

## D19. Small model: Qwen2.5-0.5B/1.5B-Instruct instead of Qwen3-0.6B/1.7B (deviation from the original plan)
- Qwen3's chat template has a "thinking mode" (`<think>` blocks) that complicates both training targets and output parsing. Qwen2.5-Instruct has a plain, stable template, mature TRL/PEFT support, and fits a free T4. First run 0.5B, main run 1.5B if time allows.

## D20. Fine-tuning setup
- **LoRA** r=16, alpha=32, dropout 0.05 on all attention and MLP projections (q,k,v,o,gate,up,down). Why: the task is narrow (pick 1 of <=14 labels and a one-line reason), so a small adapter is enough; targeting all linear layers is the standard setting that matches full fine-tuning more closely than attention-only.
- **Optimization:** lr 2e-4 (typical for LoRA), cosine decay, 5% warmup, 2 epochs, effective batch 16, seed 0. 2926 train examples / 16 = 183 steps per epoch, 366 steps total. Log every 10 steps, evaluate on val every 50, checkpoint every 50.
- **fp16 mixed precision, not bf16:** the T4 (Turing) has no bf16. Base weights are loaded in fp16, LoRA weights are kept in fp32 by PEFT, and the Trainer uses fp16 autocast with loss scaling. fp16 can overflow, so before training one forward pass checks that the loss is finite; if not, it automatically reloads in fp32 (slower, 2x memory, still fits). A NaN in the logged training loss fails the run loudly.
- **Loss on the reply only:** prompt/completion dataset format with `completion_only_loss=True`. Verified by printing the tokens that carry loss for one example (exactly the JSON reply + `<|im_end|>`; the whole prompt is masked).
- **max_length 640, not 512 (deviation found by the smoke test):** the plan assumed 512 from the 4-chars-per-token estimate. Real Qwen token counts are prompt 428-502, reply 38-49, full conversation up to 550 tokens; with 512, 84% of examples (3104 of 3679) would have lost the end of the reply. `train()` now asserts that the longest example fits. Padding is per batch, so the larger limit costs nothing.
- **Generation:** greedy, max_new_tokens 64 (replies are at most 49 tokens), same chat template as training.
- **Compute plan:** resumable from `runs/phase3/<run>/checkpoints/` on Drive (save_total_limit 2). Checkpoints are kept separate from eval outputs so metrics can be pulled to the Mac without weights (`sync_drive.sh pull runs --metrics-only`).

## D21. Library versions
- Pinned in `requirements-colab.txt`: transformers 5.20.0, trl 1.16.0, peft 0.21.2, accelerate 1.15.0, datasets 5.1.0 (torch 2.14.1 locally; Colab keeps its own torch). Verified together by the local smoke test. API notes that cost time and are encoded in the code: transformers 5 renamed `torch_dtype` to `dtype` and replaced `warmup_ratio` by `warmup_steps` (a float below 1 is a ratio); TRL 1.x tokenizes inside the trainer and exposes `labels` with -100 on the prompt.
- Local note: the editable-install `.pth` file in `.venv/` repeatedly gets the macOS "hidden" flag, which makes Python 3.13+ ignore it (`chflags nohidden` fixes it). To not depend on it, `pyproject.toml` sets `pythonpath = ["src"]` for pytest and `sync_drive.sh` exports `PYTHONPATH`.

## D22. Statistics
- 95% CIs are percentile bootstrap intervals over states (2000 resamples, seed 0) of the per-state score, for tie-aware top-1, improvement rate and mean regret. For `random` the per-state score is its exact expectation. Methods are compared on the same states, so overlapping intervals are only a rough guide; a paired test would be tighter and is a possible follow-up.

### D18 observed results (Groq, 150-example eval subset)
- Limits read from response headers: 8,000 tokens/min and 1,000 requests/day per model (the 200K tokens/day figure is not exposed in headers; gpt-oss used ~159K, within it).
- gpt-oss-120b (medium effort): ~1060 tokens/example (498 prompt + 562 completion, of which ~520 reasoning), 1.6 s/call, 2 of 150 outputs truncated at 2048 tokens (reasoning ran out the budget, empty answer, scored invalid). ~45 minutes wall time because of the per-minute cap.
- qwen3.8-27b (default, no reasoning): ~541 tokens/example, 0 truncated, 100% valid.

## D23. Data travels through git; results come back as a zip (replaces the Drive-for-desktop route of D9)
- **Why:** the Drive for desktop app overheated the laptop, lost files and was uninstalled, so `data/phase2` could not be trusted to be on Drive. Git gives Colab an exact, versioned snapshot of the data, the same commit as the code that reads it.
- **Options:** (a) keep Drive for desktop; (b) upload data by hand in the Drive web UI; (c) commit the dataset to git; (d) Git LFS.
- **Chosen: (c).** Allowed in git: `data/phase2/*.jsonl`, `data/phase2/build_stats.json`, `data/samples/`, `data/manifest.json` (about 23 MB; train.jsonl is 16.8 MB, under GitHub's 50 MB warning). Everything else under data/ and runs/ stays ignored. `check_large_files.sh` keeps the 10 MB warning for every other file (50 MB for the allowed data files). Trade-offs: the repo grows by ~23 MB per dataset version (history keeps old versions, so relabel/rebuild commits should be rare), and the dataset is now public along with the code. It is simulator-generated, so nothing private is exposed.
- **Colab paths:** `DATA_DIR` is `<repo>/data` (the clone) everywhere; `RUNS_DIR` and `RESULTS_DIR` are on the mounted Drive on Colab (`STORAGE_ROOT`), which Colab writes to directly. `verify_manifest` now checks the clone's data. (`ANALOGFT_STORAGE_ROOT` still moves all three, for tests.)
- **Results back to the Mac:** the notebook's last cell writes `runs/phase3/<run>_results.zip` (eval/, logs/, figures/, config.json; no checkpoints or adapters; ~MBs) to Drive; the user downloads it in the browser and runs `scripts/import_results_zip.py`, which only accepts that layout (path-traversal safe, tested). Weights stay on Drive.
- **Drive for desktop is optional:** `DRIVE_LOCAL_DIR` is still honoured; `sync_drive.sh` prints the zip-route instructions instead of failing obscurely when the folder is missing.
