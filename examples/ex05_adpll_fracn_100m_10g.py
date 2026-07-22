"""Example 5: ADPLL, 100 MHz -> 10.0503 GHz (FCW = 100.503, fractional).

Part 1 — counter-assisted (TDC) ADPLL:
  * open-loop two-point KDCO FCAL (30% initial Kdco error)
  * TDC period-normalization calibration (5% TDC gain error)
  * PN breakdown vs time-domain periodogram, ~100 fs class

Part 2 — DTC + bang-bang fractional ADPLL:
  * MASH 1-1 + 12-bit DTC, sign-sign LMS DTC gain calibration
  * self-consistently linearized BBPD in analyze()
"""
import os

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
cal = SignSignLMS(init=1.0, mu=1e-5, gear_shift_n=100_000, mu_final=1e-6)
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
print(f"\nplots saved to {OUT}/ex05_*.png")
