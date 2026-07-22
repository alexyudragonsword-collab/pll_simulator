"""Example 12: Multiplying DLL vs injection-locked clock multiplier.

150 MHz -> 2.4 GHz (N = 16) from the SAME mediocre ring oscillator
(-100 dBc/Hz @ 1 MHz free-running).  The architectural question: how much of
the ring's noise can each technique remove?

  ILCM (beta = 0.6):  each injection pulls the phase 60% toward the
                      reference -> oscillator highpass corner ~ beta*fref/2pi
  MDLL (beta -> 1):   each select REPLACES the edge -> accumulated jitter is
                      reset every Tref, corner ~ fref/pi, and the ring noise
                      that survives is only the intra-period accumulation

Same digital tuning story on both (residual frequency error -> fref spur).

A nuance this example surfaced: the MDLL passes reference+mux noise FLAT to
Nyquist (x N, ZOH-shaped) while the ILCM lowpasses it at ~beta*fref/2pi.
With a quiet ring and an ordinary reference the ILCM can actually win; the
MDLL's advantage materializes when the ring is the dominant noise source —
which is exactly the cheap-ring use case MDLLs exist for (-95 dBc/Hz @ 1 MHz
here).
"""
import os

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from pllsim.arch.ilcm import ILCM, ILCMConfig
from pllsim.arch.mdll import MDLL, MDLLConfig
from pllsim.blocks.oscillator import OscConfig
from pllsim.core.jitter import ldbc_from_sphi

OUT = os.path.join(os.path.dirname(__file__), "out")
os.makedirs(OUT, exist_ok=True)

RING = OscConfig(f0=2.4e9, gain=100e3, pn_dbchz=-95.0, pn_foffset=1e6,
                 pn_f1f3=8e5, pn_floor_dbchz=-140.0)

mdll = MDLL(MDLLConfig(fref=150e6, fout=2.4e9, osc=RING,
                       mux_jitter_rms_s=40e-15, ref_pn_dbchz=-160.0))


def make_ilcm(beta):
    return ILCM(ILCMConfig(fref=150e6, fout=2.4e9, osc=RING, beta=beta,
                           inj_jitter_rms_s=40e-15, ref_pn_dbchz=-160.0,
                           ftl_f_lsb=20e3))


ar_m = mdll.analyze()
print("=== MDLL ===")
print(mdll.design_report(ar_m))

sim_m = mdll.simulate(250_000, seed=1, f_free_error=2e6)
rows = [("MDLL (beta->1)", ar_m, sim_m, "C0")]
for beta, col in [(0.6, "C1"), (0.2, "C3")]:
    pll = make_ilcm(beta)
    ar = pll.analyze()
    sim = pll.simulate(250_000, seed=1, f_free_error=2e6, fine_oversample=4)
    rows.append((f"ILCM beta={beta}", ar, sim, col))

print(f"\n{'architecture':18s}{'linear [fs]':>12s}{'time-dom [fs]':>14s}")
for name, ar, sim, _ in rows:
    print(f"{name:18s}{ar.jitter_fs:12.1f}{sim.jitter_fs:14.1f}")
print("\nedge replacement is the beta->1 limit: against strong injection "
      "(beta=0.6)\nthe MDLL's margin is small, but it grows ~20logN((1-b)/b) "
      "as injection weakens.")

fig, ax = plt.subplots(figsize=(9.5, 6))
ax.semilogx(ar_m.f, ldbc_from_sphi(RING.leeson().psd(ar_m.f)), "k:", lw=1,
            label="ring free-running")
for name, ar, sim, col in rows:
    key = "ring" if "MDLL" in name else "osc"
    ax.semilogx(ar.f, ldbc_from_sphi(ar.pn_breakdown[key]), col + "--", lw=0.9)
    ax.semilogx(ar.f, ldbc_from_sphi(ar.pn_breakdown["total"]), col, lw=1.8,
                label=f"{name} total ({sim.jitter_fs:.0f} fs sim)")
ax.set_xlim(1e4, 5e8)
ax.set_ylim(-165, -80)
ax.set_xlabel("offset [Hz]")
ax.set_ylabel("L(f) [dBc/Hz]")
ax.set_title("MDLL vs ILCM on the same -95 dBc/Hz ring "
             "(dashed: ring contribution)")
ax.grid(True, which="both", alpha=0.3)
ax.legend(fontsize=9)
fig.tight_layout()
fig.savefig(f"{OUT}/ex12_mdll_vs_ilcm.png", dpi=140)
print(f"\nplot saved to {OUT}/ex12_mdll_vs_ilcm.png")
