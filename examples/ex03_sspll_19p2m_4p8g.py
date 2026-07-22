"""Example 3: Sub-sampling PLL, 19.2 MHz -> 4.8 GHz (N = 250).

Same reference and VCO class as ex01 (integer-N CPPLL) — the point of this
example is the head-to-head: the SSPLL's PD gain is referred to OUTPUT phase,
so charge-pump/loop-filter noise is not multiplied by N^2, and the in-band
floor drops accordingly (~160 fs vs ~260 fs with identical building blocks).

Also demonstrated: the SSPD alone cannot acquire (false-locks at any integer
multiple of fref — here it parks 19.2 MHz off at N=249) and the counter-based
FLL acquires, hands off with hysteresis, then stays quiet.
"""
import os

import numpy as np

from pllsim.arch.sspll import SSPLL, SSPLLConfig
from pllsim.blocks.loopfilter import FilterDesign
from pllsim.blocks.oscillator import OscConfig
from pllsim.blocks.sampler import SamplerConfig
from pllsim.plotting import plot_pn_breakdown, plot_transient

OUT = os.path.join(os.path.dirname(__file__), "out")
os.makedirs(OUT, exist_ok=True)

cfg = SSPLLConfig(
    fref=19.2e6, fout=4.8e9,
    osc=OscConfig(f0=4.75e9, gain=60e6, pn_dbchz=-122.0, pn_foffset=1e6,
                  pn_f1f3=3e5, pn_floor_dbchz=-155.0),
    sampler=SamplerConfig(amp_v=0.4, c_samp=60e-15, gm=1e-3,
                          pulse_width=150e-12, pedestal_v=1e-3),
    filt=FilterDesign(c1=680e-12, r2=20e3, c2=2.2e-12, r3=2e3, c3=1e-12),
    ref_pn_dbchz=-162.0,
    fll_i=1e-6, fll_engage=2e6, fll_release=400e3,
)
pll = SSPLL(cfg)
ar = pll.analyze()
print(pll.design_report(ar))

print("\nacquisition from -25 MHz with FLL...")
sim = pll.simulate(400_000, seed=1, f_start_offset=-25e6)
eng = sim.cal_traces["fll_engaged"]
handoff = np.where(np.diff(eng) < 0)[0]
print(f"FLL handoff at {handoff[0] / cfg.fref * 1e6:.1f} us, "
      f"lock at {sim.lock_time_s * 1e6:.1f} us")
print(f"jitter (t-dom) = {sim.jitter_fs:.1f} fs vs linear {ar.jitter_fs:.1f} fs")

print("\nsame start WITHOUT FLL (expected: false lock one fref away)...")
sim_nofll = pll.simulate(60_000, seed=1, f_start_offset=-25e6, fll_enable=False)
ferr = float(np.mean(sim_nofll.freq_out[-5000:]) - cfg.fout)
print(f"parked at {ferr / 1e6:+.2f} MHz from target (= {ferr / cfg.fref:+.1f} x fref)")

plot_pn_breakdown(ar, sim, save=f"{OUT}/ex03_pn_breakdown.png")
plot_transient(sim, save=f"{OUT}/ex03_transient.png")
print(f"\nplots saved to {OUT}/ex03_*.png")
