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


# --- never reached fout ---------------------------------------------------
# An audit of fref/fout-only edits found ILCM and MDLL silently railing: the
# configured fout is a legal integer multiple, the oscillator's digital tuning
# cannot reach it, and the run read as an ordinary result 2.4 GHz off target
# (MDLL fout x2) with no lock detector to hint otherwise.  Every architecture
# goes through postprocess, so the check lives there and shares its criterion
# with compare_domains' NotLockedError.

def test_a_loop_that_never_reaches_fout_says_so():
    pll = presets.ALL_PRESETS["mdll_150m_2p4g"]()
    pll.cfg.fout *= 2                       # N = 32, legal; ring cannot get there
    sim = pll.simulate(8_000, seed=1)
    assert any("never reached" in n for n in sim.notes), sim.notes


def test_ilcm_out_of_range_fout_says_so():
    pll = presets.ALL_PRESETS["ilcm_250m_12g"]()
    pll.cfg.fout *= 2                       # 24 GHz, N = 48; FTL range is Hz-level
    sim = pll.simulate(8_000, seed=1)
    assert any("never reached" in n for n in sim.notes), sim.notes


@pytest.mark.parametrize("name", [n for n in presets.ALL_PRESETS
                                  if not n.startswith("bench_")])
def test_stock_presets_reach_fout_and_stay_quiet(name):
    sim = presets.ALL_PRESETS[name]().simulate(8_000, seed=1)
    assert not any("never reached" in n for n in sim.notes), sim.notes


def test_never_locked_predicate_threshold():
    from pllsim.core.boundaries import LOCK_FERR_FRACTION, never_locked
    fref = 100e6
    assert never_locked(1.01 * LOCK_FERR_FRACTION * fref, fref)
    assert not never_locked(0.99 * LOCK_FERR_FRACTION * fref, fref)


def test_mdll_simulate_refuses_a_non_integer_multiple():
    # analyze() and both ILCM paths already refused; simulate() ran with a
    # rounded multiple and reported a result 154 MHz off target
    pll = presets.ALL_PRESETS["mdll_150m_2p4g"]()
    pll.cfg.fout *= 1.07
    with pytest.raises(ValueError, match="integer fout/fref"):
        pll.simulate(2_000, seed=1)


# --- flicker synthesis floor ----------------------------------------------
# The boundary register listed flicker-floor with "a runtime warning note all
# three GUIs show" -- and no engine ever emitted one.  It only becomes true
# on long records: the Welch resolution has to drop below fref/65536 before
# the integration band can reach the floor at all (>= 8 x 65536 cycles at
# fref > 65.5 MHz), which is why no stock run ever showed it.

def _synthetic(n: int, fs: float = 100e6, seed: int = 1):
    import numpy as np

    from pllsim.core.results import SimResult
    rng = np.random.default_rng(seed)
    return SimResult(fs=fs, f0=8e9, t=np.arange(n) / fs,
                     phase_err_out=rng.normal(0.0, 1e-3, n),
                     freq_out=np.full(n, 8e9), ctrl=np.zeros(n),
                     lock_time_s=1e-6)


def test_a_long_record_with_flicker_says_where_its_floor_is():
    from pllsim.core.boundaries import flicker_floor_hz
    from pllsim.core.engine import postprocess
    # postprocess analyses the settled 75%: 600k samples -> nperseg 75000 ->
    # Welch RBW 1.33 kHz, under the fref/65536 = 1.53 kHz floor.  At 600k
    # cycles total (450k settled) the RBW is still 1.78 kHz and nothing fires.
    n = 800_000
    sim = postprocess(_synthetic(n), int_band=(1e3, 1e8), flicker_corner_hz=2e5)
    hits = [x for x in sim.notes if "flicker synthesis floor" in x]
    assert hits, sim.notes
    assert f"{flicker_floor_hz(100e6, n):.3g}" in hits[0], hits[0]


def test_no_flicker_configured_means_no_floor_note():
    from pllsim.core.engine import postprocess
    sim = postprocess(_synthetic(600_000), int_band=(1e3, 1e8), flicker_corner_hz=0.0)
    assert not any("flicker synthesis floor" in x for x in sim.notes), sim.notes


def test_a_short_record_never_reaches_the_floor():
    from pllsim.core.engine import postprocess
    sim = postprocess(_synthetic(120_000), int_band=(1e3, 1e8), flicker_corner_hz=2e5)
    assert not any("flicker synthesis floor" in x for x in sim.notes), sim.notes


@pytest.mark.parametrize("name", ["cppll_19p2m_4p8g", "sspll_19p2m_4p8g",
                                  "spll_100m_8g", "adpll_100m_10g",
                                  "ilcm_250m_12g", "mdll_150m_2p4g"])
def test_every_engine_tells_postprocess_its_flicker_corner(name, monkeypatch):
    # a note that no engine can trigger is decorative: each engine must hand
    # postprocess a positive corner from its own noise configuration
    import importlib
    pll = presets.ALL_PRESETS[name]()
    mod = importlib.import_module(type(pll).__module__)
    seen = {}
    real = mod.postprocess

    def spy(sim, *a, **kw):
        seen.update(kw)
        return real(sim, *a, **kw)
    monkeypatch.setattr(mod, "postprocess", spy)
    pll.simulate(3_000, seed=1)
    assert seen.get("flicker_corner_hz", 0.0) > 0.0, seen
