"""Example 9: Second-order impairments on the 19.2 MHz -> 4.8 GHz CPPLL.

  A. Kvco nonlinearity — loop metrics at the real operating point: a -5%/V
     compression at the top of the tuning range cuts Kvco 60 -> 35 MHz/V,
     UGB 0.95 -> 0.61 MHz; the time domain locks with the nonlinear law.
  B. Supply pushing — 50 MHz/V pushing + 5 mV / 3 MHz supply ripple:
     FM spur through |E(f)|, FFT vs narrowband-FM analytic within ~0.2 dB.
  C. Reference doubler duty-cycle error — every other edge early/late,
     square-wave phase modulation at fref/2; spur scales 20 dB/dec with the
     duty error (the CT |H| estimate at Nyquist is only ~7 dB accurate — the
     FFT is the reference there).
  D. Coarse band selection — 32-band VCO, binary search from the counter,
     5 trials to the correct band, then normal lock.
"""
import os

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from pllsim.arch.cppll import CPPLL, CPPLLConfig
from pllsim.blocks.chargepump import CPConfig
from pllsim.blocks.loopfilter import FilterDesign
from pllsim.blocks.oscillator import OscConfig

OUT = os.path.join(os.path.dirname(__file__), "out")
os.makedirs(OUT, exist_ok=True)

BASE = dict(fref=19.2e6, fout=4.8e9,
            cp=CPConfig(icp=1.5e-3, mismatch_pct=2.0, leakage_a=1e-9,
                        t_reset=200e-12),
            filt=FilterDesign(c1=680e-12, r2=20e3, c2=3.3e-12, r3=2e3,
                              c3=2.2e-12),
            ref_pn_dbchz=-162.0)
PN = dict(pn_dbchz=-122.0, pn_foffset=1e6, pn_f1f3=3e5, pn_floor_dbchz=-155.0)

# ---- A: Kvco nonlinearity ---------------------------------------------------
print("A. Kvco nonlinearity (operating-point-aware analyze):")
for nl1, lbl in [(0.0, "linear"), (-0.05, "-5%/V compression")]:
    osc = OscConfig(f0=4.6e9, gain=60e6, **PN, nl1=nl1)
    ar = CPPLL(CPPLLConfig(**BASE, osc=osc)).analyze()
    v = osc.v_for(4.8e9)
    print(f"  {lbl:18s}: v_op={v:.2f} V  Kvco={osc.kvco_at(v) / 1e6:5.1f} MHz/V  "
          f"UGB={ar.loop.f_ugb / 1e6:.3f} MHz  PM={ar.loop.pm_deg:.1f} deg  "
          f"jitter={ar.jitter_fs:.0f} fs")

# ---- B: supply pushing ------------------------------------------------------
print("\nB. supply pushing (50 MHz/V, 5 mV ripple):")
osc_p = OscConfig(f0=4.75e9, gain=60e6, **PN, pushing_hz_v=50e6)
pll_p = CPPLL(CPPLLConfig(**BASE, osc=osc_p))
ar_p = pll_p.analyze()
for f_rip in (0.3e6, 3e6):
    sim = pll_p.simulate(200_000, seed=1, supply_ripple=(5e-3, f_rip))
    e_fr = np.interp(np.log10(f_rip), np.log10(ar_p.f), np.abs(ar_p.ntfs["err"].h))
    beta = 50e6 * 5e-3 * e_fr / f_rip
    print(f"  ripple @ {f_rip / 1e6:4.1f} MHz: spur FFT = "
          f"{sim.spurs_fft.get(f_rip, float('nan')):6.1f} dBc,  "
          f"analytic = {20 * np.log10(beta / 2):6.1f} dBc "
          f"(|E| = {e_fr:.3f} loop suppression)")

# ---- C: reference doubler duty error ---------------------------------------
print("\nC. reference doubler duty-cycle error -> fref/2 spur:")
errs = [0.0005, 0.001, 0.002, 0.004]
spurs = []
for de in errs:
    osc = OscConfig(f0=4.75e9, gain=60e6, **PN)
    sim = CPPLL(CPPLLConfig(**BASE, osc=osc, ref_doubler_duty_err=de)) \
        .simulate(150_000, seed=1)
    s = sim.spurs_fft.get(9.6e6, float("nan"))
    spurs.append(s)
    print(f"  duty error {de * 100:.2f}%: spur @ 9.6 MHz = {s:.1f} dBc")
slope = (spurs[-1] - spurs[0]) / (20 * np.log10(errs[-1] / errs[0]))
print(f"  scaling: {slope:.2f} x 20 dB/dec (expect 1.00)")

fig, ax = plt.subplots(figsize=(7.5, 4.5))
ax.semilogx(np.array(errs) * 100, spurs, "o-")
ax.semilogx(np.array(errs) * 100,
            spurs[0] + 20 * np.log10(np.array(errs) / errs[0]), "k:",
            label="20 dB/dec")
ax.set_xlabel("doubler duty-cycle error [%]")
ax.set_ylabel("spur @ fref/2 [dBc]")
ax.set_title("Reference-doubler duty error spur (19.2 MHz doubled reference)")
ax.grid(True, which="both", alpha=0.3)
ax.legend()
fig.tight_layout()
fig.savefig(f"{OUT}/ex09_doubler_spur.png", dpi=140)

# ---- D: coarse band selection -----------------------------------------------
print("\nD. 32-band VCO coarse selection (binary search):")
osc_b = OscConfig(f0=4.6e9, gain=30e6, **PN, band_step_hz=150e6, n_bands=32)
sim_b = CPPLL(CPPLLConfig(**BASE, osc=osc_b)).simulate(80_000, seed=1)
trace = sim_b.cal_traces["band_select"].astype(int)
print(f"  trials {[int(x) for x in trace]} -> band {sim_b.extra['band']}, "
      f"lock at {sim_b.lock_time_s * 1e6:.1f} us, "
      f"final f-err {np.mean(sim_b.freq_out[-5000:]) - 4.8e9:+.0f} Hz")

fig, axes = plt.subplots(2, 1, figsize=(8.5, 6), sharex=False)
axes[0].step(range(len(trace)), trace, where="mid", marker="o")
axes[0].axhline(sim_b.extra["band"], color="r", ls=":", lw=1)
axes[0].set_xlabel("binary-search trial")
axes[0].set_ylabel("band index")
axes[0].set_title("Coarse band search")
axes[0].grid(alpha=0.3)
axes[1].plot(sim_b.t * 1e6, (sim_b.freq_out - 4.8e9) / 1e6, lw=0.8)
axes[1].set_xlabel("time [µs]")
axes[1].set_ylabel("freq error [MHz]")
axes[1].set_title("Fine lock after band selection")
axes[1].grid(alpha=0.3)
fig.tight_layout()
fig.savefig(f"{OUT}/ex09_band_select.png", dpi=140)
print(f"\nplots saved to {OUT}/ex09_*.png")
