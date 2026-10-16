# Device models

No model files are stored here. The project uses SPICE Level-1 MOSFET models generated in code
(`src/analogft/circuit/models.py`) with channel-length modulation lambda proportional to 1/L.

The intended source was the ASU Predictive Technology Model (PTM) 180 nm bulk BSIM card (https://ptm.asu.edu),
which was unreachable at build time, so no PTM card is included. A PTM-based extension should cite:
W. Zhao and Y. Cao, "New generation of predictive technology model for sub-45nm early design exploration,"
IEEE Trans. Electron Devices, vol. 53, no. 11, pp. 2816-2823, Nov. 2006.
See `docs/DECISIONS.md` (D1).
