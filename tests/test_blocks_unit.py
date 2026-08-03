"""Unit tests for the behavioral blocks, in isolation from any loop.

The architecture tests exercise these through a closed loop, where a sign
error or a factor of two is often absorbed by the feedback and shows up only
as a slightly different jitter number.  These pin each block's contract on its
own so a wrong one fails here, where the message says which block.
"""
import numpy as np
import pytest

from pllsim.blocks.chargepump import ChargePump, CPConfig
from pllsim.blocks.dtc import DTC, DTCConfig
from pllsim.blocks.loopfilter import FilterDesign, LoopFilter
from pllsim.blocks.oscillator import OscConfig, Oscillator
from pllsim.blocks.sampler import SamplerConfig, SamplingPD
from pllsim.blocks.tdc import BBPD, TDC, TDCConfig

TREF = 1.0 / 19.2e6


def rng():
    return np.random.default_rng(0)


# ------------------------------------------------------------------ oscillator
def test_freq_law_is_linear_without_nonlinearity():
    o = OscConfig(f0=4.8e9, gain=60e6)
    assert o.freq_law(0.5) == pytest.approx(4.8e9 + 30e6)
    assert o.kvco_at(0.5) == pytest.approx(60e6)


def test_v_for_inverts_the_nonlinear_law():
    o = OscConfig(f0=4.8e9, gain=60e6, nl1=-0.3, nl2=0.1)
    for target in (4.78e9, 4.8e9, 4.83e9):
        assert o.freq_law(o.v_for(target)) == pytest.approx(target, rel=1e-9)


def test_kvco_at_is_the_derivative_of_freq_law():
    o = OscConfig(f0=4.8e9, gain=60e6, nl1=-0.3, nl2=0.1)
    v, h = 0.7, 1e-6
    numeric = (o.freq_law(v + h) - o.freq_law(v - h)) / (2 * h)
    assert o.kvco_at(v) == pytest.approx(numeric, rel=1e-5)


def test_control_voltage_clamps_at_the_rails():
    o = OscConfig(f0=4.8e9, gain=60e6, v_min=0.2, v_max=1.0)
    assert o.freq_law(5.0) == o.freq_law(1.0)
    assert o.freq_law(-5.0) == o.freq_law(0.2)
    assert o.v_limited


def test_band_bank_continuity_is_a_sizing_check():
    """Span 2*gain*(v_max-v_min) against the pitch: negative overlap = holes."""
    wide = OscConfig(f0=4.8e9, gain=60e6, n_bands=8, band_step_hz=40e6,
                     v_min=0.0, v_max=1.0)
    assert wide.band_overlap_hz() == pytest.approx(60e6 - 40e6)
    assert wide.band_bank_is_continuous()
    sparse = OscConfig(f0=4.8e9, gain=60e6, n_bands=8, band_step_hz=150e6,
                       v_min=0.0, v_max=1.0)
    assert sparse.band_overlap_hz() < 0
    assert not sparse.band_bank_is_continuous()


def test_band_centres_straddle_f0():
    o = OscConfig(f0=4.8e9, gain=60e6, n_bands=5, band_step_hz=40e6)
    assert o.band_center_hz(2) == pytest.approx(4.8e9)
    assert o.band_center_hz(0) == pytest.approx(4.8e9 - 2 * 40e6)
    assert o.band_center_hz(4) == pytest.approx(4.8e9 + 2 * 40e6)


def test_oscillator_noise_accumulates_as_a_random_walk():
    """Open-loop oscillator phase variance grows with time; white noise does not."""
    o = Oscillator(OscConfig(f0=4.8e9, gain=60e6), 19.2e6, rng())
    w = o.noise_steps(200000)
    early = np.var(w[:1000] - w[0])
    late = np.var(w[100000:101000] - w[100000])
    assert np.isfinite(early) and np.isfinite(late)
    # a random walk's total spread grows without bound
    assert np.std(w[:100000]) < np.std(w)


def test_noise_off_means_exactly_zero():
    o = Oscillator(OscConfig(f0=4.8e9, gain=60e6), 19.2e6, rng(), noise=False)
    assert np.all(o.noise_steps(100) == 0.0)
    assert o.noise_step() == 0.0


# ----------------------------------------------------------------- charge pump
def test_charge_is_linear_in_the_timing_error():
    cp = ChargePump(CPConfig(icp=300e-6, t_reset=0.0), TREF, rng(), noise=False)
    assert cp.charge(1e-9) == pytest.approx(300e-6 * 1e-9)
    assert cp.charge(-1e-9) == pytest.approx(-300e-6 * 1e-9)


def test_mismatch_charge_flows_every_cycle_regardless_of_error():
    cp = ChargePump(CPConfig(icp=300e-6, mismatch_pct=4.0, t_reset=1e-9),
                    TREF, rng(), noise=False)
    assert cp.charge(0.0) == pytest.approx(300e-6 * 0.04 * 1e-9)


def test_leakage_integrates_over_the_whole_period():
    cp = ChargePump(CPConfig(icp=300e-6, leakage_a=1e-9, t_reset=0.0),
                    TREF, rng(), noise=False)
    assert cp.charge(0.0) == pytest.approx(1e-9 * TREF)


def test_lock_offset_zeroes_the_net_charge():
    """The static offset a type-II loop parks at, by construction."""
    cfg = CPConfig(icp=300e-6, mismatch_pct=3.0, leakage_a=2e-9, t_reset=0.2e-9)
    cp = ChargePump(cfg, TREF, rng(), noise=False)
    assert cp.charge(cp.lock_offset_s()) == pytest.approx(0.0, abs=1e-24)


def test_segments_sum_to_the_net_charge():
    """The waveform and the lumped model must agree on area, or the loop
    dynamics would differ between fine_oversample settings."""
    cfg = CPConfig(icp=300e-6, mismatch_pct=3.0, t_reset=0.2e-9)
    cp = ChargePump(cfg, TREF, rng(), noise=False)
    for dt in (-2e-9, -1e-12, 1e-12, 2e-9):
        area = sum(a * d for a, d in cp.segments(dt))
        assert area == pytest.approx(cp.charge(dt), rel=1e-9)


def test_noise_charge_consumes_one_sample_per_cycle_either_way():
    """charge() and noise_charge() must not double-draw, or a run's noise
    would depend on which level of detail it asked for."""
    cfg = CPConfig(icp=300e-6, flicker_corner=0.0)
    a = ChargePump(cfg, TREF, np.random.default_rng(7))
    b = ChargePump(cfg, TREF, np.random.default_rng(7))
    a.charge(1e-9)
    assert a.charge(1e-9) - 300e-6 * 1e-9 == pytest.approx(
        (lambda: (b.noise_charge(1e-9), b.noise_charge(1e-9))[1])())


def test_flicker_priming_adds_low_frequency_content():
    cfg = CPConfig(icp=300e-6, flicker_corner=1e6)
    cp = ChargePump(cfg, TREF, rng())
    cp.prime_flicker(8192)
    seq = np.array([cp.charge(0.0) for _ in range(8192)])
    f, s = np.fft.rfftfreq(seq.size, TREF)[1:], np.abs(np.fft.rfft(seq))[1:] ** 2
    lo = np.mean(s[(f > f[0]) & (f < 1e5)])
    hi = np.mean(s[f > 5e6])
    assert lo > 3 * hi, "a primed 1/f sequence must be low-frequency heavy"


# ----------------------------------------------------------------- loop filter
def test_transimpedance_matches_the_state_space_dc_behaviour():
    """A type-II passive filter integrates: |Z| ~ 1/(2 pi f C) at low f."""
    d = FilterDesign(c1=1e-9, r2=2e3, c2=100e-12)
    lf = LoopFilter(d, TREF)
    f = np.array([1e3, 1e4])
    z = np.abs(lf.transimpedance(f))
    assert z[0] / z[1] == pytest.approx(10.0, rel=0.05)


def test_impulse_response_conserves_charge_on_the_integrator():
    """With no input the type-II pole holds the accumulated voltage."""
    lf = LoopFilter(FilterDesign(c1=1e-9, r2=2e3, c2=100e-12), TREF)
    lf.reset(0.0)
    lf.update_impulse(1e-12)
    settled = [lf.update_impulse(0.0) for _ in range(2000)][-1]
    assert settled == pytest.approx(1e-12 / (1e-9 + 100e-12), rel=1e-3)


def test_pulse_and_impulse_agree_for_a_narrow_pulse():
    d = FilterDesign(c1=1e-9, r2=2e3, c2=100e-12)
    a, b = LoopFilter(d, TREF), LoopFilter(d, TREF)
    dq, t_on = 1e-12, 1e-12
    assert a.update_pulse(dq / t_on, t_on) == pytest.approx(
        b.update_impulse(dq), rel=1e-6)


def test_drive_fine_endpoint_equals_the_coarse_step():
    d = FilterDesign(c1=1e-9, r2=2e3, c2=100e-12, r3=1e3, c3=20e-12)
    a, b = LoopFilter(d, TREF), LoopFilter(d, TREF)
    a.reset(0.5)
    b.reset(0.5)
    for _ in range(20):
        v1 = a.update_pulse(1e-3, 3e-9)
        v2 = b.drive_fine([(1e-3, 3e-9)], 16)[-1]
    assert v1 == pytest.approx(v2, rel=1e-9)


def test_drive_fine_resolves_a_segment_shorter_than_a_sub_interval():
    """A 1 ps pulse inside a 52 ns step must still deliver its charge."""
    lf = LoopFilter(FilterDesign(c1=1e-9, r2=2e3, c2=100e-12), TREF)
    lf.reset(0.0)
    lf.drive_fine([(1.0, 1e-12)], 4)          # 1 A for 1 ps = 1 pC
    settled = [lf.update_impulse(0.0) for _ in range(2000)][-1]
    assert settled == pytest.approx(1e-12 / (1e-9 + 100e-12), rel=1e-2)


def test_third_order_filter_adds_a_pole():
    f = np.logspace(5, 8, 200)
    z2 = np.abs(LoopFilter(FilterDesign(1e-9, 2e3, 100e-12), TREF).transimpedance(f))
    z3 = np.abs(LoopFilter(FilterDesign(1e-9, 2e3, 100e-12, r3=1e3, c3=20e-12),
                           TREF).transimpedance(f))
    assert z3[-1] < 0.5 * z2[-1], "the extra pole must roll off harder"


# --------------------------------------------------------------------- sampler
def test_sampler_gain_is_the_sine_slope_at_the_origin():
    s = SamplerConfig(amp_v=0.4, pedestal_v=0.0)
    pd = SamplingPD(s, TREF, rng(), noise=False)
    assert pd.sample(0.0) == pytest.approx(0.0)
    assert pd.sample(1e-3) == pytest.approx(0.4 * 1e-3, rel=1e-5)


def test_pedestal_is_an_additive_offset():
    s = SamplerConfig(amp_v=0.4, pedestal_v=2e-3)
    pd = SamplingPD(s, TREF, rng(), noise=False)
    assert pd.sample(0.0) == pytest.approx(2e-3)


def test_ktc_noise_has_the_right_variance():
    s = SamplerConfig(amp_v=0.4, c_samp=50e-15, pedestal_v=0.0)
    pd = SamplingPD(s, TREF, np.random.default_rng(1))
    v = np.array([pd.sample(0.0) for _ in range(40000)])
    assert np.std(v) == pytest.approx(s.ktc_sigma_v, rel=0.03)


def test_charge_is_gm_times_held_voltage_times_window():
    s = SamplerConfig(gm=2e-3, pulse_width=500e-12)
    pd = SamplingPD(s, TREF, rng(), noise=False)
    assert pd.charge(0.1) == pytest.approx(2e-3 * 0.1 * 500e-12)


def test_sampler_segments_carry_the_kickback_first():
    s = SamplerConfig(gm=2e-3, pulse_width=500e-12, kick_q_c=1e-15,
                      kick_delay_s=300e-12)
    pd = SamplingPD(s, TREF, rng(), noise=False)
    segs = pd.segments(2e-15)
    assert sum(a * d for a, d in segs) == pytest.approx(1e-15 + 2e-15)
    assert segs[0][0] > 0, "kickback leads the gm pulse"


def test_no_kickback_means_no_ripple_fundamental():
    pd = SamplingPD(SamplerConfig(pedestal_v=5e-3), TREF, rng(), noise=False)
    assert pd.ripple_fundamental_a(TREF) == 0.0


# ------------------------------------------------------------------- TDC / DTC
def test_tdc_quantizes_with_the_true_lsb_not_the_nominal_one():
    t = TDC(TDCConfig(t_res=5e-12, n_bits=7, gain_error=0.1), rng(), noise=False)
    assert t.measure(55e-12) == int(55e-12 / (5e-12 * 1.1))


def test_tdc_saturates_at_both_ends():
    t = TDC(TDCConfig(t_res=5e-12, n_bits=4), rng(), noise=False)
    assert t.measure(1e-6) == 15
    assert t.measure(-1e-9) == 0


def test_bbpd_is_the_sign_and_nothing_else():
    bb = BBPD(0.0, rng(), noise=False)
    assert bb.sample(1e-15) == 1
    assert bb.sample(-1e-15) == -1
    assert bb.sample(0.0) == 1


def test_bbpd_jitter_randomizes_near_the_threshold():
    bb = BBPD(1e-12, np.random.default_rng(3))
    out = np.array([bb.sample(0.0) for _ in range(5000)])
    assert abs(out.mean()) < 0.05, "at zero error the sign must be unbiased"


def test_dtc_code_uses_the_calibrated_gain_and_the_device_the_true_one():
    cfg = DTCConfig(t_res=1e-12, n_bits=8)
    d = DTC(cfg, rng(), noise=False, gain_error=0.2)
    t = d.delay(0.0)                     # mid-range target
    assert d.last_code == round(cfg.range_s / 2 / cfg.t_res)
    assert t == pytest.approx(d.last_code * cfg.t_res * 1.2)


def test_dtc_gain_correction_moves_the_code_not_the_device():
    cfg = DTCConfig(t_res=1e-12, n_bits=8)
    d = DTC(cfg, rng(), noise=False, gain_error=0.2)
    d.delay(0.0)
    base = d.last_code
    d.gain_corr = 1.0 / 1.2
    d.delay(0.0)
    assert d.last_code == pytest.approx(base / 1.2, rel=1e-2)


def test_dtc_inl_shapes_are_additive():
    cfg = DTCConfig(t_res=1e-12, n_bits=8, inl_sin=(3e-12, 2, 0.0),
                    inl_poly=(0.0, 1e-12))
    d = DTC(cfg, rng(), noise=False)
    x = 0.25
    code = int(round(x * d.code_max))
    want = 3e-12 * np.sin(2 * np.pi * 2 * code / d.code_max) \
        + 1e-12 * (code / d.code_max)
    assert d.inl_s(code) == pytest.approx(want)


def test_dtc_codes_clamp_to_the_range():
    cfg = DTCConfig(t_res=1e-12, n_bits=6)
    d = DTC(cfg, rng(), noise=False)
    d.delay(1e-6)
    assert d.last_code == d.code_max
    d.delay(-1e-6)
    assert d.last_code == 0
