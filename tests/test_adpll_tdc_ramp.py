"""A TDC-mode ADPLL on a frequency ramp (issue #80, fmcw_radar).

A sawtooth chirp sweeps the TDC across its bins, and the library used to
say that this dithers the TDC.  It does not: the sweep is deterministic and
repeats every ramp, so with under half a bin of random dither the TDC
quantization error follows the ramp.  Its PSD level still agrees with
analyze(); what fails is its randomness -- the part common to every ramp
is a few dB under the total instead of 1/n_ramps of it, and a radar's
coherent integration over ramps turns that part into ghost targets.

Measured 2026-11-18, the issue's loop (15 GHz / 100 MHz, 12.2 ps 7-bit
TDC), sawtooth -500..+500 MHz over 10 000 reference cycles, 3 ramps dropped
then 16 kept, each ramp linearly detrended and Hann-windowed; "coherent"
is the PSD of the ramp-averaged residual over the mean ramp PSD, each
averaged over +-15 % around the offset (random noise: 1/16 = -12 dB):

    TDC jitter (bins)   0.3 / 1 / 3 / 10 MHz coherent, seeds 1-3
    1 ps    (0.09)      -3.2..-3.6 / -7.1..-8.4 / -3.2..-3.8 / -5.2 dB
    2.44 ps (0.20)      -7.7..-9.7 / -9.3..-11.8 / -7.7..-8.9 / -8.6..-9.0
    6.5 ps  (0.53)      -11.3..-12.8 / -11.6..-12.6 / -11.2..-12.4 / -11.7..-12.1
    0.1 ps TDC, none    -10.7 / -14.0 / -11.3 / -11.8  (seed 7: the floor)

Band-averaged PSD level against analyze() at 1 ps: within 1.5 dB from
0.3 to 10 MHz, -2.4..-3.4 dB at 100 kHz (seeds 1-3).

Found on the way, and fixed here: the lock check compared the record's
tail with fout without taking the modulation out, so every sawtooth chirp
whose tail sat on the upper half of the ramp read "loop never reached the
configured fout" -- hundreds of MHz off.
"""
from __future__ import annotations

import numpy as np
import pytest

from pllsim import presets
from pllsim.arch.adpll import ADPLL, ADPLLConfig, DLFConfig
from pllsim.blocks.oscillator import OscConfig
from pllsim.blocks.tdc import TDCConfig
from pllsim.core.boundaries import ferr_signed, tail_frequency_error

FREF, FOUT = 100e6, 15e9
NR = 10_000                 # cycles per ramp: 100 us
SETTLE, NRAMP = 3, 16
LOCK_NOTE = "loop never reached the configured fout"
RAMP_NOTE = "TDC quantization follows the modulation"


def _loop(jitter_rms_s, t_res=12.2e-12, n_bits=7, osc=None):
    """The 60 GHz chain's 15 GHz loop of issue #80, all library defaults."""
    return ADPLL(ADPLLConfig(
        fref=FREF, fout=FOUT, mode="tdc",
        osc=osc or OscConfig(f0=FOUT, gain=50e3, pn_dbchz=-95, pn_foffset=1e6,
                             pn_f1f3=300e3, pn_floor_dbchz=-140),
        dlf=DLFConfig(alpha=0.054431567763467366, rho=0.0018658164646583977),
        tdc=TDCConfig(t_res=t_res, n_bits=n_bits, jitter_rms_s=jitter_rms_s),
        ref_pn_dbchz=-155.0, int_band=(1e3, 50e6)))


def _sawtooth(n_ramps, dev=500e6):
    return np.tile(np.linspace(-dev, dev, NR, endpoint=False), n_ramps)


def _ramp_residuals(pll, seed):
    """Per-ramp detrended phase residual [rad], shape (NRAMP, NR)."""
    mod = _sawtooth(SETTLE + NRAMP)
    sim = pll.simulate(mod.size, noise=True, seed=seed, mod_freq=mod)
    # phase_err_out[n] carries mod[0..n-1]: one cycle behind the cumsum
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


def _coherent_db(segs, offs):
    f, p = _psd(segs)
    _, pc = _psd(segs.mean(axis=0, keepdims=True))
    return np.array([10 * np.log10(_band(f, pc[0], o) / _band(f, p.mean(0), o))
                     for o in offs])


OFFS = np.array([3e5, 1e6, 3e6, 1e7])


# --------------------------------------------------------- the measurement
def test_under_a_tenth_of_a_bin_the_error_repeats_with_the_ramp():
    """1 ps on 12.2 ps: 0.09 bin.  At 300 kHz and 3 MHz the part common to
    all 16 ramps is 3.2-3.8 dB under the total (seeds 1-3), against 12 dB
    if it were random.  -6 dB keeps 2 dB of margin and stays 6 dB clear of
    random."""
    pll = _loop(1e-12)
    assert pll.tdc_dither_rms_s() / 12.2e-12 < 0.1
    segs, _ = _ramp_residuals(pll, seed=1)
    coh = _coherent_db(segs, OFFS)
    assert coh[0] > -6.0 and coh[2] > -6.0, np.round(coh, 1)


def test_at_half_a_bin_of_jitter_the_error_is_random_again():
    """6.5 ps: 0.53 bin.  -11.2..-12.8 dB at every offset (seeds 1-3), the
    1/16 of random noise; a near-ideal 0.1 ps TDC reads the same."""
    segs, _ = _ramp_residuals(_loop(6.5e-12), seed=1)
    coh = _coherent_db(segs, OFFS)
    assert np.all(coh < -10.0), np.round(coh, 1)


def test_the_psd_level_still_agrees_with_analyze():
    """The level is not what fails: band-averaged, within 1.5 dB of
    analyze() from 0.3 to 10 MHz at 0.09 bin (seeds 1-3).  This is why the
    case is a simulate() note and not a cross-domain boundary."""
    pll = _loop(1e-12)
    segs, _ = _ramp_residuals(pll, seed=1)
    f, p = _psd(segs)
    total = pll.analyze(OFFS).pn_breakdown["total"]
    d = np.array([10 * np.log10(_band(f, p.mean(0), o) / total[i])
                  for i, o in enumerate(OFFS)])
    assert np.all(np.abs(d) < 2.5), np.round(d, 1)


# ------------------------------------------------------------- the notes
def _notes(pll, mod, seed=1):
    return pll.simulate(mod.size, noise=True, seed=seed, mod_freq=mod).notes


def test_the_ramp_note_fires_under_half_a_bin_with_modulation():
    notes = [n for n in _notes(_loop(1e-12), _sawtooth(6)) if RAMP_NOTE in n]
    assert len(notes) == 1 and "0.09 TDC bins" in notes[0]


@pytest.mark.parametrize("why, pll, mod", [
    ("half a bin of TDC jitter", _loop(6.5e-12), _sawtooth(6)),
    ("no modulation", _loop(1e-12), None),
    ("an all-zero mod_freq is not modulation", _loop(1e-12), np.zeros(6 * NR)),
])
def test_no_ramp_note(why, pll, mod):
    n = 6 * NR
    sim = pll.simulate(n, noise=True, seed=1, mod_freq=mod)
    assert not any(RAMP_NOTE in x for x in sim.notes), why


def test_the_analyze_note_no_longer_says_a_ramp_dithers():
    """The integer-N dead-zone note used to say a ramp dithers the TDC."""
    note = next(n for n in _loop(1e-12).analyze().notes if "TDC dead zone" in n)
    assert "does not dither it" in note
    assert "ramp or two-point modulation dithers" not in note


# ----------------------------------------------------- the lock check
@pytest.mark.parametrize("jitter", [1e-12, 6.5e-12])
def test_a_locked_chirp_is_not_reported_as_unlocked(jitter):
    """Before the fix: the last 5000 cycles sit on the upper half of the
    ramp, mean +250 MHz, and every run read 'never reached fout'."""
    assert not any(LOCK_NOTE in n for n in _notes(_loop(jitter), _sawtooth(6)))


def test_a_chirp_the_dco_cannot_follow_is_still_reported():
    """A +-1000-code tuning range is +-50 MHz: it cannot follow +-500 MHz."""
    osc = OscConfig(f0=FOUT, gain=50e3, pn_dbchz=-95, pn_foffset=1e6,
                    v_min=-1000, v_max=1000)
    assert any(LOCK_NOTE in n for n in _notes(_loop(6.5e-12, osc=osc), _sawtooth(6)))


def test_a_sawtooth_on_the_sspll_is_not_reported_as_unlocked():
    """The SSPLL takes mod_freq through the same postprocess.  +-2 MHz over
    20 000 cycles: the 5000-cycle tail is the ramp's top quarter, +1.5 MHz,
    far past fref/1000 = 19.2 kHz.  With the modulation taken out the tail
    reads +0.1 kHz (residual 5.6 kHz rms at lag 0).  At +-20 MHz this loop
    really does not follow (1.7 MHz rms residual), and is reported."""
    pll = presets.sspll_19p2m_4p8g()
    n = 80_000
    mod = np.tile(np.linspace(-2e6, 2e6, 20_000, endpoint=False), n // 20_000)
    assert not any(LOCK_NOTE in x for x in pll.simulate(n, seed=1, mod_freq=mod).notes)


def test_ferr_takes_the_modulation_out_sample_for_sample():
    rng = np.random.default_rng(0)
    mod = rng.uniform(-5e8, 5e8, 40_000)
    assert ferr_signed(FOUT + mod + 1e3, FOUT, mod) == pytest.approx(1e3, abs=1e-3)
    assert tail_frequency_error(FOUT + mod, FOUT) > 1e6     # without it
    # a shorter mod_freq leaves the rest of the record alone
    assert ferr_signed(np.full(100, FOUT + 7.0), FOUT, np.ones(10)) == pytest.approx(7.0)
