"""Example 6: Injection-locked clock multiplier, 250 MHz -> 12 GHz (N = 48).

Demonstrates:
  * realignment-model phase noise: reference lowpass xN vs oscillator
    highpass with injection bandwidth ~ beta*fref/2pi (~36 MHz here)
  * lock range: inside the realignment bound the ILCM locks, outside it slips
    (Adler LC-tank cross-check printed alongside)
  * injection spur at fref offset vs free-running frequency error — the
    headline plot: why an ILCM lives or dies by its FTL
  * bang-bang FTL convergence from a 3 MHz free-running error
"""
import os

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from pllsim.arch.ilcm import ILCM, ILCMConfig, injection_spur_dbc
from pllsim.blocks.oscillator import OscConfig
from pllsim.plotting import plot_pn_breakdown

OUT = os.path.join(os.path.dirname(__file__), "out")
os.makedirs(OUT, exist_ok=True)

cfg = ILCMConfig(
    fref=250e6, fout=12e9,
    osc=OscConfig(f0=12e9, gain=1.0, pn_dbchz=-105.0, pn_foffset=1e6,
                  pn_f1f3=5e5, pn_floor_dbchz=-145.0),
    beta=0.6, q_tank=8, i_ratio=0.15,
    inj_jitter_rms_s=15e-15,
    ref_pn_dbchz=-155.0,
    ftl_f_lsb=20e3,
)
pll = ILCM(cfg)
ar = pll.analyze()
print(pll.design_report(ar))

# --- phase noise with FTL active -------------------------------------------
sim = pll.simulate(300_000, seed=1, f_free_error=3e6)
fc = sim.cal_traces["ftl_fcorr"]
print(f"\nFTL: 3 MHz initial free-running error corrected to "
      f"{(3e6 + fc[-1]) / 1e3:+.0f} kHz residual")
print(f"jitter (t-dom) = {sim.jitter_fs:.1f} fs vs linear {ar.jitter_fs:.1f} fs")
plot_pn_breakdown(ar, sim, save=f"{OUT}/ex06_pn_breakdown.png")

# --- injection spur vs frequency error (FTL off) ----------------------------
print("\nspur vs free-running frequency error (FTL off):")
ferrs = np.array([0.25e6, 0.5e6, 1e6, 2e6, 4e6, 8e6])
meas, theo = [], []
for fe in ferrs:
    s = pll.simulate(60_000, seed=2, f_free_error=fe, calibration=False,
                     fine_oversample=4)
    spur = s.spurs_fft.get(250e6, float("nan"))
    th = injection_spur_dbc(2 * np.pi * fe / cfg.fref, cfg.beta)
    meas.append(spur)
    theo.append(th)
    print(f"  ferr = {fe / 1e6:5.2f} MHz : spur(FFT) = {spur:6.1f} dBc, "
          f"analytic = {th:6.1f} dBc")

fig, ax = plt.subplots(figsize=(8, 5))
ax.semilogx(ferrs / 1e6, meas, "o-", label="time-domain FFT")
ax.semilogx(ferrs / 1e6, theo, "s--", label="sawtooth-ripple analytic")
ax.set_xlabel("free-running frequency error [MHz]")
ax.set_ylabel("injection spur @ fref offset [dBc]")
ax.set_title(f"ILCM {cfg.fout / 1e9:.0f} GHz: why the FTL matters "
             f"(lock range {cfg.lock_range_hz() / 1e6:.0f} MHz)")
ax.grid(True, which="both", alpha=0.3)
ax.legend()
fig.tight_layout()
fig.savefig(f"{OUT}/ex06_spur_vs_ferr.png", dpi=140)

# --- lock range demonstration ----------------------------------------------
print("\nlock range check (no FTL, no noise):")
for fe in (30e6, 100e6):
    s = pll.simulate(20_000, seed=0, f_free_error=fe, calibration=False,
                     noise=False)
    slips = s.extra["slips"]
    tag = "locked (no edge slips)" if slips == 0 else f"slipping ({slips} wraps)"
    print(f"  ferr = {fe / 1e6:5.0f} MHz "
          f"(bound {cfg.lock_range_hz() / 1e6:.0f} MHz): {tag}")

# --- FTL convergence --------------------------------------------------------
fig, ax = plt.subplots(figsize=(8, 4))
ax.plot(sim.t[:fc.size] * 1e6, (3e6 + fc) / 1e6, lw=0.8)
ax.set_xlabel("time [µs]")
ax.set_ylabel("residual free-running error [MHz]")
ax.set_title("Bang-bang FTL convergence")
ax.grid(alpha=0.3)
fig.tight_layout()
fig.savefig(f"{OUT}/ex06_ftl_convergence.png", dpi=140)
print(f"\nplots saved to {OUT}/ex06_*.png")
