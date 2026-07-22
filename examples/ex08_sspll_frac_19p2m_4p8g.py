"""Example 8: DTC-assisted fractional-N sub-sampling PLL + ILCM timing cal.

Part 1 — fractional SSPLL, 19.2 MHz -> 4.806 GHz (N = 250.2503):
  The modern low-jitter synthesizer architecture: a 1st-order EFM feeds a
  10-bit/250 fs DTC that shifts the sampling instant so the reference edge
  always lands on a VCO zero crossing.  EFM1 (not MASH-2/3) because its
  residue spans exactly 1 UI = 208 ps — a practical DTC range; higher-order
  MASH spans 4-8 UI and saturates the DTC (config-enforced).
    * perfect DTC:        fractional operation is nearly free (~138 fs vs
                          ~135 fs integer-N)
    * 8% DTC gain error:  1.3 ps and a -34 dBc in-band fractional spur
    * + sign-sign LMS:    ~150 fs, spur < -80 dBc, gain -> 1/(1+eps) exactly

Part 2 — ILCM injection/FTL path offset calibration (250 MHz -> 12 GHz):
  A 3 ps FTL detector offset parks the FTL with a residual drift -> -32 dBc
  injection spur.  A second detector observing the injection's own phase
  jump sees the TRUE drift and bang-bang corrects the offset: spur -> -96 dBc.
"""
import os

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from pllsim.arch.cppll import FracConfig
from pllsim.arch.ilcm import ILCM, ILCMConfig
from pllsim.arch.sspll import SSPLL, SSPLLConfig
from pllsim.blocks.dtc import DTCConfig
from pllsim.blocks.loopfilter import FilterDesign
from pllsim.blocks.oscillator import OscConfig
from pllsim.blocks.sampler import SamplerConfig
from pllsim.calibration.lms import SignSignLMS
from pllsim.core.jitter import ldbc_from_sphi

OUT = os.path.join(os.path.dirname(__file__), "out")
os.makedirs(OUT, exist_ok=True)

# ---- Part 1: fractional SSPLL ----------------------------------------------
FREF, FRAC = 19.2e6, 0.2503
FOUT = (250 + FRAC) * FREF
BASE = dict(
    fref=FREF, fout=FOUT,
    osc=OscConfig(f0=4.755e9, gain=60e6, pn_dbchz=-122.0, pn_foffset=1e6,
                  pn_f1f3=3e5, pn_floor_dbchz=-155.0),
    sampler=SamplerConfig(amp_v=0.4, c_samp=60e-15, gm=1e-3,
                          pulse_width=150e-12, pedestal_v=1e-3),
    filt=FilterDesign(c1=680e-12, r2=20e3, c2=2.2e-12, r3=2e3, c3=1e-12),
    ref_pn_dbchz=-162.0, fll_i=1e-6, fll_engage=2e6, fll_release=400e3)
DTC = DTCConfig(t_res=250e-15, n_bits=10, jitter_rms_s=30e-15)
EPS = 0.08

print(f"fractional SSPLL: {FREF / 1e6} MHz -> {FOUT / 1e9:.6f} GHz (N = 250.2503)\n")
runs = []
for label, cal, err in [
        ("perfect DTC        ", None, 0.0),
        ("8% gain err, uncal ", None, EPS),
        ("8% err + LMS cal   ",
         SignSignLMS(init=1.0, mu=5e-6, gear_shift_n=60_000, mu_final=5e-7), EPS)]:
    cfg = SSPLLConfig(**BASE, frac=FracConfig(frac=FRAC, mash_order=1,
                                              dtc=DTC, dtc_cal=cal))
    sim = SSPLL(cfg).simulate(250_000, seed=2, dtc_gain_init_error=err)
    spur = {f"{k / 1e3:.0f}k": round(v, 1) for k, v in sim.spurs_fft.items()
            if not np.isnan(v)}
    gc = f"  gain_corr={cal.value:.4f} (ideal {1 / (1 + EPS):.4f})" if cal else ""
    print(f"{label}: jitter {sim.jitter_fs:7.1f} fs  spurs {spur}{gc}")
    runs.append((label.strip(), sim))

fig, ax = plt.subplots(figsize=(9.5, 5.5))
for (label, sim), col in zip(runs, ("C2", "C1", "C0")):
    ax.semilogx(sim.f_psd, ldbc_from_sphi(sim.s_phi_psd), lw=0.9, color=col,
                label=f"{label} ({sim.jitter_fs:.0f} fs)")
ax.set_xlabel("offset [Hz]")
ax.set_ylabel("L(f) [dBc/Hz]")
ax.set_title("Fractional-N SSPLL: DTC gain error and its calibration")
ax.grid(True, which="both", alpha=0.3)
ax.legend(fontsize=9)
fig.tight_layout()
fig.savefig(f"{OUT}/ex08_sspll_frac.png", dpi=140)

# ---- Part 2: ILCM injection/FTL offset calibration --------------------------
print("\nILCM FTL-path offset (250 MHz -> 12 GHz):")
IBASE = dict(
    fref=250e6, fout=12e9,
    osc=OscConfig(f0=12e9, gain=1.0, pn_dbchz=-105.0, pn_foffset=1e6,
                  pn_f1f3=5e5, pn_floor_dbchz=-145.0),
    beta=0.6, q_tank=8, i_ratio=0.15, inj_jitter_rms_s=15e-15,
    ref_pn_dbchz=-155.0, ftl_f_lsb=20e3)
s_off = ILCM(ILCMConfig(**IBASE, ftl_det_offset_s=3e-12)).simulate(
    150_000, seed=1, f_free_error=1e6, fine_oversample=4)
s_cal = ILCM(ILCMConfig(**IBASE, ftl_det_offset_s=3e-12, timing_cal=True,
                        timing_cal_step_s=20e-15)).simulate(
    150_000, seed=1, f_free_error=1e6, fine_oversample=4)
print(f"  3 ps offset, no cal: spur @ fref = {s_off.spurs_fft[250e6]:.1f} dBc")
print(f"  3 ps offset + cal  : spur @ fref = {s_cal.spurs_fft[250e6]:.1f} dBc, "
      f"correction -> {s_cal.cal_traces['inj_timing'][-1] * 1e12:+.2f} ps (target -3)")

fig, ax = plt.subplots(figsize=(8.5, 4))
tc = s_cal.cal_traces["inj_timing"]
ax.plot(s_cal.t[:tc.size] * 1e6, tc * 1e12, lw=0.9)
ax.axhline(-3, color="r", ls=":", lw=1, label="-offset")
ax.set_xlabel("time [µs]")
ax.set_ylabel("timing correction [ps]")
ax.set_title("ILCM injection/FTL path offset calibration "
             f"(spur {s_off.spurs_fft[250e6]:.0f} -> {s_cal.spurs_fft[250e6]:.0f} dBc)")
ax.grid(alpha=0.3)
ax.legend()
fig.tight_layout()
fig.savefig(f"{OUT}/ex08_ilcm_timing_cal.png", dpi=140)
print(f"\nplots saved to {OUT}/ex08_*.png")
