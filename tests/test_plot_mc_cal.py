"""Plot helpers, Monte Carlo collation and the calibration loops.

Plotting had no tests at all, so a stale attribute name would only surface
when someone ran an example.  These call every figure function on real
results and assert on what ends up on the axes, not just that nothing raised.
"""
import matplotlib
import numpy as np
import pytest

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from pllsim import plotting, presets
from pllsim.calibration.ftl import FTL, FLLStateMachine, InjTimingCal
from pllsim.calibration.gain_cal import BandSelect
from pllsim.calibration.lms import LMSGainCal, SignSignLMS
from pllsim.montecarlo import MCResult, monte_carlo, plot_mc


@pytest.fixture(scope="module")
def run():
    p = presets.cppll_frac_38p4m_6g()
    return p.analyze(), p.simulate(20000, seed=1)


@pytest.fixture(autouse=True)
def _close_figs():
    yield
    plt.close("all")


# -------------------------------------------------------------------- plotting
def test_pn_breakdown_draws_every_source_plus_the_total(run):
    ar, sim = run
    fig = plotting.plot_pn_breakdown(ar, sim)
    labels = {ln.get_label() for ln in fig.axes[0].get_lines()}
    for src in ar.pn_breakdown:
        if src != "total":
            assert src in labels
    assert "total (linear model)" in labels
    assert "time-domain sim" in labels


def test_pn_breakdown_without_a_sim_omits_the_overlay(run):
    ar, _ = run
    fig = plotting.plot_pn_breakdown(ar)
    assert "time-domain sim" not in {ln.get_label() for ln in fig.axes[0].get_lines()}


def test_pn_breakdown_fmax_sets_the_axis(run):
    ar, _ = run
    fig = plotting.plot_pn_breakdown(ar, fmax=1e7)
    assert fig.axes[0].get_xlim()[1] == pytest.approx(1e7)


def test_transient_has_three_stacked_panels(run):
    _, sim = run
    fig = plotting.plot_transient(sim)
    assert len(fig.axes) == 3
    assert fig.axes[0].get_lines()[0].get_xdata().size == sim.t.size


def test_transient_marks_the_lock_time_only_when_there_is_one(run):
    _, sim = run
    assert sim.lock_time_s is not None, "this preset should reach lock"
    marked = plotting.plot_transient(sim)
    assert any("lock @" in (ln.get_label() or "")
               for ln in marked.axes[0].get_lines())

    import copy
    unlocked = copy.copy(sim)
    unlocked.lock_time_s = None
    plain = plotting.plot_transient(unlocked)
    assert not any("lock @" in (ln.get_label() or "")
                   for ln in plain.axes[0].get_lines())


def test_spur_spectrum_marks_every_detected_spur(run):
    ar, sim = run
    fig = plotting.plot_spur_spectrum(sim, ar=ar)
    ax = fig.axes[0]
    # every entry gets a marker, NaN included: "below the floor here" is
    # information a spur plot should show rather than silently drop
    assert len(ax.texts) == len(sim.spurs_fft)
    assert "linear model" in {ln.get_label() for ln in ax.get_lines()}


def test_spur_spectrum_works_without_a_linear_overlay(run):
    _, sim = run
    fig = plotting.plot_spur_spectrum(sim)
    assert fig.axes[0].get_legend() is None


def test_cal_convergence_has_one_panel_per_trace(run):
    _, sim = run
    assert sim.cal_traces, "this preset should carry a calibration trace"
    fig = plotting.plot_cal_convergence(sim)
    assert len(fig.axes) == len(sim.cal_traces)


def test_every_plot_writes_a_file(tmp_path, run):
    ar, sim = run
    for name, fn, args in [("pn", plotting.plot_pn_breakdown, (ar, sim)),
                           ("tr", plotting.plot_transient, (sim,)),
                           ("sp", plotting.plot_spur_spectrum, (sim,)),
                           ("cal", plotting.plot_cal_convergence, (sim,))]:
        out = tmp_path / f"{name}.png"
        fn(*args, save=str(out))
        assert out.stat().st_size > 1000


# ----------------------------------------------------------------- Monte Carlo
def _build(rng):
    """Module-level so ProcessPoolExecutor can pickle it."""
    p = presets.cppll_19p2m_4p8g()
    mm = float(rng.normal(2.0, 0.5))
    p.cfg.cp.mismatch_pct = mm
    return p, {"n_cycles": 4000, "noise": False}, {"mismatch_pct": mm}


def _build_that_fails(rng):
    if rng.random() < 0.5:
        raise ValueError("drawn instance does not build")
    return _build(rng)


def test_monte_carlo_collates_metrics_and_params():
    res = monte_carlo(_build, n_runs=4, seed=0, n_jobs=1)
    assert res.n_runs == 4 and res.n_ok == 4
    assert "jitter_fs" in res.metrics
    assert res.params["mismatch_pct"].size == 4
    assert np.all(np.isfinite(res.metrics["jitter_fs"]))


def test_a_diverged_run_is_data_not_a_crash():
    res = monte_carlo(_build_that_fails, n_runs=6, seed=3, n_jobs=1)
    assert res.failures, "this build fails half the time by construction"
    assert res.n_ok == res.n_runs - len(res.failures)
    assert res.summary()


def test_multiprocess_and_serial_agree():
    a = monte_carlo(_build, n_runs=4, seed=11, n_jobs=1)
    b = monte_carlo(_build, n_runs=4, seed=11, n_jobs=2)
    assert np.allclose(a.metrics["jitter_fs"], b.metrics["jitter_fs"])


def test_yield_frac_counts_the_right_side():
    r = MCResult(metrics={"jitter_fs": np.array([100.0, 200.0, 300.0, 400.0])},
                 params={}, n_runs=4)
    assert r.yield_frac("jitter_fs", 250.0, "<") == 0.5
    assert r.yield_frac("jitter_fs", 250.0, ">") == 0.5


def test_nan_spurs_pass_a_less_than_limit_but_nan_jitter_does_not():
    """A spur below the noise floor is a pass; a run whose jitter is NaN is
    a failure.  Conflating them would inflate the yield."""
    r = MCResult(metrics={"spur_600k_dbc": np.array([np.nan, -70.0]),
                          "jitter_fs": np.array([np.nan, 100.0])},
                 params={}, n_runs=2)
    assert r.yield_frac("spur_600k_dbc", -60.0, "<") == 1.0
    assert r.yield_frac("jitter_fs", 200.0, "<") == 0.5


def test_summary_reports_all_nan_columns_rather_than_dividing_by_zero():
    r = MCResult(metrics={"x": np.array([np.nan, np.nan])}, params={}, n_runs=2)
    assert "all NaN" in r.summary()


def test_plot_mc_makes_one_panel_per_metric(tmp_path):
    res = monte_carlo(_build, n_runs=6, seed=5, n_jobs=1)
    fig = plot_mc(res, metrics=["jitter_fs"], save=str(tmp_path / "mc.png"))
    drawn = [ax for ax in fig.axes if ax.get_title()]
    assert len(drawn) == 1
    assert (tmp_path / "mc.png").stat().st_size > 1000


def test_plot_mc_defaults_skip_calibration_traces():
    res = MCResult(metrics={"jitter_fs": np.array([1.0, 2.0]),
                            "cal_dtc_gain_final": np.array([1.0, 1.0])},
                   params={}, n_runs=2)
    fig = plot_mc(res)
    titles = [ax.get_title() for ax in fig.axes if ax.get_title()]
    assert any("jitter_fs" in t for t in titles)
    assert not any("cal_" in t for t in titles)


# ---------------------------------------------------------------- calibration
def test_fll_engages_far_out_and_releases_near_lock():
    fll = FLLStateMachine(250, 19.2e6, window=8, f_engage=3e6, f_release=5e5,
                          hyst_windows=1)
    assert fll.engaged
    for _ in range(64):                       # exactly on target
        fll.step(250.0)
    assert not fll.engaged, "a locked counter must hand off"
    for _ in range(64):                       # 1 cycle/ref off = 19.2 MHz
        fll.step(251.0)
    assert fll.engaged, "a big frequency error must re-engage"


def test_fll_hysteresis_needs_repeated_windows():
    fll = FLLStateMachine(250, 19.2e6, window=4, f_release=5e5, hyst_windows=3)
    for _ in range(4 * 2):
        fll.step(250.0)
    assert fll.engaged, "two quiet windows are not enough with hyst=3"
    for _ in range(4):
        fll.step(250.0)
    assert not fll.engaged


def test_fll_drive_is_zero_once_released():
    fll = FLLStateMachine(250, 19.2e6, window=4, f_release=5e5, hyst_windows=1)
    for _ in range(16):
        last = fll.step(250.0)
    assert last == 0.0


def test_fll_drive_opposes_the_error_sign():
    hi = FLLStateMachine(250, 19.2e6, window=4, f_release=5e5)
    lo = FLLStateMachine(250, 19.2e6, window=4, f_release=5e5)
    for _ in range(8):
        dq_hi = hi.step(251.0)      # running fast
        dq_lo = lo.step(249.0)      # running slow
    assert dq_hi < 0 < dq_lo


def test_ftl_is_bang_bang_and_gear_shifts():
    ftl = FTL(f_lsb=50e3, mu=1.0, gear_shift_n=3, mu_final=0.25)
    assert ftl.step(1.0) == pytest.approx(-50e3)
    assert ftl.step(-1.0) == pytest.approx(0.0)
    for _ in range(3):
        ftl.step(1.0)
    coarse = ftl.trace[2] - ftl.trace[1]
    fine = ftl.trace[-1] - ftl.trace[-2]
    assert abs(fine) < abs(coarse), "the gear shift must shrink the step"
    assert len(ftl.trace) == 5


def test_inj_timing_cal_walks_toward_the_observed_drift():
    cal = InjTimingCal(t_step=50e-15, mu=1.0)
    for _ in range(10):
        cal.step(1.0)
    assert cal.value == pytest.approx(10 * 50e-15)
    for _ in range(20):
        cal.step(-1.0)
    assert cal.value == pytest.approx(-10 * 50e-15)


def test_band_select_binary_searches_to_the_closest_band():
    bs = BandSelect(n_bands=16, f_target=4.8e9)
    centres = 4.8e9 + (np.arange(16) - 7.5) * 40e6
    while not bs.done:
        bs.observe(centres[bs.band])
    assert bs.band == int(np.argmin(np.abs(centres - 4.8e9)))
    assert len(bs.trace) <= 16


def test_lms_gain_cal_converges_on_a_known_gain_error():
    """Closing the loop the way an engine does: the residual timing error is
    proportional to how far the correction still is from 1/true."""
    cal = LMSGainCal(init=1.0, mu=0.05, ema=0.01)
    rng = np.random.default_rng(0)
    true = 1.10
    for _ in range(20000):
        r = rng.uniform(-1.0, 1.0)
        cal.step(-(true * cal.value - 1.0) * r, r)
    assert cal.value == pytest.approx(1.0 / true, rel=0.02)
    assert len(cal.trace) == 20000


def test_sign_sign_lms_moves_by_a_fixed_step():
    """Step size is mu regardless of how big the error is -- that bounded
    update is the whole reason to use it in hardware."""
    cal = SignSignLMS(init=1.0, mu=1e-3, center_err=False)
    v0 = cal.value
    cal.step(1.0, 1.0)
    small = abs(cal.value - v0)
    v1 = cal.value
    cal.step(1e6, 1.0)
    assert small == pytest.approx(1e-3)
    assert abs(cal.value - v1) == pytest.approx(1e-3)


def test_gear_shift_shrinks_the_lms_step():
    cal = SignSignLMS(init=1.0, mu=1e-3, gear_shift_n=5, mu_final=1e-4,
                      center_err=False)
    for _ in range(5):
        cal.step(1.0, 1.0)
    coarse = abs(cal.trace[-1] - cal.trace[-2])
    for _ in range(3):
        cal.step(1.0, 1.0)
    assert abs(cal.trace[-1] - cal.trace[-2]) < coarse


def test_regressor_centering_rejects_a_dc_offset():
    """A residual sequence with a DC offset must not bias the correlation."""
    a = LMSGainCal(init=0.0, mu=1e-3, ema=0.05, center_err=False)
    rng = np.random.default_rng(4)
    for _ in range(20000):
        a.step(1.0, 5.0 + rng.normal())      # error uncorrelated with regressor
    assert abs(a.value) < 0.5, "a constant regressor offset must not integrate"
