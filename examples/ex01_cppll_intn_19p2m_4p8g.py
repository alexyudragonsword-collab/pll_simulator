"""Example 1: Integer-N charge-pump PLL, 19.2 MHz -> 4.8 GHz (N = 250).

Demonstrates: frequency-domain phase-noise breakdown, lock acquisition
transient, and the cross-domain check (time-domain periodogram vs linear
model).  Lands ~260 fs integrated jitter (1 kHz - 100 MHz): the classic CPPLL
noise floor set by N^2-multiplied CP/reference noise — compare ex03 (SSPLL,
same reference and VCO class) to see why sub-sampling wins at 12 GHz-class
in-band noise.
"""
import os

from pllsim.arch.cppll import CPPLL, CPPLLConfig
from pllsim.blocks.chargepump import CPConfig
from pllsim.blocks.loopfilter import FilterDesign
from pllsim.blocks.oscillator import OscConfig
from pllsim.plotting import plot_pn_breakdown, plot_transient

OUT = os.path.join(os.path.dirname(__file__), "out")
os.makedirs(OUT, exist_ok=True)

cfg = CPPLLConfig(
    fref=19.2e6,
    fout=4.8e9,
    # 4.8 GHz LC-VCO: -122 dBc/Hz @ 1 MHz, 300 kHz flicker corner
    osc=OscConfig(f0=4.75e9, gain=60e6, pn_dbchz=-122.0, pn_foffset=1e6,
                  pn_f1f3=3e5, pn_floor_dbchz=-155.0),
    cp=CPConfig(icp=1.5e-3, mismatch_pct=2.0, leakage_a=1e-9, t_reset=200e-12),
    filt=FilterDesign(c1=680e-12, r2=20e3, c2=3.3e-12, r3=2e3, c3=2.2e-12),
    ref_pn_dbchz=-162.0,   # clean crystal + buffer
    ref_pn_fc=20e3,
)

pll = CPPLL(cfg)
ar = pll.analyze()
print(pll.design_report(ar))

print("\nrunning time-domain simulation (lock from -30 MHz offset + noise)...")
sim = pll.simulate(400_000, seed=1, f_start_offset=-30e6)
print(f"lock time      = {sim.lock_time_s * 1e6:.2f} us")
print(f"jitter (t-dom) = {sim.jitter_fs:.1f} fs   vs linear model {ar.jitter_fs:.1f} fs")

plot_pn_breakdown(ar, sim, save=f"{OUT}/ex01_pn_breakdown.png")
plot_transient(sim, save=f"{OUT}/ex01_transient.png", tmax=60e-6)
print(f"plots saved to {OUT}/ex01_*.png")
