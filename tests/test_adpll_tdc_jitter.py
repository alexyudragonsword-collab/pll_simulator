"""TDC jitter and the TDC dead zone in the TDC-mode ADPLL (issue #76).

fmcw_radar found two things, both reproduced here to the decibel:

* ``tdc.jitter_rms_s`` acted only in simulate().  analyze() had no term for
  it, so its total was identical from 0 to 5 ps of jitter -- an impairment
  with one of its two paths, which is how a parameter becomes decorative.
* In integer-N with nothing to dither the TDC, the loop parks inside one
  bin and simulate() reads up to ~17 dB more in band than analyze()'s white
  t_res^2/12.  That is a validity limit of the linear model, now flagged by
  ``core.boundaries.tdc_dead_zone`` (a note here, a boundary in the sweep).

Checking the jitter term turned up a third thing, on the simulate() side:
in integer-N the loop locks with the TDC at its range edge, and the kernel
clamped TDC jitter there instead of wrapping it, reading 5-6 dB low with
the jitter dominant.  The jitter is input-referred, so it now shifts the
sampling instant like reference jitter does, and the wrap test below holds
all three phase patterns (integer, 0.5, 0.37) to the same agreement.
"""
from __future__ import annotations

import copy

import numpy as np
import pytest

from pllsim import presets
from pllsim.arch.adpll import ADPLL, ADPLLConfig, DLFConfig
from pllsim.blocks.oscillator import OscConfig
from pllsim.blocks.tdc import TDCConfig
from pllsim.core.boundaries import TDC_DITHER_BINS, tdc_dead_zone


def _issue_loop(jitter_rms_s=0.0, fout=15e9, t_res=5e-12, pn=-95.0, n_bits=7,
                floor=-140.0, ref=-155.0):
    """The 15 GHz / 100 MHz loop of issue #76, parametrised."""
    return ADPLL(ADPLLConfig(
        fref=100e6, fout=fout,
        osc=OscConfig(f0=fout, gain=50e3, pn_dbchz=pn, pn_foffset=1e6,
                      pn_f1f3=300e3, pn_floor_dbchz=floor),
        dlf=DLFConfig(alpha=0.054431567763467366, rho=0.0018658164646583977),
        mode="tdc",
        tdc=TDCConfig(t_res=t_res, n_bits=n_bits, jitter_rms_s=jitter_rms_s),
        ref_pn_dbchz=ref, ref_pn_fc=20e3))


def _dead_zone_noted(pll) -> bool:
    return any("TDC dead zone" in n for n in pll.analyze().notes)


# ------------------------------------------------------------ the jitter term
def test_analyze_has_a_tdc_jitter_term_only_when_there_is_jitter():
    """An impairment that is not configured is an absent key, not a zero."""
    assert "tdc_jitter" not in _issue_loop(0.0).analyze().pn_breakdown
    assert "tdc_jitter" in _issue_loop(1e-12).analyze().pn_breakdown


def test_the_total_now_moves_with_tdc_jitter():
    """The defect as reported: the total was identical from 0 to 5 ps."""
    f = np.geomspace(3e4, 1e7, 20)
    t0 = _issue_loop(0.0).analyze(f).pn_breakdown["total"]
    t5 = _issue_loop(5e-12).analyze(f).pn_breakdown["total"]
    assert np.all(t5 > t0)


@pytest.mark.parametrize("sigma", [0.3e-12, 2e-12, 20e-12])
def test_tdc_jitter_is_tdc_quant_with_sigma_for_q_over_sqrt12(sigma):
    """Same path, same sampled-white convention (2 sigma^2 / fref): the
    ratio of the two terms is exactly sigma^2 / (t_res^2 / 12) at every
    offset.  Algebra, so 1e-12."""
    bd = _issue_loop(sigma).analyze(np.geomspace(1e3, 4e7, 50)).pn_breakdown
    ratio = bd["tdc_jitter"] / bd["tdc_quant"]
    assert ratio == pytest.approx(np.full_like(ratio, sigma**2 / (5e-12**2 / 12)),
                                  rel=1e-12)


@pytest.mark.parametrize("label, fout", [
    ("integer: the TDC parks at its range edge", 15.0e9),
    ("fraction 0.5: at the edge every other cycle", 15.05e9),
])
def test_tdc_jitter_wraps_at_the_range_edge_instead_of_being_clipped(label, fout):
    """The jitter is input-referred: timing noise on the TDC's input edge.
    It has to move the sampling instant -- count and fraction together, as
    reference jitter already does -- so that a sample pushed across a DCO
    edge wraps to the previous edge rather than being clamped at code 0.

    Until 2026-11-12 the kernel took the count first, added the jitter to
    the fraction only and clamped at 0.  An integer-N loop locks with the
    TDC at about 0, its range edge, so part of the jitter was cut: measured
    -5.33 dB (integer) and -2.74 dB (0.5) on this test before the fix,
    +0.33..+0.68 and +0.32..+0.70 after (seeds 1-3).  Same configuration
    and tolerance as the dominance test.
    """
    pll = _issue_loop(5e-12, fout=fout, t_res=0.5e-12, pn=-105.0,
                      n_bits=8, floor=-150.0, ref=-165.0)
    f = np.geomspace(3e4, 3e6, 9)
    bd = pll.analyze(f).pn_breakdown
    assert np.min(bd["tdc_jitter"] / bd["total"]) > 0.9, "jitter is not dominant"
    sim = pll.simulate(200_000, noise=True, seed=1)
    d = 10 * np.log10(np.interp(f, sim.f_psd, sim.s_phi_psd) / bd["total"])
    assert abs(d.mean()) < 1.5, f"{label}: band-mean {d.mean():+.2f} dB: {np.round(d, 1)}"


@pytest.mark.parametrize("seed", [1, 2])
def test_with_tdc_jitter_dominant_the_two_domains_agree(seed):
    """Drive the source to dominance before comparing (CONTRIBUTING).

    5 ps of jitter on a 0.5 ps bin with a quiet DCO puts tdc_jitter at 98 %
    of the in-band budget; a fractional FCW (0.37) sweeps the TDC phase
    across the period.  Measured 2026-11-12, 200k cycles, mean over 9
    log-spaced offsets 30 kHz-3 MHz: +0.35 / +0.57 / +0.71 dB at seeds 1-3
    (integer FCW +0.33..+0.68, fraction 0.5 +0.32..+0.70).  Without the
    term analyze() would read ~17 dB low, so 1.5 dB is ~2x the spread and
    a tenth of the defect.
    """
    pll = _issue_loop(5e-12, fout=15.037e9, t_res=0.5e-12, pn=-105.0,
                      n_bits=8, floor=-150.0, ref=-165.0)
    f = np.geomspace(3e4, 3e6, 9)
    bd = pll.analyze(f).pn_breakdown
    assert np.min(bd["tdc_jitter"] / bd["total"]) > 0.9, "jitter is not dominant"
    sim = pll.simulate(200_000, noise=True, seed=seed)
    d = 10 * np.log10(np.interp(f, sim.f_psd, sim.s_phi_psd) / bd["total"])
    assert abs(d.mean()) < 1.5, f"band-mean {d.mean():+.2f} dB: {np.round(d, 1)}"


# ----------------------------------------------------------- the dead zone
def test_the_issue_loop_is_flagged_and_its_excess_is_real():
    """The report's own configuration: no jitter, integer-N, 0.08 bin of
    dither.  The note fires, and simulate() really does read the ~16 dB
    excess it warns about (measured +15.8 dB at 30 and 100 kHz, 400k
    cycles, seed 3; 10 dB is the floor of what 'dead zone' means here)."""
    pll = _issue_loop(0.0)
    assert pll.tdc_dither_rms_s() / 5e-12 < 0.1
    assert _dead_zone_noted(pll)
    f = np.array([3e4, 1e5])
    sim = pll.simulate(400_000, noise=True, seed=3)
    d = 10 * np.log10(np.interp(f, sim.f_psd, sim.s_phi_psd)
                      / pll.analyze(f).pn_breakdown["total"])
    assert np.all(d > 10.0), np.round(d, 1)


@pytest.mark.parametrize("why, pll", [
    ("one bin of TDC jitter", _issue_loop(5e-12)),
    ("fractional FCW", _issue_loop(0.0, fout=15.037e9)),
    ("a TDC fine enough for the DCO noise to cross bins", _issue_loop(0.0, t_res=0.5e-12, n_bits=8)),
    ("the stock preset (fractional)", presets.adpll_100m_10g()),
])
def test_no_note_where_something_dithers_the_tdc(why, pll):
    assert not _dead_zone_noted(pll), why


def test_the_stock_loop_at_integer_n_is_flagged_although_it_agrees():
    """The documented false positive, kept visible so the note's wording
    stays honest: 0.20 bin, flagged, and measured within 0.6 dB (the
    adpll-intn sweep point holds the measurement)."""
    p = copy.deepcopy(presets.adpll_100m_10g())
    p.cfg.fout = round(p.cfg.fout / p.cfg.fref) * p.cfg.fref
    assert 0.15 < p.tdc_dither_rms_s() / p.cfg.tdc.t_res < TDC_DITHER_BINS
    notes = [n for n in p.analyze().notes if "TDC dead zone" in n]
    assert notes and "+0.3 dB" in notes[0]


@pytest.mark.parametrize("fcw, dither_bins, want", [
    (150.0, 0.1, True), (150.0, 0.49, True), (150.0, 0.5, False),
    (150.0, 2.0, False), (150.37, 0.1, False), (150.0 + 1e-6, 0.1, False),
])
def test_the_predicate(fcw, dither_bins, want):
    assert tdc_dead_zone(fcw, 5e-12, dither_bins * 5e-12) is want


def test_dither_excludes_the_quantizers_and_adds_the_jitter():
    """The dither is what moves the phase across bins: the TDC's own jitter
    and the loop's random phase error, not tdc_quant / dco_quant (which
    stop being random once the code stops changing)."""
    base = _issue_loop(0.0).tdc_dither_rms_s()
    with_j = _issue_loop(3e-12).tdc_dither_rms_s()
    assert with_j == pytest.approx(np.hypot(base, 3e-12), rel=1e-9)
    # coarsening the TDC grows tdc_quant 100x in power, not the dither
    assert _issue_loop(0.0, t_res=50e-12, n_bits=4).tdc_dither_rms_s() == \
        pytest.approx(base, rel=1e-6)
