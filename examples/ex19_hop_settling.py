"""Example 19: channel-hop settling — the OTHER hard spec besides jitter.

A synthesizer that hops channels is judged on how fast it is *usable*
again: cellular budgets are ~10 us class for digital loops, tens of us
for analog ones.  pllsim.settling measures both settling instants from
the behavioral trajectory (frequency pull-in with a counter-style
detector whose tolerance floors at the loop's own frequency wander, and
phase settling as the last excursion beyond 50 mrad), plus the FLL
segment for sampling loops.

Four stories:
1. architecture comparison at a comparable hop
2. hop-size scaling on the sampling PLL: the FLL slew (i_fll into C1)
   is the bottleneck — settle time is linear in hop size, and i_fll is
   the knob (x4 current -> ~x4 faster acquisition segment)
3. what the phases are made of: FLL slew -> PD handoff -> phase decay
4. settling is a YIELD quantity: 20-seed distribution, p50/p95/worst
"""
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from pllsim import presets
from pllsim.settling import hop_settling, hop_statistics

OUT = os.path.join(os.path.dirname(__file__), "out")
os.makedirs(OUT, exist_ok=True)

# ------------------------------------------------ 1. architecture compare
print("=== 1. architecture comparison ===")
print(f"{'architecture':26s}{'hop':>8s}{'t_freq':>10s}{'t_phase':>10s}"
      f"{'FLL seg':>10s}{'jitter':>9s}")
CASES = [("cppll_19p2m_4p8g", -100e6), ("sspll_19p2m_4p8g", -25e6),
         ("spll_frac_52m_6p253g", -100e6), ("adpll_100m_10g", -100e6)]
results = {}
for nm, hop in CASES:
    pll = presets.ALL_PRESETS[nm]()
    r = hop_settling(pll, pll.cfg.fout + hop, n_cycles=200_000, seed=1)
    results[nm] = r
    fll = f"{r.fll_engaged_s * 1e6:8.1f}us" if r.fll_engaged_s else \
        f"{'-':>10s}"
    print(f"{nm:26s}{hop / 1e6:+6.0f}M{r.t_freq_s * 1e6:8.1f}us"
          f"{r.t_phase_s * 1e6:8.1f}us{fll}{r.jitter_fs:7.0f}fs")
print("the ADPLL wins by an order of magnitude: a digital loop retunes at "
      "its DLF\nbandwidth with no FLL slew segment; sampling loops pay for "
      "their tiny PD\ncapture range with an FLL-dominated hop.")

# ------------------------------------------------ 2. hop-size scaling
print("\n=== 2. sampling-PLL hop scaling and the FLL stability bound ===")
from pllsim.settling import fll_stability                     # noqa: E402

st = fll_stability(presets.spll_frac_52m_6p253g())
print(f"slew per FLL decision: {st['slew_per_window_hz'] / 1e3:.0f} kHz, "
      f"i_fll bound {st['i_fll_max_a'] * 1e6:.2f} uA "
      f"(margin {st['margin']:.1f}x)")
print(f"{'hop [MHz]':>10s}{'t_phase [us]':>14s}{'FLL seg [us]':>14s}")
hops = (-20e6, -50e6, -100e6, -200e6)
for hop in hops:
    pll = presets.spll_frac_52m_6p253g()
    r = hop_settling(pll, pll.cfg.fout + hop, n_cycles=250_000, seed=1)
    print(f"{hop / 1e6:10.0f}{r.t_phase_s * 1e6:14.1f}"
          f"{r.fll_engaged_s * 1e6:14.1f}")
print("the FLL segment is linear in hop size (a charge budget: dV = "
      "hop/Kvco on C1\nat i_fll).  But i_fll has a HARD upper bound — the "
      "FLL decides once per window\nand bangs full current in between, so "
      "beyond i_fll_max the limit-cycle\namplitude exceeds the release "
      "band and the FLL oscillates around zero\nFOREVER without handing "
      "off:")
pll4 = presets.spll_frac_52m_6p253g()
pll4.cfg.fll_i = 4.0 * pll4.cfg.fll_i
st4 = fll_stability(pll4)
r4 = hop_settling(pll4, pll4.cfg.fout - 100e6, n_cycles=250_000, seed=1)
t4 = "NEVER (limit cycle)" if not np.isfinite(r4.t_phase_s) \
    else f"{r4.t_phase_s * 1e6:.1f} us"
print(f"4x i_fll (margin {st4['margin']:.2f}x < 1): -100 MHz hop settles: "
      f"{t4},\nFLL engaged the entire "
      f"{r4.fll_engaged_s * 1e3:.1f} ms window — more current is NOT "
      "faster.\nfll_stability() checks the bound; the presets carry "
      "1.4-1.9x margin.")

# ------------------------------------------------ 3. anatomy of one hop
r = results["spll_frac_52m_6p253g"]
sim = r.sim
t_us = sim.t * 1e6

# ------------------------------------------------ 4. seed distribution
print("\n=== 4. settling is a yield quantity (20 seeds, -100 MHz hop) ===")
stats = hop_statistics(lambda: presets.spll_frac_52m_6p253g(),
                       presets.spll_frac_52m_6p253g().cfg.fout - 100e6,
                       seeds=range(20), n_cycles=250_000)
print(f"t_phase: p50 = {stats['p50_s'] * 1e6:.1f} us, "
      f"p95 = {stats['p95_s'] * 1e6:.1f} us, "
      f"worst = {stats['worst_s'] * 1e6:.1f} us, "
      f"non-settled = {stats['fail_frac'] * 100:.0f}%")
print("spec the p95/worst, not the mean — the FLL release point and the "
      "DSM/DTC\ninitial state move individual hops by tens of percent.")

# ------------------------------------------------------------------ plot
fig, (axl, axr) = plt.subplots(1, 2, figsize=(12.5, 4.6))
axl.plot(t_us, (sim.freq_out - r.f_to) / 1e6, lw=0.7)
eng = sim.cal_traces["fll_engaged"] > 0.5
axl.fill_between(t_us, -120, 20, where=eng, alpha=0.15, color="C1",
                 label="FLL engaged")
axl.axvline(r.t_phase_s * 1e6, color="r", ls="--", lw=1,
            label=f"phase settled {r.t_phase_s * 1e6:.0f} us")
axl.set_xlim(0, min(600, t_us[-1]))
axl.set_ylim(-120, 20)
axl.set_xlabel("time [us]")
axl.set_ylabel("frequency error [MHz]")
axl.set_title("SPLL frac -100 MHz hop anatomy")
axl.legend(fontsize=8)
axl.grid(alpha=0.3)

axr.hist(stats["t_phase_s"][np.isfinite(stats["t_phase_s"])] * 1e6,
         bins=12, alpha=0.8)
axr.axvline(stats["p95_s"] * 1e6, color="r", ls="--",
            label=f"p95 = {stats['p95_s'] * 1e6:.0f} us")
axr.set_xlabel("t_phase [us]")
axr.set_ylabel("hops")
axr.set_title("20-seed settling distribution")
axr.legend()
axr.grid(alpha=0.3)
fig.tight_layout()
fig.savefig(f"{OUT}/ex19_hop_settling.png", dpi=130)
print(f"\nplot saved to {OUT}/ex19_hop_settling.png")
