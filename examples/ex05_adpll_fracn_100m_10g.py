"""Example 5: ADPLL, 100 MHz -> 10.0503 GHz (FCW = 100.503, fractional).

Part 1 — counter-assisted (TDC) ADPLL:
  * open-loop two-point KDCO FCAL (30% initial Kdco error)
  * TDC period-normalization calibration (5% TDC gain error)
  * PN breakdown vs time-domain periodogram, ~100 fs class

Part 2 — DTC + bang-bang fractional ADPLL:
  * MASH 1-1 + 12-bit DTC, sign-sign LMS DTC gain calibration
  * self-consistently linearized BBPD in analyze()

Part 3 — domain cross-check figure: both modes side by side, frequency-domain
linear model (total + per-source) overlaid with the time-domain periodogram.
TDC mode matches within ~0.3 dB band-averaged; the BB mode sits ~3 dB above
the model in-band — the expected accuracy limit of Gaussian BBPD
linearization against the deterministic MASH/DTC residual pattern (the
time-domain result is the reference for BB loops).
"""
import os

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from pllsim.arch.adpll import ADPLL, ADPLLConfig, DLFConfig
from pllsim.arch.cppll import FracConfig
from pllsim.blocks.dtc import DTCConfig
from pllsim.blocks.oscillator import OscConfig
from pllsim.blocks.tdc import TDCConfig
from pllsim.calibration.gain_cal import KdcoCal, TdcPeriodCal
from pllsim.calibration.lms import SignSignLMS
from pllsim.plotting import plot_cal_convergence, plot_pn_breakdown, plot_transient

OUT = os.path.join(os.path.dirname(__file__), "out")
os.makedirs(OUT, exist_ok=True)

FREF = 100e6
FCW = 100.503
FOUT = FCW * FREF
DCO = OscConfig(f0=10.0e9, gain=20e3, pn_dbchz=-112.0, pn_foffset=1e6,
                pn_f1f3=4e5, pn_floor_dbchz=-150.0)

# ---- Part 1: counter-assisted TDC ADPLL -----------------------------------
print("=== counter-assisted TDC ADPLL ===")
cfg1 = ADPLLConfig(
    fref=FREF, fout=FOUT, osc=DCO,
    dlf=DLFConfig(alpha=2**-4, rho=2**-11, iir_lambdas=(0.5,)),
    tdc=TDCConfig(t_res=0.5e-12, n_bits=8, gain_error=0.05),
    ref_pn_dbchz=-158.0,
    kdco_est_error=0.30,
)
pll1 = ADPLL(cfg1)
ar1 = pll1.analyze()
print(pll1.design_report(ar1))

kcal = KdcoCal(kdco_init=DCO.gain * 1.30, amp_lsb=8, meas_n=1024, rounds=4)
tcal = TdcPeriodCal(cpp_init=(1 / FOUT) / 0.5e-12)
sim1 = pll1.simulate(300_000, seed=1, kdco_cal=kcal, tdc_cal=tcal)
true_cpp = (1 / FOUT) / (0.5e-12 * 1.05)
print(f"KDCO FCAL:   {DCO.gain * 1.3:.0f} -> {kcal.value:.0f} Hz/LSB (true {DCO.gain:.0f})")
print(f"TDC cal:     codes/period -> {tcal.value:.2f} (true {true_cpp:.2f})")
print(f"jitter (t-dom) = {sim1.jitter_fs:.1f} fs vs linear {ar1.jitter_fs:.1f} fs")

plot_pn_breakdown(ar1, sim1, save=f"{OUT}/ex05_tdc_pn_breakdown.png")
plot_transient(sim1, save=f"{OUT}/ex05_tdc_transient.png", tmax=200e-6)
plot_cal_convergence(sim1, save=f"{OUT}/ex05_gain_cals.png")

# ---- Part 2: DTC + bang-bang fractional ADPLL -----------------------------
print("\n=== DTC + BBPD fractional ADPLL ===")
# gear shift before the PSD analysis window (last 75%) so the large-mu
# convergence wander does not contaminate the low-frequency periodogram
cal = SignSignLMS(init=1.0, mu=1e-5, gear_shift_n=60_000, mu_final=1e-6)
cfg2 = ADPLLConfig(
    fref=FREF, fout=FOUT, osc=DCO,
    dlf=DLFConfig(alpha=2.0, rho=2**-6),
    mode="dtc_bbpd",
    frac=FracConfig(frac=FCW - 100, mash_order=2,
                    dtc=DTCConfig(t_res=250e-15, n_bits=12, jitter_rms_s=50e-15),
                    dtc_cal=cal),
    bb_jitter_rms_s=200e-15,
    ref_pn_dbchz=-158.0,
)
pll2 = ADPLL(cfg2)
ar2 = pll2.analyze()
print(pll2.design_report(ar2))
sim2 = pll2.simulate(300_000, seed=3, dtc_gain_init_error=0.08)
print(f"DTC gain cal -> {cal.value:.4f} (ideal {1 / 1.08:.4f})")
print(f"jitter (t-dom) = {sim2.jitter_fs:.1f} fs vs linear {ar2.jitter_fs:.1f} fs "
      "(linear model is conservative for BB loops)")

plot_pn_breakdown(ar2, sim2, save=f"{OUT}/ex05_bb_pn_breakdown.png")

# ---- Part 3: frequency-domain vs time-domain overlay, both modes ----------
from pllsim.core.jitter import ldbc_from_sphi

# the FCAL corrected Kdco at runtime -> compare against the CALIBRATED model
ar1 = ADPLL(ADPLLConfig(**{**cfg1.__dict__, "kdco_est_error": 0.0})).analyze()

fig, axes = plt.subplots(1, 2, figsize=(13.5, 5.6), sharey=True)
for ax, ar, sim, title in [
        (axes[0], ar1, sim1,
         f"counter-assisted TDC mode\n(lin {ar1.jitter_fs:.0f} fs vs "
         f"sim {sim1.jitter_fs:.0f} fs)"),
        (axes[1], ar2, sim2,
         f"DTC + bang-bang mode\n(lin {ar2.jitter_fs:.0f} fs vs "
         f"sim {sim2.jitter_fs:.0f} fs)")]:
    ax.semilogx(sim.f_psd, ldbc_from_sphi(sim.s_phi_psd), color="0.6", lw=0.7,
                label="time-domain periodogram")
    for k in ar.pn_breakdown:
        if k != "total":
            ax.semilogx(ar.f, ldbc_from_sphi(ar.pn_breakdown[k]), lw=0.8,
                        alpha=0.8, label=k)
    ax.semilogx(ar.f, ldbc_from_sphi(ar.pn_breakdown["total"]), "k", lw=2.2,
                label="linear model total")
    ax.set_xlim(1e3, 5e7)
    ax.set_ylim(-160, -85)
    ax.set_xlabel("offset frequency [Hz]")
    ax.set_title(title, fontsize=10)
    ax.grid(True, which="both", alpha=0.3)
    ax.legend(fontsize=7, loc="lower left")
axes[0].set_ylabel("L(f) [dBc/Hz]")
fig.suptitle("ADPLL 100 MHz -> 10.0503 GHz: frequency-domain model vs "
             "time-domain simulation", fontsize=12)
fig.tight_layout()
fig.savefig(f"{OUT}/ex05_domain_comparison.png", dpi=150)

for tag, ar, sim in [("TDC", ar1, sim1), ("BB ", ar2, sim2)]:
    m = (sim.f_psd > 2e4) & (sim.f_psd < 2.5e7)
    fm, sm = sim.f_psd[m], sim.s_phi_psd[m]
    tgt = np.interp(np.log10(fm), np.log10(ar.f), ar.pn_breakdown["total"])
    edges = np.logspace(np.log10(2e4), np.log10(2.5e7), 7)
    errs = []
    for a, b in zip(edges[:-1], edges[1:]):
        mm = (fm >= a) & (fm < b)
        errs.append(f"{a / 1e6:.2f}-{b / 1e6:.2f}M: "
                    f"{10 * np.log10(np.mean(sm[mm]) / np.mean(tgt[mm])):+.1f} dB")
    print(f"domain match [{tag}]: " + " | ".join(errs))

print(f"\nplots saved to {OUT}/ex05_*.png")
