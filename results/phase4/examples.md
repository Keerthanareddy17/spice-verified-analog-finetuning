# Example traces (after expert iteration + recovery)

Each step shows the state the model saw, what it answered, any recovery, the action applied and the simulated result.

## A success in which a recovery path fired

**Episode `t0261_s0`** - outcome: **solved** in 2 step(s), 2 simulations, reference path 6 moves, start distance 0.169075, final distance 0.0
Spec: gain >= 78.8 dB, UGF >= 6.96 MHz, PM >= 70.0 deg, power <= 0.269 mW

- **Step 1** state: gain 86.7 dB, UGF 7.85 MHz, PM 67.5 deg, power 0.134 mW; failing: pm; distance 0.169075
  - model said: `{"action": "cc_up", "reason": "PM 67.5 < 70 deg is the largest shortfall; cc_up: PM +4.0 deg, UGF -21%"}`
  - action **cc_up** -> simulated: gain 86.7 dB, UGF 6.13 MHz, PM 70.6 deg, power 0.134 mW; distance 0.169075 -> 0.055376 (improvement +0.114)
- **Step 2** state: gain 86.7 dB, UGF 6.13 MHz, PM 70.6 deg, power 0.134 mW; failing: ugf; distance 0.055376
  - model said: `{"action": "cc_down", "reason": "UGF 6.1 < 7.0 MHz is the largest shortfall; cc_down: UGF +29%, PM -1.9 deg"}`
  - action **ibias_up** -> simulated: gain 84.5 dB, UGF 6.97 MHz, PM 70.7 deg, power 0.173 mW; distance 0.055376 -> 0.0 (improvement +0.055)
  - failure detected: LOOP
  - recovery taken: **loop_block_reask** (cc_down)

## A failure

**Episode `t0157_s1`** - outcome: **budget_exhausted** in 8 step(s), 8 simulations, reference path 6 moves, start distance 0.656175, final distance 0.226887
Spec: gain >= 79.0 dB, UGF >= 16.72 MHz, PM >= 57.7 deg, power <= 0.477 mW

- **Step 1** state: gain 74.4 dB, UGF 15.64 MHz, PM 64.8 deg, power 0.705 mW; failing: gain, ugf, power; distance 0.656175
  - model said: `{"action": "ibias_down", "reason": "gain 74.4 < 79.0 dB is the largest shortfall; ibias_down: gain +2.3 dB, power -23%"}`
  - action **ibias_down** -> simulated: gain 76.7 dB, UGF 13.83 MHz, PM 64.6 deg, power 0.543 mW; distance 0.656175 -> 0.364844 (improvement +0.291)
- **Step 2** state: gain 76.7 dB, UGF 13.83 MHz, PM 64.6 deg, power 0.543 mW; failing: gain, ugf, power; distance 0.364844
  - model said: `{"action": "ibias_down", "reason": "gain 76.7 < 79.0 dB is the largest shortfall; ibias_down: gain +2.3 dB, power -23%"}`
  - action **ibias_down** -> simulated: gain 79.0 dB, UGF 12.21 MHz, PM 64.4 deg, power 0.418 mW; distance 0.364844 -> 0.136382 (improvement +0.228)
- **Step 3** state: gain 79.0 dB, UGF 12.21 MHz, PM 64.4 deg, power 0.418 mW; failing: ugf; distance 0.136382
  - model said: `{"action": "cc_down", "reason": "UGF 12.2 < 16.7 MHz is the largest shortfall; cc_down: UGF +29%, PM -3.4 deg"}`
  - action **cc_down** -> simulated: gain 79.0 dB, UGF 15.61 MHz, PM 60.7 deg, power 0.418 mW; distance 0.136382 -> 0.029779 (improvement +0.107)
- **Step 4** state: gain 79.0 dB, UGF 15.61 MHz, PM 60.7 deg, power 0.418 mW; failing: ugf; distance 0.029779
  - model said: `{"action": "cc_down", "reason": "UGF 15.6 < 16.7 MHz is the largest shortfall; cc_down: UGF +28%, PM -3.4 deg"}`
  - action **cc_down** -> simulated: gain 79.0 dB, UGF 19.77 MHz, PM 56.2 deg, power 0.418 mW; distance 0.029779 -> 0.099644 (improvement -0.070)
- **Step 5** state: gain 79.0 dB, UGF 19.77 MHz, PM 56.2 deg, power 0.418 mW; failing: pm; distance 0.099644
  - model said: `{"action": "cc_up", "reason": "PM 56.2 < 58 deg is the largest shortfall; cc_up: PM +5.5 deg, UGF -19%"}`
  - action **w_in_down** -> simulated: gain 77.9 dB, UGF 17.50 MHz, PM 60.0 deg, power 0.418 mW; distance 0.099644 -> 0.10808 (improvement -0.008)
  - failure detected: LOOP
  - recovery taken: **loop_block_reask** (cc_up)
- **Step 6** state: gain 77.9 dB, UGF 17.50 MHz, PM 60.0 deg, power 0.418 mW; failing: gain; distance 0.10808
  - model said: `{"action": "ibias_down", "reason": "gain 77.9 < 79.0 dB is the largest shortfall; ibias_down: gain +2.3 dB, power -23%"}`
  - action **ibias_down** -> simulated: gain 80.2 dB, UGF 15.44 MHz, PM 59.8 deg, power 0.322 mW; distance 0.10808 -> 0.03459 (improvement +0.073)
  - failure detected: NO_PROGRESS
  - recovery taken: **progress_rollback** (cc_down)
- **Step 7** state: gain 79.0 dB, UGF 15.61 MHz, PM 60.7 deg, power 0.418 mW; failing: ugf; distance 0.029779
  - model said: `{"action": "ibias_up", "reason": "UGF 15.6 < 16.7 MHz is the largest shortfall; ibias_up: UGF +13%, gain -2.3 dB"}`
  - action **ibias_up** -> simulated: gain 76.7 dB, UGF 17.68 MHz, PM 60.9 deg, power 0.543 mW; distance 0.029779 -> 0.282334 (improvement -0.253)
- **Step 8** state: gain 76.7 dB, UGF 17.68 MHz, PM 60.9 deg, power 0.543 mW; failing: gain, power; distance 0.282334
  - model said: `{"action": "ibias_down", "reason": "gain 76.7 < 79.0 dB is the largest shortfall; ibias_down: gain +2.3 dB, power -23%"}`
  - action **l_load_up** -> simulated: gain 77.3 dB, UGF 17.52 MHz, PM 59.7 deg, power 0.543 mW; distance 0.282334 -> 0.226887 (improvement +0.055)
  - failure detected: LOOP
  - failure detected: UNAVAILABLE_ACTION
  - recovery taken: **loop_block_reask** (ibias_down)
  - recovery taken: **fallback_rules** (l_load_up)
