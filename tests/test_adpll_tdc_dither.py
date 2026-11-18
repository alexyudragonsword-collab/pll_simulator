"""Subtractive TDC dither in the TDC-mode ADPLL (issue #80, part 2).

``TDCConfig.dither_lsb`` moves the TDC's sampling instant by a known
pseudo-random k LSB each cycle (a DTC on the reference path) and subtracts
the same k from the code; ``dither_gain_error`` is the DTC's gain error.
Everything below was measured on 2026-11-18 before it was written down.

What it fixes, on fmcw_radar's loop (15 GHz / 100 MHz, 12.2 ps 7-bit TDC,
1 ps jitter):

* On a +-500 MHz / 100 us sawtooth, the part of the error common to all 16
  ramps goes from -2.7..-6.9 dB of the total (0.3-10 MHz, seeds 7-9) to
  -10.3..-14.3 at 1 LSB -- random is -12 -- and to -10.2..-13.1 with
  noise=False, where nothing else dithers.  Band-averaged level within
  0.8 dB of analyze() from 0.3 to 10 MHz.
* At integer N in CW, simulate - analyze (band mean 30-300 kHz) goes from
  +16.8..+17.1 dB to +2.4..+2.9 at 1 LSB, -1.2..-1.55 at 2, -0.2..-0.8 at 3.

Why 1 LSB is not exact: classical subtractive dither whitens a quantizer
whose steps are all equal.  At 12.2 ps a DCO period is 5.46 codes, so the
bin straddling the DCO edge is 0.46 LSB -- and an integer-N loop parks on
that edge.  With a period of exactly 5 codes, 1 LSB reads -0.46..+0.02.
Real TDCs are never an integer number of codes per period, so the notes
count the dither's RMS (0.29 bin per LSB) with the 0.5-bin threshold rather
than trusting an integer width.

The two analyze() additions, each driven to dominance first:

* ``tdc_dither_gain`` (eps * k * t_res left over): band mean -0.42..+0.40 dB
  at 59-80 % of the total.
* ``tdc_dither_mod_residual(f, dev_rms)``: under modulation the TDC's
  codes-per-period normalisation is off by dev/fout, which the dither turns
  into noise of variance dev^2 (sigma_d^2 + T^2/12).  The first version had
  only sigma_d^2 and read 2-3 dB low at narrow dither; with the T^2/12 part,
  constant offsets on a fractional FCW agree to -0.83..+0.23 dB, ramps (with
  the Hann weighting of the deviation) to -0.4..+0.5.
"""
from __future__ import annotations

import math

import numpy as np
import pytest
from scipy.signal import welch

from pllsim.arch.adpll import ADPLL, ADPLLConfig, DLFConfig
from pllsim.blocks.oscillator import OscConfig
from pllsim.blocks.tdc import TDCConfig

FREF = 100e6
NR, SETTLE, NRAMP = 10_000, 3, 16
DEAD = "TDC dead zone"
RAMP = "TDC quantization follows the modulation"


def _issue_loop(lsb=0.0, eps=0.0, jitter=1e-12, t_res=12.2e-12, fout=15e9):
    """fmcw_radar's loop (issue #80), all library defaults."""
    return ADPLL(ADPLLConfig(
        fref=FREF, fout=fout, mode="tdc",
        osc=OscConfig(f0=fout, gain=50e3, pn_dbchz=-95, pn_foffset=1e6,
                      pn_f1f3=300e3, pn_floor_dbchz=-140),
        dlf=DLFConfig(alpha=0.054431567763467366, rho=0.0018658164646583977),
        tdc=TDCConfig(t_res=t_res, n_bits=7, jitter_rms_s=jitter,
                      dither_lsb=lsb, dither_gain_error=eps),
        ref_pn_dbchz=-155.0, int_band=(1e3, 50e6)))


def _quiet_loop(lsb, eps=0.0, fout=15.037e9):
    """A quiet DCO and a 0.5 ps TDC, so a dither term can dominate."""
    return ADPLL(ADPLLConfig(
        fref=FREF, fout=fout, mode="tdc",
        osc=OscConfig(f0=fout, gain=50e3, pn_dbchz=-105, pn_foffset=1e6,
                      pn_f1f3=300e3, pn_floor_dbchz=-150),
        dlf=DLFConfig(alpha=0.054431567763467366, rho=0.0018658164646583977),
        tdc=TDCConfig(t_res=0.5e-12, n_bits=8, dither_lsb=lsb, dither_gain_error=eps),
        ref_pn_dbchz=-165.0, ref_pn_fc=20e3))


def _sawtooth(n_ramps):
    return np.tile(np.linspace(-500e6, 500e6, NR, endpoint=False), n_ramps)


def _ramps(pll, seed, noise=True):
    mod = _sawtooth(SETTLE + NRAMP)
    sim = pll.simulate(mod.size, noise=noise, seed=seed, mod_freq=mod)
    ideal = np.concatenate([[0.0], 2 * np.pi * np.cumsum(mod)[:-1] / FREF])
    segs = (sim.phase_err_out - ideal)[SETTLE * NR:].reshape(NRAMP, NR)
    t = np.arange(NR)
    return np.array([s - np.polyval(np.polyfit(t, s, 1), t) for s in segs]), sim


def _psd(segs):
    w = np.hanning(NR)
    p = 2 * np.abs(np.fft.rfft(segs * w, axis=1)) ** 2 / (FREF * np.sum(w ** 2))
    return np.fft.rfftfreq(NR, 1 / FREF), p


def _band(f, p, f0):
    m = (f > 0.85 * f0) & (f < 1.15 * f0)
    return p[..., m].mean(axis=-1)


OFFS = np.array([3e5, 1e6, 3e6, 1e7])


def _coherent_db(segs):
    f, p = _psd(segs)
    _, pc = _psd(segs.mean(axis=0, keepdims=True))
    return np.array([10 * np.log10(_band(f, pc[0], o) / _band(f, p.mean(0), o))
                     for o in OFFS])


def _cw_band_mean(pll, seed=1, n=400_000):
    f = np.geomspace(3e4, 3e5, 9)
    sim = pll.simulate(n, noise=True, seed=seed)
    total = pll.analyze(f).pn_breakdown["total"]
    return float(np.mean(10 * np.log10(np.interp(f, sim.f_psd, sim.s_phi_psd) / total)))


def _notes(pll, mod=None):
    n = 6 * NR
    return pll.simulate(n, noise=True, seed=1, mod_freq=mod).notes + pll.analyze().notes


# ----------------------------------------------------------- configuration
@pytest.mark.parametrize("kw, msg", [
    (dict(dither_lsb=-1.0), "dither_lsb"),
    (dict(dither_lsb=float("nan")), "dither_lsb"),
    (dict(dither_lsb=1.0, dither_gain_error=-1.0), "dither_gain_error"),
    (dict(dither_gain_error=0.01), "does nothing with dither_lsb = 0"),
])
def test_bad_dither_fields_are_refused(kw, msg):
    with pytest.raises(ValueError, match=msg):
        TDCConfig(t_res=1e-12, **kw)


def test_dtc_bbpd_refuses_a_tdc_dither():
    """Same rule as mod_freq there: refused, not accepted and ignored."""
    import dataclasses

    from pllsim import presets
    base = presets.adpll_bb_100m_10g().cfg
    assert base.mode == "dtc_bbpd"
    with pytest.raises(ValueError, match="dtc_bbpd has no TDC to dither"):
        dataclasses.replace(base, tdc=TDCConfig(t_res=1e-12, dither_lsb=1.0))


def test_off_adds_no_term_and_no_dither():
    pll = _issue_loop()
    assert pll.cfg.tdc.dither_rms_s() == 0.0
    assert "tdc_dither_gain" not in pll.analyze().pn_breakdown
    assert np.all(pll.tdc_dither_mod_residual(np.array([1e5, 1e6]), 3e8) == 0.0)


def test_the_dither_counts_in_the_rms_at_the_tdc_input():
    base = _issue_loop().tdc_dither_rms_s()
    d = _issue_loop(lsb=2.0).tdc_dither_rms_s()
    assert d == pytest.approx(math.hypot(base, 2 * 12.2e-12 / math.sqrt(12)), rel=1e-9)


# ------------------------------------------------------- the random stream
def test_same_seed_same_run_and_it_acts_with_noise_off():
    """A circuit function, so noise=False applies it too; its own stream,
    so the same seed reproduces it."""
    pll = _issue_loop(lsb=1.0)
    a = pll.simulate(20_000, noise=False, seed=5).phase_err_out
    b = pll.simulate(20_000, noise=False, seed=5).phase_err_out
    c = pll.simulate(20_000, noise=False, seed=6).phase_err_out
    off = _issue_loop().simulate(20_000, noise=False, seed=5).phase_err_out
    assert np.array_equal(a, b)
    assert not np.array_equal(a, c)
    assert not np.array_equal(a, off)


# ----------------------------------------------- the ramp: issue #80's case
@pytest.mark.parametrize("noise", [True, False])
def test_one_lsb_makes_the_ramp_error_random(noise):
    """Common part -10.2..-14.3 dB at 0.3-10 MHz (seeds 7-9, both noise
    settings); without dither -2.7..-6.9.  -9 dB is 3 dB short of random
    and 2 dB clear of the worst dithered reading."""
    segs, _ = _ramps(_issue_loop(lsb=1.0), seed=7, noise=noise)
    coh = _coherent_db(segs)
    assert np.all(coh < -9.0), np.round(coh, 1)


def test_with_dither_the_ramp_level_still_agrees():
    pll = _issue_loop(lsb=1.0)
    segs, _ = _ramps(pll, seed=7)
    f, p = _psd(segs)
    total = pll.analyze(OFFS).pn_breakdown["total"]
    d = np.array([10 * np.log10(_band(f, p.mean(0), o) / total[i])
                  for i, o in enumerate(OFFS)])
    assert np.all(np.abs(d) < 1.5), np.round(d, 1)


# ------------------------------------------------- CW at integer N, parked
def test_three_lsb_takes_an_integer_n_loop_out_of_the_dead_zone():
    """+16.8..+17.1 dB without dither; -0.2..-0.8 at 3 LSB (seeds 1-3)."""
    assert abs(_cw_band_mean(_issue_loop(lsb=3.0))) < 1.2


def test_one_lsb_leaves_the_short_edge_bin():
    """The known gap, pinned so it stays visible: +2.4..+2.9 dB at 1 LSB
    with 5.46 codes per DCO period, and the dead-zone note still says so
    (0.30 bin of dither).  The same loop with exactly 5 codes per period
    reads -0.46..+0.02: the theorem holds where its premise does."""
    d = _cw_band_mean(_issue_loop(lsb=1.0))
    assert 1.5 < d < 4.0, d
    assert any(DEAD in n for n in _issue_loop(lsb=1.0).analyze().notes)
    exact = _cw_band_mean(_issue_loop(lsb=1.0, t_res=(1 / 15e9) / 5))
    assert abs(exact) < 0.8, exact


def test_two_lsb_clears_both_notes():
    """0.59 bin of RMS motion at 2 LSB: neither the integer-N dead zone
    (analyze) nor the ramp note (simulate) fires; at 1 LSB both do."""
    one = _notes(_issue_loop(lsb=1.0), _sawtooth(6))
    two = _notes(_issue_loop(lsb=2.0), _sawtooth(6))
    assert any(DEAD in n for n in one) and any(RAMP in n for n in one)
    assert not any(DEAD in n or RAMP in n for n in two)


# ------------------------------------------------- the analyze() additions
@pytest.mark.parametrize("lsb, eps", [(20, 0.5), (20, -0.3)])
def test_the_gain_error_term_matches_simulate(lsb, eps):
    """tdc_dither_gain at 59-80 % of the total: band mean within 0.42 dB."""
    pll = _quiet_loop(lsb, eps)
    f = np.geomspace(3e4, 3e6, 9)
    bd = pll.analyze(f).pn_breakdown
    assert np.min(bd["tdc_dither_gain"] / bd["total"]) > 0.55
    sim = pll.simulate(200_000, seed=1)
    d = np.mean(10 * np.log10(np.interp(f, sim.f_psd, sim.s_phi_psd) / bd["total"]))
    assert abs(d) < 1.0, d


@pytest.mark.parametrize("lsb", [60, 200])
def test_the_modulation_residual_matches_a_constant_offset(lsb):
    """+500 MHz held through two-point modulation on a fractional FCW, so
    the TDC phase sweeps the period.  Measured -0.83..-0.12 dB with the
    T^2/12 part; without it 60 LSB read +3.0..+3.3 dB over the prediction."""
    pll = _quiet_loop(lsb)
    f = np.geomspace(3e4, 3e6, 9)
    total = pll.analyze(f).pn_breakdown["total"]
    mr = pll.tdc_dither_mod_residual(f, 500e6)
    assert np.min(mr / (total + mr)) > 0.45
    n = 200_000
    mod = np.full(n, 500e6)
    sim = pll.simulate(n, seed=1, mod_freq=mod)
    ph = (sim.phase_err_out - np.concatenate([[0.0], 2 * np.pi * np.cumsum(mod)[:-1] / FREF]))
    ph = ph[n // 4:]
    t = np.arange(ph.size)
    fw, p = welch(ph - np.polyval(np.polyfit(t, ph, 1), t), fs=FREF, nperseg=1 << 14)
    d = np.mean(10 * np.log10(np.interp(f, fw, p) / (total + mr)))
    assert abs(d) < 1.2, d


def test_the_modulation_residual_for_issue_80s_loop():
    """Algebra on the convention: sampled white, 2 sigma^2/fref on
    tdc_quant's path, so the ratio is sigma^2 / (t_res^2/12) at every
    offset.  For 1 LSB of 12.2 ps and a +-500 MHz sawtooth (289 MHz RMS):
    -19.5 dB under tdc_quant, not the -34 dB first estimated on the issue
    from the sigma_d part alone."""
    pll = _issue_loop(lsb=1.0)
    f = np.geomspace(1e4, 1e7, 30)
    q = pll.analyze(f).pn_breakdown["tdc_quant"]
    dev = 500e6 / math.sqrt(3)
    mr = pll.tdc_dither_mod_residual(f, dev)
    sig_ui = dev * math.hypot(12.2e-12 / math.sqrt(12), 1 / (15e9 * math.sqrt(12)))
    want = sig_ui ** 2 / ((12.2e-12 * 15e9) ** 2 / 12)
    assert mr / q == pytest.approx(np.full_like(f, want), rel=1e-9)
    assert 10 * math.log10(want) == pytest.approx(-19.5, abs=0.1)
