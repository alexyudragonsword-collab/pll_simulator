"""Unit tests for core estimation, noise sources, engine post-processing.

Every architecture's cross-domain agreement rests on these: if find_spurs
mis-scales, every reported spur is wrong by the same amount and every
cross-check still passes.  So they are pinned against synthesized signals
whose answer is known exactly.
"""
import numpy as np
import pytest

from pllsim.core import noise as nz
from pllsim.core.engine import detect_lock, postprocess
from pllsim.core.freqresp import FreqResponse, default_grid
from pllsim.core.jitter import ipn_dbc, rms_jitter_fs
from pllsim.core.results import SimResult
from pllsim.core.spectrum import find_spurs, periodogram_psd, phase_psd

TWOPI = 2.0 * np.pi


# ------------------------------------------------------------------- spectrum
def test_phase_psd_recovers_a_known_white_level():
    """S_phi = sigma^2/(fs/2) one-sided for a white sequence."""
    fs, n = 100e6, 1 << 16
    sig = 0.01
    x = np.random.default_rng(0).normal(0.0, sig, n)
    f, s = phase_psd(x, fs)
    assert np.median(s) == pytest.approx(sig**2 / (fs / 2), rel=0.1)


def test_find_spurs_recovers_a_known_sideband():
    """A tone of peak phase A gives a sideband of 20log10(A/2) dBc."""
    fs, n, fo, amp = 100e6, 1 << 17, 3e6, 1e-3
    t = np.arange(n) / fs
    x = amp * np.sin(TWOPI * fo * t)
    f, s = periodogram_psd(x, fs)
    got = find_spurs(f, s, [fo])[fo]
    assert got == pytest.approx(20 * np.log10(amp / 2), abs=0.2)


def test_find_spurs_returns_nan_when_the_cluster_is_below_the_pedestal():
    """A dip is not a spur.  Fed directly so the outcome is deterministic --
    on random noise a cluster beats the local median about half the time,
    which is the estimator working, not failing."""
    f = np.arange(1, 2001) * 1e4
    s = np.full(f.size, 1e-12)
    s[f == 7e6] = 1e-15                     # a notch at the target
    assert np.isnan(find_spurs(f, s, [7e6])[7e6])


def test_find_spurs_subtracts_the_noise_pedestal():
    """A tone sitting on noise must read the same as one that is not."""
    fs, n, fo, amp = 100e6, 1 << 17, 3e6, 1e-3
    t = np.arange(n) / fs
    tone = amp * np.sin(TWOPI * fo * t)
    rng = np.random.default_rng(2)
    clean = find_spurs(*periodogram_psd(tone, fs), [fo])[fo]
    noisy = find_spurs(*periodogram_psd(tone + rng.normal(0, 3e-5, n), fs),
                       [fo])[fo]
    assert abs(noisy - clean) < 0.3


def test_find_spurs_off_grid_offset_is_nan_not_a_wrong_number():
    fs, n = 100e6, 1 << 14
    f, s = periodogram_psd(np.zeros(n) + 1e-9, fs)
    assert np.isnan(find_spurs(f, s, [fs])[fs])          # beyond the grid


# ---------------------------------------------------------------------- jitter
def test_rms_jitter_matches_a_hand_integrated_flat_psd():
    """sigma_phi^2 = integral S_phi df; t_rms = sigma_phi/(2 pi f0)."""
    f = np.logspace(3, 8, 20001)
    level = 1e-14
    s = np.full_like(f, level)
    f0, f1, f2 = 1e10, 1e4, 1e7
    want = np.sqrt(level * (f2 - f1)) / (TWOPI * f0) * 1e15
    assert rms_jitter_fs(f, s, f0, f1, f2) == pytest.approx(want, rel=0.01)


def test_ipn_uses_the_single_sideband_convention():
    """IPN is quoted from L(f) = S_phi/2, so it sits 3.01 dB below the
    integral of the double-sideband S_phi this library carries everywhere
    else.  Pinned because mixing the two is a silent 3 dB."""
    f = np.logspace(3, 8, 20001)
    s = np.full_like(f, 1e-14)
    f1, f2 = 1e4, 1e7
    dsb = 10 * np.log10(1e-14 * (f2 - f1))
    assert ipn_dbc(f, s, f1, f2) == pytest.approx(dsb - 3.0103, abs=0.05)


def test_jitter_scales_inversely_with_carrier():
    f = np.logspace(3, 8, 5001)
    s = np.full_like(f, 1e-14)
    a = rms_jitter_fs(f, s, 1e9, 1e4, 1e7)
    b = rms_jitter_fs(f, s, 2e9, 1e4, 1e7)
    assert a / b == pytest.approx(2.0, rel=1e-3)


# ---------------------------------------------------------------- noise sources
def test_flicker_floor_crosses_the_declared_spot():
    src = nz.FlickerFloorPhase.from_spot("x", -150.0, 1e5)
    # from_spot places the FLOOR at the quoted level; at the corner the
    # flicker term adds equal power, i.e. +3 dB
    assert 10 * np.log10(src.psd(np.array([1e9]))[0] / 2) == pytest.approx(-150, abs=0.1)
    at_corner = 10 * np.log10(src.psd(np.array([1e5]))[0] / 2)
    assert at_corner == pytest.approx(-147, abs=0.2)


def test_leeson_has_the_right_asymptotic_slopes():
    src = nz.LeesonOscillator.from_spot("vco", -120.0, 1e6, f_1f3=2e5,
                                        floor_dbchz=-160.0)
    f = np.array([1e6, 2e6])
    s = src.psd(f)
    assert 10 * np.log10(s[0] / s[1]) == pytest.approx(6.0, abs=0.5)   # 1/f^2
    f3 = np.array([1e4, 2e4])
    s3 = src.psd(f3)
    assert 10 * np.log10(s3[0] / s3[1]) == pytest.approx(9.0, abs=1.0)  # 1/f^3


def test_sampled_charge_noise_carries_the_alias_factor():
    """One packet per cycle aliases into [0, fs/2]: S_q = 2*i2*tau/fs."""
    src = nz.SampledChargeNoise(name="gm", unit="C^2/Hz", i2=1e-20, tau=1e-9,
                                fs=1e8)
    assert src.psd(np.array([1e5]))[0] == pytest.approx(2 * 1e-20 * 1e-9 / 1e8)


def test_current_noise_duty_scales_the_level():
    a = nz.CurrentNoise(name="cp", unit="A^2/Hz", i2=1e-22, duty=1.0)
    b = nz.CurrentNoise(name="cp", unit="A^2/Hz", i2=1e-22, duty=0.25)
    f = np.array([1e5])
    assert a.psd(f)[0] / b.psd(f)[0] == pytest.approx(4.0)


def test_resistor_noise_is_4kTR():
    r = nz.ResistorNoise(name="r", unit="V^2/Hz", r_ohm=1e3)
    assert r.psd(np.array([1e6]))[0] == pytest.approx(4 * 1.380649e-23 * 290 * 1e3,
                                                      rel=1e-3)


def test_sampled_ktc_is_two_sigma_squared_over_fs():
    c, fs = 50e-15, 1e8
    src = nz.SampledKTC(name="ktc", unit="V^2/Hz", c_farad=c, fs=fs)
    sigma2 = 1.380649e-23 * 290.0 / c
    assert src.psd(np.array([1e5]))[0] == pytest.approx(2 * sigma2 / fs, rel=1e-3)


def test_shaped_quantization_slope_follows_the_order():
    f = np.array([1e5, 2e5])
    flat = nz.ShapedQuantization(name="q", unit="rad^2/Hz", q=1.0, fs=1e8, order=0)
    assert flat.psd(f)[0] == pytest.approx(flat.psd(f)[1])
    shaped = nz.ShapedQuantization(name="q", unit="rad^2/Hz", q=1.0, fs=1e8, order=2)
    slope = 10 * np.log10(shaped.psd(f)[1] / shaped.psd(f)[0])
    assert slope == pytest.approx(12.0, abs=0.5)     # (2*order) * 6 dB/octave


def test_tabulated_phase_interpolates_log_log_and_holds_the_ends():
    src = nz.TabulatedPhase(name="meas", unit="rad^2/Hz",
                            f_pts=(1e3, 1e6), l_dbc_pts=(-100.0, -160.0))
    dbc = lambda x: 10 * np.log10(src.psd(np.array([x]))[0] / 2)   # noqa: E731
    assert dbc(1e2) == pytest.approx(-100.0, abs=0.1)      # held below the table
    assert dbc(1e9) == pytest.approx(-160.0, abs=0.1)      # held above it
    assert dbc(np.sqrt(1e3 * 1e6)) == pytest.approx(-130.0, abs=0.1)


def test_output_psd_sums_powers_and_keeps_a_total():
    f = default_grid(1e3, 1e7)
    one = FreqResponse(f, np.ones_like(f, dtype=complex))
    paths = [nz.NoisePath(nz.NoiseSource(name="a", unit="rad^2/Hz", level=1e-12), one),
             nz.NoisePath(nz.NoiseSource(name="b", unit="rad^2/Hz", level=3e-12), one)]
    bd = nz.output_psd(paths, f)
    assert set(bd) == {"a", "b", "total"}
    assert np.allclose(bd["total"], 4e-12)


def test_noise_path_applies_the_transfer_in_power():
    f = default_grid(1e3, 1e7)
    half = FreqResponse(f, np.full(f.shape, 0.5 + 0j))
    bd = nz.output_psd(
        [nz.NoisePath(nz.NoiseSource(name="a", unit="rad^2/Hz", level=4e-12), half)], f)
    assert np.allclose(bd["a"], 1e-12)


# ---------------------------------------------------------------------- engine
def test_detect_lock_needs_a_sustained_run():
    t = np.arange(1000) * 1e-9
    err = np.where(np.arange(1000) < 400, 1e6, 1.0)
    assert detect_lock(t, err, tol_hz=10.0, hold=200) == pytest.approx(t[400])
    assert detect_lock(t, err, tol_hz=10.0, hold=800) is None


def test_detect_lock_is_none_for_a_record_shorter_than_hold():
    t = np.arange(10) * 1e-9
    assert detect_lock(t, np.zeros(10), tol_hz=1.0, hold=200) is None


def _sim(ph, fs=100e6, f0=10e9):
    n = ph.size
    return SimResult(fs=fs, f0=f0, t=np.arange(n) / fs, phase_err_out=ph,
                     freq_out=np.full(n, f0), ctrl=np.zeros(n), lock_time_s=None)


def test_postprocess_flags_an_unfinished_transient():
    rng = np.random.default_rng(0)
    n = 1 << 14
    ph = rng.normal(0, 1e-3, n)
    ph[:n // 2] *= 20.0            # still settling in the analysed window
    out = postprocess(_sim(ph), settle_frac=0.0)
    assert any("still settling" in note for note in out.notes)


def test_postprocess_is_quiet_on_a_settled_record():
    ph = np.random.default_rng(0).normal(0, 1e-3, 1 << 14)
    assert not any("still settling" in n for n in postprocess(_sim(ph)).notes)


def test_postprocess_attaches_a_psd_and_a_jitter_number():
    ph = np.random.default_rng(0).normal(0, 1e-4, 1 << 14)
    out = postprocess(_sim(ph))
    assert out.f_psd is not None and out.s_phi_psd is not None
    assert out.jitter_fs > 0


def test_postprocess_skips_the_psd_on_a_short_record():
    out = postprocess(_sim(np.zeros(500)))
    assert out.f_psd is None


def test_postprocess_finds_a_planted_spur():
    fs, n, fo, amp = 100e6, 1 << 15, 4e6, 2e-3
    t = np.arange(n) / fs
    ph = amp * np.sin(TWOPI * fo * t)
    out = postprocess(_sim(ph, fs=fs), settle_frac=0.0, spur_offsets=[fo])
    assert out.spurs_fft[fo] == pytest.approx(20 * np.log10(amp / 2), abs=0.5)
