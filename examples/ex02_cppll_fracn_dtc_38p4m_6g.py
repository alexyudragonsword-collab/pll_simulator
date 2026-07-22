"""Example 2: Fractional-N CPPLL with DTC quantization-noise cancellation.

38.4 MHz -> 6.0033 GHz  (N = 156.2525, MASH 1-1, 12-bit / 250 fs DTC).

Four experiments:
  A  no DTC              - raw MASH quantization noise through the loop
  B  DTC, 10% gain error - uncalibrated cancellation leaks DSM noise
  C  DTC + sign-sign LMS - gain converges to 1/(1+eps), jitter recovers
  D  DTC with sinusoidal INL, piecewise-LUT calibration on top of C

Generates: PN/spur spectra comparison, LMS convergence trace.
"""
import os

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from pllsim.arch.cppll import CPPLL, CPPLLConfig, FracConfig
from pllsim.blocks.chargepump import CPConfig
from pllsim.blocks.dtc import DTCConfig
from pllsim.blocks.loopfilter import FilterDesign
from pllsim.blocks.oscillator import OscConfig
from pllsim.calibration.lms import LUTCal, SignSignLMS
from pllsim.core.jitter import ldbc_from_sphi
from pllsim.plotting import plot_cal_convergence

OUT = os.path.join(os.path.dirname(__file__), "out")
os.makedirs(OUT, exist_ok=True)

FREF = 38.4e6
FOUT = (156 + 0.2525) * FREF

BASE = dict(
    fref=FREF, fout=FOUT,
    osc=OscConfig(f0=5.95e9, gain=80e6, pn_dbchz=-120.0, pn_foffset=1e6,
                  pn_f1f3=3e5, pn_floor_dbchz=-152.0),
    cp=CPConfig(icp=1.5e-3, mismatch_pct=1.0, leakage_a=1e-9, t_reset=150e-12),
    filt=FilterDesign(c1=470e-12, r2=15e3, c2=3.3e-12, r3=1.5e3, c3=2.2e-12),
    ref_pn_dbchz=-160.0,
)
DTC = dict(t_res=250e-15, n_bits=12, jitter_rms_s=30e-15)
GAIN_ERR = 0.10
N_CYC = 300_000


def run(tag, frac_cfg, **sim_kw):
    pll = CPPLL(CPPLLConfig(**BASE, frac=frac_cfg))
    sim = pll.simulate(N_CYC, seed=2, **sim_kw)
    spur = {f"{k / 1e6:.3f}M": round(v, 1) for k, v in sim.spurs_fft.items()}
    print(f"{tag}: jitter = {sim.jitter_fs:7.1f} fs   spurs [dBc] = {spur}")
    return sim


print(f"fref={FREF / 1e6} MHz  fout={FOUT / 1e9:.6f} GHz  N=156.2525\n")

simA = run("A  no DTC          ", FracConfig(frac=0.2525, mash_order=2))
simB = run("B  DTC eps=10% nocal", FracConfig(frac=0.2525, mash_order=2,
                                              dtc=DTCConfig(**DTC)),
           dtc_gain_init_error=GAIN_ERR)

calC = SignSignLMS(init=1.0, mu=5e-6, gear_shift_n=100_000, mu_final=5e-7)
simC = run("C  DTC + LMS gaincal", FracConfig(frac=0.2525, mash_order=2,
                                              dtc=DTCConfig(**DTC), dtc_cal=calC),
           dtc_gain_init_error=GAIN_ERR)
print(f"   gain_corr converged to {calC.value:.4f} (ideal {1 / (1 + GAIN_ERR):.4f})")

calD = SignSignLMS(init=1.0, mu=5e-6, gear_shift_n=100_000, mu_final=5e-7)
lutD = LUTCal(k=32, lo=-2.0, hi=2.0, mu=1e-16)
simD_off = run("D0 INL 2ps, no LUT  ",
               FracConfig(frac=0.2525, mash_order=2,
                          dtc=DTCConfig(**DTC, inl_sin=(2e-12, 3.0, 0.7)),
                          dtc_cal=SignSignLMS(init=1.0, mu=5e-6,
                                              gear_shift_n=100_000, mu_final=5e-7)),
               dtc_gain_init_error=0.02)
simD = run("D1 INL 2ps + LUT cal",
           FracConfig(frac=0.2525, mash_order=2,
                      dtc=DTCConfig(**DTC, inl_sin=(2e-12, 3.0, 0.7)),
                      dtc_cal=calD, dtc_lut_cal=lutD),
           dtc_gain_init_error=0.02)

# ---- plots ----------------------------------------------------------------
fig, ax = plt.subplots(figsize=(9.5, 6))
for sim, lab, col in [(simA, "A: no DTC", "C3"),
                      (simB, "B: DTC 10% gain err, uncal", "C1"),
                      (simC, "C: DTC + LMS gain cal", "C0")]:
    ax.semilogx(sim.f_psd, ldbc_from_sphi(sim.s_phi_psd), lw=0.9, color=col,
                label=f"{lab} ({sim.jitter_fs:.0f} fs)")
ax.set_xlabel("offset [Hz]")
ax.set_ylabel("L(f) [dBc/Hz]")
ax.set_title("Fractional-N CPPLL: DSM noise cancellation by DTC")
ax.grid(True, which="both", alpha=0.3)
ax.legend(fontsize=9)
fig.tight_layout()
fig.savefig(f"{OUT}/ex02_dtc_comparison.png", dpi=140)

simC.cal_traces["dtc_gain"] = np.asarray(calC.trace)
plot_cal_convergence(simC, save=f"{OUT}/ex02_lms_convergence.png")

fig, ax = plt.subplots(figsize=(9.5, 5))
for sim, lab, col in [(simD_off, "INL 2 ps, LUT off", "C1"),
                      (simD, "INL 2 ps, LUT on", "C0")]:
    ax.semilogx(sim.f_psd, ldbc_from_sphi(sim.s_phi_psd), lw=0.9, color=col,
                label=f"{lab} ({sim.jitter_fs:.0f} fs)")
ax.set_xlabel("offset [Hz]")
ax.set_ylabel("L(f) [dBc/Hz]")
ax.set_title("DTC INL: piecewise-LUT calibration")
ax.grid(True, which="both", alpha=0.3)
ax.legend(fontsize=9)
fig.tight_layout()
fig.savefig(f"{OUT}/ex02_lut_cal.png", dpi=140)

print(f"\nplots saved to {OUT}/ex02_*.png")
