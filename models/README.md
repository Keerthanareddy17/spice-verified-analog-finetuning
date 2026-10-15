# Device models

No model files are stored here. The project uses SPICE **Level-1** MOSFET models generated in code
(`src/analogft/circuit/models.py`) with channel-length modulation lambda proportional to 1/L.

The intended source was the ASU Predictive Technology Model (PTM), 180 nm bulk BSIM card
(https://ptm.asu.edu). The site was unreachable when this was built, so no PTM card is included.
If you add one, cite the PTM paper (written from memory, since the site could not be opened to confirm the exact requested wording; verify before publishing): W. Zhao and Y. Cao, "New generation of predictive technology model
for sub-45nm early design exploration," IEEE Trans. Electron Devices, vol. 53, no. 11, pp. 2816-2823, Nov. 2006.
See docs/DECISIONS.md (D1).
