"""SPLL fractional mode + the three JSSC benchmarks of ex14.

Benchmark bounds are deliberately loose (same policy as test_benchmark.py):
published measurements are class targets for architectural consistency, not
parameter replication — the undisclosed circuit values are assumptions.
"""
import numpy as np
import pytest

from pllsim import presets
from pllsim.arch.cppll import FracConfig
from pllsim.arch.spll import SPLL, SPLLConfig
from pllsim.core.jitter import ldbc_from_sphi


# ------------------------------------------------------- SPLL fractional mode
def test_spll_frac_locks_at_fractional_channel():
    pll = presets.spll_frac_52m_6p253g()
    sim = pll.simulate(60_000, seed=1)
    assert sim.lock_time_s is not None
    f_tail = sim.freq_out[-5000:].mean()
    assert abs(f_tail - pll.cfg.fout) < 1e-4 * pll.cfg.fout
    # the channel is genuinely fractional: no integer N reaches it
    assert abs(pll.cfg.fout / pll.cfg.fref % 1.0 - 0.2503) < 1e-9


def test_spll_frac_config_guards():
    c = presets.spll_frac_52m_6p253g().cfg
    with pytest.raises(ValueError):        # frac mismatch with fout
        SPLLConfig(fref=c.fref, fout=c.fout, osc=c.osc, sampler=c.sampler,
                   filt=c.filt,
                   frac=FracConfig(frac=0.5, mash_order=1, dtc=c.frac.dtc))
    with pytest.raises(ValueError):        # MASH order > 1 rejected
        SPLLConfig(fref=c.fref, fout=c.fout, osc=c.osc, sampler=c.sampler,
                   filt=c.filt,
                   frac=FracConfig(frac=0.2503, mash_order=2, dtc=c.frac.dtc))
    with pytest.raises(ValueError):        # integer-N with fractional fout
        SPLLConfig(fref=c.fref, fout=c.fout, osc=c.osc, sampler=c.sampler,
                   filt=c.filt).n_div


def test_spll_fractionalization_nearly_free():
    """With a calibrated DTC the fractional SPLL pays little over integer-N."""
    frac_pll = presets.spll_frac_52m_6p253g()
    c = frac_pll.cfg
    int_pll = SPLL(SPLLConfig(
        fref=c.fref, fout=120 * c.fref, osc=c.osc, sampler=c.sampler,
        filt=c.filt, ref_pn_dbchz=c.ref_pn_dbchz, fll_i=c.fll_i,
        fll_engage=c.fll_engage, fll_release=c.fll_release,
        int_band=c.int_band))
    ji = int_pll.simulate(80_000, seed=2).jitter_fs
    jf = frac_pll.simulate(80_000, seed=2).jitter_fs
    assert jf < 1.35 * ji, f"fractional penalty too high: {jf:.0f} vs {ji:.0f}"


def test_spll_frac_lms_converges_to_inverse_gain_error():
    pll = presets.spll_frac_52m_6p253g()
    sim = pll.simulate(120_000, seed=3, dtc_gain_init_error=0.08)
    g = sim.cal_traces["dtc_gain"][-1]
    assert abs(g - 1.0 / 1.08) < 0.01 * (1.0 / 1.08)


# ------------------------------------------------- Part 1: Dartizio JSSC 2023
def _dartizio():
    return presets.bench_dartizio23_adpllbb_500m_9p2515g()


def test_dartizio23_consistency():
    """Published: 9.25 GHz fractional channels, < 77 fs rms."""
    pll = _dartizio()
    ar = pll.analyze()
    assert 40 < ar.jitter_fs < 100         # linear under-reads BB loops
    sim = pll.simulate(250_000, seed=3)
    assert 55 < sim.jitter_fs < 105        # published 77 fs class


# ------------------------------------------------ Part 2: Markulic JSSC 2016
def _markulic(frac):
    if frac is None:
        return presets.bench_markulic16_sspll_40m_10p24g()
    assert frac == 0.2503
    return presets.bench_markulic16_sspll_frac_40m_10p25g()


def test_markulic16_consistency():
    """Published: 176 fs integer-N / 198 fs worst fractional at 10.24 GHz."""
    ji = _markulic(None).analyze().jitter_fs
    jf = _markulic(0.2503).analyze().jitter_fs
    assert 130 < ji < 230                  # published 176 fs class
    assert 150 < jf < 260                  # published 198 fs (worst channel)
    assert jf > ji                          # residual makes frac >= int
    assert jf < 1.5 * ji                    # ... but nearly free


# ------------------------------------------------------ Part 3: Wu JSSC 2019
def _wu():
    return presets.bench_wu19_spll_frac_52m_6p253g()


def test_wu19_consistency():
    """Published: 75 fs rms over 10 kHz - 10 MHz, spur < -64 dBc."""
    pll = _wu()
    ar = pll.analyze()
    assert 55 < ar.jitter_fs < 100         # published 75 fs class
    i200k = np.searchsorted(ar.f, 200e3)
    inband = ldbc_from_sphi(ar.pn_breakdown["total"][i200k])
    assert -118 < inband < -107
    sim = pll.simulate(100_000, seed=4, dtc_gain_init_error=0.05)
    assert sim.jitter_fs < 120
    spurs = [v for v in sim.spurs_fft.values() if np.isfinite(v)]
    assert spurs and max(spurs) < -64.0    # published spur bound


# --------------------------------------------- Parts 4-6: the missing archs
# The three architectures the anchor did not cover until 2026-09 (CPPLL,
# ILCM, MDLL).  Their abstracts give no integration band, so the bounds are
# class bounds on what the abstracts do give -- see each preset's docstring.

def test_dadalt03_cppll_spot_phase_noise():
    """Published: L(1 MHz) = -115 dBc/Hz on the 2.488 GHz output.  The
    integer-N CPPLL anchor is the spot, not the (band-less) 860 fs."""
    pll = presets.bench_dadalt03_cppll_311m_2p488g()
    ar = pll.analyze()
    i1m = np.searchsorted(ar.f, 1e6)
    l1m = ldbc_from_sphi(ar.pn_breakdown["total"][i1m])
    assert -118 < l1m < -112, l1m
    assert pll.cfg.n_div == 8
    sim = pll.simulate(60_000, seed=3)
    assert 150 < sim.jitter_fs < 400          # 12 kHz - 20 MHz class


def test_helal09_ilcm_consistency():
    """Published: 130 fs rms integrated, 50 MHz -> 3.2 GHz (x64)."""
    pll = presets.bench_helal09_ilcm_50m_3p2g()
    assert pll.cfg.n_mult == 64
    sim = pll.simulate(60_000, seed=3, f_free_error=1e6)
    assert 90 < sim.jitter_fs < 190          # published 130 fs class


def test_elshazly13_mdll_consistency():
    """Published: 400 fs rms integrated, 375 MHz -> 1.5 GHz (x4)."""
    pll = presets.bench_elshazly13_mdll_375m_1p5g()
    assert pll.cfg.n_mult == 4
    sim = pll.simulate(60_000, seed=3, f_free_error=1e6)
    assert 280 < sim.jitter_fs < 560         # published 400 fs class
