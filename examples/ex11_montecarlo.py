"""Example 11: Monte Carlo yield analysis of the fractional-N CPPLL (ex02).

Per-chip draws (the mismatch/process story a designer actually faces):
  CP up/down mismatch     ~ N(0, 1.5 %)
  CP leakage              ~ half-normal, sigma 2 nA
  DTC gain error          ~ N(0, 5 %)          (sign-sign LMS calibrates it)
  DTC INL                 ~ sinusoid, amp |N(0, 0.7 ps)|, random phase
  Kvco                    ~ N(60, 3) MHz/V     (+-5 %)
  VCO 1/f^3 corner        ~ N(300, 60) kHz

100 chips x 150k reference cycles, calibration running on every chip.
Outputs: jitter / spur / calibrated-gain distributions and yield numbers.
"""
import os
import time

import numpy as np

from pllsim.arch.cppll import CPPLL, CPPLLConfig, FracConfig
from pllsim.blocks.chargepump import CPConfig
from pllsim.blocks.dtc import DTCConfig
from pllsim.blocks.loopfilter import FilterDesign
from pllsim.blocks.oscillator import OscConfig
from pllsim.calibration.lms import SignSignLMS
from pllsim.montecarlo import monte_carlo, plot_mc

OUT = os.path.join(os.path.dirname(__file__), "out")
os.makedirs(OUT, exist_ok=True)

FREF = 38.4e6
FRAC = 0.2525
FOUT = (156 + FRAC) * FREF


def build(rng):
    mismatch = rng.normal(0.0, 1.5)
    leakage = abs(rng.normal(0.0, 2e-9))
    dtc_gain_err = rng.normal(0.0, 0.05)
    inl_amp = abs(rng.normal(0.0, 0.7e-12))
    inl_phase = rng.uniform(0, 2 * np.pi)
    kvco = rng.normal(60e6, 3e6)
    f1f3 = max(rng.normal(3e5, 6e4), 5e4)

    cfg = CPPLLConfig(
        fref=FREF, fout=FOUT,
        osc=OscConfig(f0=5.95e9, gain=kvco, pn_dbchz=-120.0, pn_foffset=1e6,
                      pn_f1f3=f1f3, pn_floor_dbchz=-152.0),
        cp=CPConfig(icp=1.5e-3, mismatch_pct=mismatch, leakage_a=leakage,
                    t_reset=150e-12),
        filt=FilterDesign(c1=470e-12, r2=15e3, c2=3.3e-12, r3=1.5e3, c3=2.2e-12),
        ref_pn_dbchz=-160.0,
        frac=FracConfig(
            frac=FRAC, mash_order=2,
            dtc=DTCConfig(t_res=250e-15, n_bits=12, jitter_rms_s=30e-15,
                          inl_sin=(inl_amp, 3.0, inl_phase)),
            dtc_cal=SignSignLMS(init=1.0, mu=5e-6, gear_shift_n=60_000,
                                mu_final=5e-7)))
    sim_kwargs = dict(n_cycles=150_000, dtc_gain_init_error=dtc_gain_err)
    params = dict(mismatch_pct=mismatch, leakage_na=leakage * 1e9,
                  dtc_gain_err=dtc_gain_err, inl_amp_ps=inl_amp * 1e12,
                  kvco_mhz=kvco / 1e6)
    return CPPLL(cfg), sim_kwargs, params


if __name__ == "__main__":
    N = 100
    t0 = time.time()
    res = monte_carlo(build, n_runs=N, seed=42)
    print(f"{N} chips x 150k cycles in {time.time() - t0:.0f} s "
          f"({os.cpu_count()} processes)\n")
    print(res.summary())

    print("\nyield:")
    print(f"  jitter < 250 fs          : {res.yield_frac('jitter_fs', 250):.0%}")
    print(f"  jitter < 300 fs          : {res.yield_frac('jitter_fs', 300):.0%}")
    if "spur_384k_dbc" in res.metrics:
        print(f"  384k frac spur < -60 dBc : "
              f"{res.yield_frac('spur_384k_dbc', -60):.0%}")
    g = res.metrics.get("cal_dtc_gain_final")
    ideal = 1.0 / (1.0 + res.params["dtc_gain_err"])
    cal_err = np.abs(g - ideal)
    print(f"  DTC gain cal |err| < 1 % : {np.mean(cal_err < 0.01):.0%}")

    plot_mc(res, metrics=["jitter_fs", "spur_384k_dbc", "cal_dtc_gain_final"],
            save=f"{OUT}/ex11_mc_histograms.png")

    # correlation: which impairment drives jitter?
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(1, 3, figsize=(12.5, 3.8))
    for ax, pname in zip(axes, ["dtc_gain_err", "inl_amp_ps", "mismatch_pct"]):
        ax.plot(res.params[pname], res.metrics["jitter_fs"], ".", ms=5)
        ax.set_xlabel(pname)
        ax.set_ylabel("jitter [fs]")
        ax.grid(alpha=0.3)
    fig.suptitle("Jitter sensitivity (calibration active)")
    fig.tight_layout()
    fig.savefig(f"{OUT}/ex11_mc_sensitivity.png", dpi=140)
    print(f"\nplots saved to {OUT}/ex11_mc_*.png")
