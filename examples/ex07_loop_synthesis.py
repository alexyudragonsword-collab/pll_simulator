"""Example 7: Loop synthesis and jitter-vs-bandwidth optimization.

The classic PLL design question — what bandwidth minimizes integrated
jitter — answered by machine: design_cp_filter() synthesizes a 3rd-order
passive filter for every UGB target (numerically, against the real network
including C3 loading), sweep_bandwidth() integrates the per-source jitter
breakdown, and the crossover between the N-multiplied in-band sources
(reference/CP, rising with BW... falling) and the VCO (falling with BW)
appears as the U-shaped optimum.

Also synthesizes ADPLL PI coefficients on the exact z-domain loop.
"""
import os

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from pllsim.arch.cppll import CPPLL, CPPLLConfig
from pllsim.blocks.chargepump import CPConfig
from pllsim.blocks.oscillator import OscConfig
from pllsim.synth import (cppll_kdet, design_adpll_dlf, design_cp_filter,
                          sweep_bandwidth)

OUT = os.path.join(os.path.dirname(__file__), "out")
os.makedirs(OUT, exist_ok=True)

FREF, FOUT, N = 19.2e6, 4.8e9, 250
OSC = OscConfig(f0=4.75e9, gain=60e6, pn_dbchz=-122.0, pn_foffset=1e6,
                pn_f1f3=3e5, pn_floor_dbchz=-155.0)
CP = CPConfig(icp=1.5e-3, mismatch_pct=2.0, leakage_a=1e-9, t_reset=200e-12)
PM = 58.0


def make_pll(f_ugb):
    filt = design_cp_filter(cppll_kdet(CP.icp, N), OSC.gain, f_ugb, PM, FREF)
    return CPPLL(CPPLLConfig(fref=FREF, fout=FOUT, osc=OSC, cp=CP, filt=filt,
                             ref_pn_dbchz=-162.0))


print("sweeping CPPLL loop bandwidth (each point = full filter synthesis)...")
bws = np.logspace(np.log10(0.15e6), np.log10(2.3e6), 15)
sw = sweep_bandwidth(make_pll, bws)
i_opt = int(np.argmin(sw["jitter_fs"]))
print(f"optimum UGB = {sw['f_ugb'][i_opt] / 1e6:.2f} MHz -> "
      f"{sw['jitter_fs'][i_opt]:.1f} fs (PM held at {PM:.0f} deg by synthesis)")

fig, ax = plt.subplots(figsize=(8.5, 5.5))
ax.loglog(sw["f_ugb"] / 1e6, sw["jitter_fs"], "ko-", lw=1.8, label="total")
for name, arr in sw["sources"].items():
    ax.loglog(sw["f_ugb"] / 1e6, arr, "--", lw=1, alpha=0.8, label=name)
ax.axvline(sw["f_ugb"][i_opt] / 1e6, color="r", ls=":", lw=1)
ax.annotate(f"optimum {sw['f_ugb'][i_opt] / 1e6:.2f} MHz\n"
            f"{sw['jitter_fs'][i_opt]:.0f} fs",
            (sw["f_ugb"][i_opt] / 1e6, sw["jitter_fs"][i_opt]),
            textcoords="offset points", xytext=(10, 18), color="r", fontsize=9)
ax.set_xlabel("loop UGB [MHz]")
ax.set_ylabel("integrated jitter [fs] (1 kHz - 100 MHz)")
ax.set_title(f"CPPLL {FREF / 1e6:.1f} MHz -> {FOUT / 1e9:.1f} GHz: "
             f"jitter vs bandwidth, PM = {PM:.0f} deg enforced")
ax.grid(True, which="both", alpha=0.3)
ax.legend(fontsize=8)
fig.tight_layout()
fig.savefig(f"{OUT}/ex07_jitter_vs_bw.png", dpi=140)

# ---- ADPLL PI synthesis on the exact z-domain loop -------------------------
print("\nADPLL DLF synthesis (exact z-domain, incl. update delay):")
for bw, pm in [(0.8e6, 60), (1.5e6, 60), (3e6, 55)]:
    a, r = design_adpll_dlf(100e6, bw, pm, iir_lambdas=(0.5,))
    print(f"  target {bw / 1e6:.1f} MHz / {pm} deg -> "
          f"alpha = {a:.5f} (~2^{np.log2(a):.1f}), rho = {r:.2e} (~2^{np.log2(r):.1f})")

print(f"\nplot saved to {OUT}/ex07_jitter_vs_bw.png")
