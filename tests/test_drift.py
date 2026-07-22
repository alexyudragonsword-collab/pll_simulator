"""Background-calibration drift tracking under a true-gain ramp."""
import numpy as np

from pllsim import presets


def _ramp_run(n_ramp, ramp_start=80_000, eps=0.03, seed=3):
    n = ramp_start + n_ramp
    pll = presets.spll_frac_52m_6p253g()
    pll.cfg.frac.dtc_cal.gear_shift_n = 40_000
    drift = np.zeros(n)
    drift[ramp_start:] = eps * np.arange(n_ramp) / n_ramp
    sim = pll.simulate(n, seed=seed, dtc_gain_drift=drift)
    g = sim.cal_traces["dtc_gain"]
    return np.abs(g * (1.0 + drift) - 1.0), sim


def test_slow_ramp_tracked_fast_ramp_lags():
    lag_slow, _ = _ramp_run(240_000)     # rate = 0.25 x mu_final
    lag_fast, _ = _ramp_run(30_000)      # rate = 2 x mu_final
    assert lag_slow[-1] < 0.015          # bounded (~0.8%)
    assert lag_fast[-1] > 1.5 * lag_slow[-1]
    # the loop still locks and jitter stays finite through the ramp
    assert np.isfinite(lag_fast).all()


def test_drift_recovers_after_ramp_stops():
    n = 260_000
    pll = presets.spll_frac_52m_6p253g()
    pll.cfg.frac.dtc_cal.gear_shift_n = 40_000
    drift = np.zeros(n)
    drift[80_000:110_000] = 0.03 * np.arange(30_000) / 30_000
    drift[110_000:] = 0.03
    sim = pll.simulate(n, seed=3, dtc_gain_drift=drift)
    g = sim.cal_traces["dtc_gain"]
    lag = np.abs(g * (1.0 + drift) - 1.0)
    assert lag[109_999] > 0.012          # lagging hard at ramp end (2x mu)
    assert lag[-1] < 0.006               # recovered at mu_final slew


def test_drift_overrides_init_error():
    pll = presets.spll_frac_52m_6p253g()
    drift = np.full(60_000, 0.05)
    sim = pll.simulate(60_000, seed=1, dtc_gain_init_error=0.2,
                       dtc_gain_drift=drift)
    # converging toward 1/1.05, not 1/1.2
    g = sim.cal_traces["dtc_gain"][-1]
    assert abs(g - 1.0 / 1.05) < 0.05
