# Example traces (textbook rules + recovery)

Each step shows the state the model saw, what it answered, any recovery, the action applied and the simulated result.

## A failure

**Episode `t0002_s0`** - outcome: **gave_up** in 8 step(s), 7 simulations, reference path 5 moves, start distance 0.370752, final distance 0.203076
Spec: gain >= 78.6 dB, UGF >= 12.45 MHz, PM >= 70.0 deg, power <= 0.659 mW

- **Step 1** state: gain 76.2 dB, UGF 15.58 MHz, PM 68.1 deg, power 0.556 mW; failing: gain, pm; distance 0.370752
  - model said: `(rules policy, no text)`
  - action **l_load_up** -> simulated: gain 77.6 dB, UGF 15.56 MHz, PM 67.7 deg, power 0.556 mW; distance 0.370752 -> 0.251531 (improvement +0.119)
- **Step 2** state: gain 77.6 dB, UGF 15.56 MHz, PM 67.7 deg, power 0.556 mW; failing: gain, pm; distance 0.251531
  - model said: `(rules policy, no text)`
  - action **cc_up** -> simulated: gain 77.6 dB, UGF 12.14 MHz, PM 70.2 deg, power 0.556 mW; distance 0.251531 -> 0.107454 (improvement +0.144)
- **Step 3** state: gain 77.6 dB, UGF 12.14 MHz, PM 70.2 deg, power 0.556 mW; failing: gain, ugf; distance 0.107454
  - model said: `(rules policy, no text)`
  - action **l_load_up** -> simulated: gain 79.0 dB, UGF 12.12 MHz, PM 69.7 deg, power 0.556 mW; distance 0.107454 -> 0.028892 (improvement +0.079)
- **Step 4** state: gain 79.0 dB, UGF 12.12 MHz, PM 69.7 deg, power 0.556 mW; failing: ugf, pm; distance 0.028892
  - model said: `(rules policy, no text)`
  - action **cc_up** -> simulated: gain 79.0 dB, UGF 9.41 MHz, PM 71.9 deg, power 0.556 mW; distance 0.028892 -> 0.121435 (improvement -0.093)
- **Step 5** state: gain 79.0 dB, UGF 9.41 MHz, PM 71.9 deg, power 0.556 mW; failing: ugf; distance 0.121435
  - model said: `(rules policy, no text)`
  - action **w_in_up** -> simulated: gain 80.1 dB, UGF 10.74 MHz, PM 69.4 deg, power 0.556 mW; distance 0.121435 -> 0.104134 (improvement +0.017)
- **Step 6** state: gain 80.1 dB, UGF 10.74 MHz, PM 69.4 deg, power 0.556 mW; failing: ugf, pm; distance 0.104134
  - model said: `(rules policy, no text)`
  - action **w_in_up** -> simulated: gain 81.3 dB, UGF 12.25 MHz, PM 66.5 deg, power 0.556 mW; distance 0.104134 -> 0.242242 (improvement -0.138)
  - failure detected: NO_PROGRESS
  - recovery taken: **progress_rollback** (cc_up)
- **Step 7** state: gain 79.0 dB, UGF 12.12 MHz, PM 69.7 deg, power 0.556 mW; failing: ugf, pm; distance 0.028892
  - model said: `(rules policy, no text)`
  - action **w_in_up** -> simulated: gain 80.1 dB, UGF 13.79 MHz, PM 67.0 deg, power 0.556 mW; distance 0.028892 -> 0.203076 (improvement -0.174)
- **Step 8** state: gain 80.1 dB, UGF 13.79 MHz, PM 67.0 deg, power 0.556 mW; failing: pm; distance 0.203076
  - model said: `(rules policy, no text)`
  - no usable action: step wasted
  - failure detected: LOOP
  - failure detected: INVALID_OUTPUT
  - recovery taken: **loop_block_reask** (cc_up)
  - recovery taken: **fallback_rules** (none)
