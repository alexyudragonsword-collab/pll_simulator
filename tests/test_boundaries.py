"""The runtime boundary notes: each fires under its condition and only then.

These are the user-facing half of the boundary registry -- the sweep asserts
the flags, a person in any of the three GUIs sees these notes.  Positive and
negative case for each, per the break-it-first doctrine.
"""
from __future__ import annotations

import pytest

from pllsim import presets
from pllsim.core.freqresp import LoopMetrics
from pllsim.synth import retune_loop
from pllsim.validation import NotLockedError, compare_domains

# ------------------------------------------------- jitter-band-clip note

def test_clipped_jitter_band_is_announced():
    """int_band 100 MHz vs a 19.2 MHz record: 8.64 vs 100 MHz integrals sat
    side by side in every GUI with nothing saying so."""
    sim = presets.ALL_PRESETS["cppll_19p2m_4p8g"]().simulate(30_000, seed=1)
    assert any("only over the common band" in n for n in sim.notes), sim.notes


def test_unclipped_jitter_band_stays_quiet():
    """ILCM at fref=250 MHz: 0.45*fs = 112.5 MHz > the 100 MHz band."""
    sim = presets.ALL_PRESETS["ilcm_250m_12g"]().simulate(
        30_000, seed=1, f_free_error=2e6)
    assert not any("only over the common band" in n for n in sim.notes)


# ------------------------------------------------------ no-fine-record note

@pytest.mark.parametrize("name", ["cppll_19p2m_4p8g", "sspll_19p2m_4p8g",
                                  "spll_100m_8g"])
def test_m1_run_says_the_reference_spur_is_absent(name):
    """ILCM/MDLL said this from the start; the three pulse-ripple archs ran
    at M=1 silently."""
    sim = presets.ALL_PRESETS[name]().simulate(30_000, seed=1)
    assert any("aliases to DC" in n for n in sim.notes), sim.notes


def test_fine_run_does_not_claim_the_spur_is_absent():
    sim = presets.ALL_PRESETS["cppll_19p2m_4p8g"]().simulate(
        20_000, seed=1, fine_oversample=32)
    assert not any("aliases to DC" in n for n in sim.notes), sim.notes


# ----------------------------------------------------------- ct-approx note

def test_spll_warns_past_the_ct_boundary():
    """The SPLL is continuous-time like the CPPLL, and was the only CT
    architecture without this warning -- while the README claimed it had
    one.  Both statements are now true."""
    pll = presets.ALL_PRESETS["spll_100m_8g"]()
    # pm_deg=45: at the stock PM target the optimizer cannot land a loop
    # past fref/10 at all -- itself a statement about how aggressive this is
    retune_loop(pll, pll.cfg.fref / 9.5, pm_deg=45)
    ar = pll.analyze()
    assert any("continuous-time" in n for n in ar.notes), ar.notes


def test_spll_stays_quiet_inside_the_ct_boundary():
    ar = presets.ALL_PRESETS["spll_100m_8g"]().analyze()
    assert not any("continuous-time" in n for n in ar.notes), ar.notes


# ------------------------------------------------ conditional-stability note

def test_multiple_crossings_are_announced(monkeypatch):
    """No stock preset is conditionally stable (measured: all four report
    n_crossings=1 since the image-counting fix), so the condition is
    injected at the metrics seam."""
    from pllsim.arch import cppll as mod
    real = mod.loop_metrics

    def fake(gol, f_limit=None):
        m = real(gol, f_limit=f_limit)
        return LoopMetrics(f_ugb=m.f_ugb, pm_deg=m.pm_deg, gm_db=m.gm_db,
                           f_3db=m.f_3db, peaking_db=m.peaking_db,
                           n_crossings=3)
    monkeypatch.setattr(mod, "loop_metrics", fake)
    ar = presets.ALL_PRESETS["cppll_19p2m_4p8g"]().analyze()
    assert any("conditionally stable" in n for n in ar.notes), ar.notes


def test_single_crossing_stays_quiet():
    ar = presets.ALL_PRESETS["cppll_19p2m_4p8g"]().analyze()
    assert not any("conditionally stable" in n for n in ar.notes)


# ----------------------------------------------------------- not-locked guard

def test_an_unlocked_loop_is_refused_not_compared():
    """Off-plan fractional configs mostly never lock; the calibration sweep
    read +25..48 dB "deviations" off them before this guard existed --
    numbers that measured nothing but an unlocked loop wandering."""
    import copy
    pll = presets.ALL_PRESETS["sspll_frac_19p2m_4p806g"]()
    p = copy.deepcopy(pll)
    p.cfg.fref *= 0.5
    with pytest.raises(NotLockedError, match="never locked"):
        compare_domains(p, n_cycles=40_000, seed=1)


def test_a_locked_loop_is_not_refused():
    c = compare_domains(presets.ALL_PRESETS["sspll_frac_19p2m_4p806g"](),
                        n_cycles=40_000, seed=1)
    assert c.bands
