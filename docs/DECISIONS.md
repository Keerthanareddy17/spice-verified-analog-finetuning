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
