"""Example 20: does background calibration survive a temperature ramp?

Production background cal is judged while the chip DRIFTS, not at the
convergence plot's happy ending.  The sign-sign LMS moves its correction
by at most mu per update, so a true-gain drift rate r (per reference
cycle) splits the world in two:

    r < mu_final : bounded tracking lag  (dither + EMA-centering residue)
    r > mu_final : the correction cannot keep up — lag grows through the
                   ramp toward eps_total * (1 - mu/r) and only recovers
                   after the ramp stops

and every % of tracking lag is a live fractional-spur penalty
(dtc_spur_table with gain_eps = lag).  The ramps here are ACCELERATED
by design (percent-level drift in ms) to expose the law; the closing
arithmetic scales it back to reality: a DTC at ~600 ppm/degC on a
10 degC/s thermal transient drifts ~1e-12 per cycle — five orders below
mu_final.  Background gain cal is safe against real temperature ramps;
the law matters for step-like events (band switch, burst power cycling),
which is exactly what ex19's hop analysis covers.

The other side of the mu window: gradient noise.  A larger mu_final
tracks faster drift but wanders more in steady state (sigma ~ mu per
step random walk, loop-filtered) — measured below as the static jitter
penalty.  mu_final must sit between the worst drift rate and the noise
budget; the sweep shows both walls.
"""
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from pllsim import presets
from pllsim.core.dtcspurs import dtc_spur_table

OUT = os.path.join(os.path.dirname(__file__), "out")
os.makedirs(OUT, exist_ok=True)

RAMP_START = 80_000          # gear shift at 40k: mu_final active well before
EPS_TOT = 0.03               # 3% total true-gain excursion
MU_FINAL = 5e-7


def ramped(n_ramp: int, seed: int = 3):
    """Run the Wu'19-class SPLL through a ramp that ENDS the simulation:
    the final tracking lag is the peak lag."""
    n = RAMP_START + n_ramp
    pll = presets.spll_frac_52m_6p253g()
    pll.cfg.frac.dtc_cal.gear_shift_n = 40_000
    drift = np.zeros(n)
    drift[RAMP_START:] = EPS_TOT * np.arange(n_ramp) / n_ramp
    sim = pll.simulate(n, seed=seed, dtc_gain_drift=drift)
    g = sim.cal_traces["dtc_gain"]
    lag = np.abs(g * (1.0 + drift) - 1.0)
    return sim, drift, lag


# ------------------------------------------------ 1. the tracking law
print("=== 1. tracking lag vs drift rate (mu_final = 5e-7 per cycle) ===")
print(f"{'rate/mu':>9s}{'rate [1/cycle]':>16s}{'peak lag':>10s}"
      f"{'spur @62.4k':>13s}{'jitter':>9s}")
pll0 = presets.spll_frac_52m_6p253g()
traces = {}
for n_ramp in (240_000, 120_000, 60_000, 30_000):
    rate = EPS_TOT / n_ramp
    sim, drift, lag = ramped(n_ramp)
    traces[rate / MU_FINAL] = (sim, drift, lag)
    c = pll0.cfg
    tab = dtc_spur_table(c.frac,
                         lambda r: -r / c.fout - c.frac.dtc.range_s / 2.0,
                         c.fref, c.fout, gain_eps=float(lag[-1]))
    spur = max(tab.values())
    print(f"{rate / MU_FINAL:9.2f}{rate:16.2e}{lag[-1] * 100:9.2f}%"
          f"{spur:11.1f}dBc{sim.jitter_fs:7.0f}fs")
print("two mechanisms stack: even well below the slew wall the lag is "
      "already ~1%\nclass — the EMA error-centering (mandatory for static "
      "offsets) subtracts part\nof the drift-induced error and blinds the "
      "correlator during ramps; above\nrate ~ mu the slew limit adds on "
      "top.  Every % of lag is a live in-band\nfractional spur at "
      "20*log10(lag) — production designs gear the LMS back UP\nwhen a "
      "ramp is detected, or slow the EMA.")

# ------------------------------------------------ 2. the other wall: noise
print("\n=== 2. static gradient noise: the upper wall of the mu window ===")
print(f"{'mu_final':>10s}{'jitter [fs]':>13s}{'gain wander (rms)':>20s}")
for mu in (5e-7, 5e-6, 5e-5):
    pll = presets.spll_frac_52m_6p253g()
    pll.cfg.frac.dtc_cal.gear_shift_n = 40_000
    pll.cfg.frac.dtc_cal.mu_final = mu
    sim = pll.simulate(200_000, seed=4)
    g = sim.cal_traces["dtc_gain"][120_000:]
    print(f"{mu:10.0e}{sim.jitter_fs:11.0f}fs{np.std(g) * 100:18.3f}%")
print("mu_final selection rule: worst drift rate per cycle < mu_final < "
      "wander that\nkeeps the dsm-residual spur/jitter inside budget.")

# ------------------------------------------------ 3. scale back to reality
print("\n=== 3. scaling the accelerated ramp back to silicon ===")
tempco = 600e-6              # DTC gain tempco [1/degC], generous
slew = 10.0                  # degC/s, an aggressive thermal transient
rate_real = tempco * slew / pll0.cfg.fref
print(f"600 ppm/degC x 10 degC/s at fref = 52 MHz -> "
      f"rate = {rate_real:.1e} per cycle = {rate_real / MU_FINAL:.1e} x mu")
print("real thermal ramps sit ~5 orders below the cliff: background gain "
      "cal is\nnot the weak link for temperature — step events (band "
      "switch, power burst)\nare, and those belong to ex19's settling "
      "analysis.")

# ------------------------------------------------------------------ plot
fig, (axl, axr) = plt.subplots(1, 2, figsize=(12.5, 4.6))
for ratio, (sim, drift, lag) in sorted(traces.items()):
    n0 = RAMP_START - 20_000
    t_ms = (np.arange(lag.size) - RAMP_START) / pll0.cfg.fref * 1e3
    axl.plot(t_ms[n0:], lag[n0:] * 100, lw=1.0,
             label=f"rate = {ratio:.2g} x mu")
axl.set_xlabel("time from ramp start [ms]")
axl.set_ylabel("tracking lag |g(1+eps)-1| [%]")
axl.set_title("sign-sign LMS under a gain ramp")
axl.legend(fontsize=8)
axl.grid(alpha=0.3)

ratios = sorted(traces)
axr.semilogx(ratios, [traces[r][2][-1] * 100 for r in ratios], "o-")
axr.axvline(1.0, color="r", ls="--", label="rate = mu (slew limit)")
axr.set_xlabel("drift rate / mu_final")
axr.set_ylabel("peak lag [%]")
axr.set_title("the tracking wall")
axr.legend()
axr.grid(alpha=0.3, which="both")
fig.tight_layout()
fig.savefig(f"{OUT}/ex20_drift_tracking.png", dpi=130)
print(f"\nplot saved to {OUT}/ex20_drift_tracking.png")
