"""Example 4: Reference-sampling PLL, 100 MHz -> 8 GHz (N = 80).

The dual of the SSPLL: a divided VCO edge samples the reference sine, so the
PD gain is referred to REFERENCE phase and the sampler kT/C + gm noise are
multiplied by N to the output — with an identical front-end, the in-band
floor is ~20logN worse than a sub-sampling design.  The breakdown plot shows
sampler_ktc as the dominant in-band source; in ex03 it is negligible.
"""
import os

from pllsim.arch.spll import SPLL, SPLLConfig
from pllsim.blocks.loopfilter import FilterDesign
from pllsim.blocks.oscillator import OscConfig
from pllsim.blocks.sampler import SamplerConfig
from pllsim.plotting import plot_pn_breakdown, plot_transient

OUT = os.path.join(os.path.dirname(__file__), "out")
os.makedirs(OUT, exist_ok=True)

cfg = SPLLConfig(
    fref=100e6, fout=8e9,
    osc=OscConfig(f0=7.92e9, gain=80e6, pn_dbchz=-118.0, pn_foffset=1e6,
                  pn_f1f3=3e5, pn_floor_dbchz=-152.0),
    sampler=SamplerConfig(amp_v=0.4, c_samp=100e-15, gm=4e-3,
                          pulse_width=800e-12, pedestal_v=1e-3),
    filt=FilterDesign(c1=330e-12, r2=12e3, c2=2.2e-12, r3=1.5e3, c3=1e-12),
    ref_pn_dbchz=-160.0,
    fll_i=2e-6, fll_engage=3e6, fll_release=600e3,
)
pll = SPLL(cfg)
ar = pll.analyze()
print(pll.design_report(ar))

sim = pll.simulate(300_000, seed=1, f_start_offset=-30e6)
print(f"\nlock at {sim.lock_time_s * 1e6:.2f} us")
print(f"jitter (t-dom) = {sim.jitter_fs:.1f} fs vs linear {ar.jitter_fs:.1f} fs")

plot_pn_breakdown(ar, sim, save=f"{OUT}/ex04_pn_breakdown.png")
plot_transient(sim, save=f"{OUT}/ex04_transient.png", tmax=100e-6)
print(f"plots saved to {OUT}/ex04_*.png")
