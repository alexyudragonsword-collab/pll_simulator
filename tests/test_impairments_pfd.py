"""PFD/CP second-order effects, divider retiming and the lock detector.

Each test drives the impairment hard enough that a model which ignored it
would give a visibly different answer -- the failure mode these guard against
is a knob that is accepted, stored and never read.
"""
from dataclasses import replace

import numpy as np
import pytest

from pllsim import presets
from pllsim.blocks.chargepump import CPConfig
from pllsim.blocks.lockdetect import LockDetectConfig, LockDetector, LockStats


# ------------------------------------------------- control-voltage dependence
def test_mismatch_tracks_the_control_voltage():
    cp = CPConfig(icp=300e-6, mismatch_pct=0.0, mismatch_slope_pct_v=4.0, v_ref=0.6)
    assert cp.mismatch_at(0.6) == pytest.approx(0.0)
    assert cp.mismatch_at(1.1) == pytest.approx(2.0)
    assert cp.mismatch_at(0.1) == pytest.approx(-2.0)
    assert cp.v_dependent


def test_reference_spur_is_a_v_shape_across_channels():
    """The measurement a constant mismatch cannot reproduce.

    With mismatch crossing zero mid-range the spur has a minimum at the
    crossing channel and rises toward both edges of the tuning range.  A
    constant mismatch gives one number for every channel, which is the answer
    that never matches silicon.
    """
    p = presets.cppll_19p2m_4p8g()
    v_mid = p.cfg.osc.v_for(p.cfg.fout)
    p.cfg.cp = replace(p.cfg.cp, mismatch_pct=0.0, leakage_a=0.0,
                       mismatch_slope_pct_v=6.0, v_ref=v_mid)
    # +/-2 channels either side of the crossing == +/-0.64 V of tuning here
    fouts = p.cfg.fout + p.cfg.fref * np.array([-2.0, -1.0, 0.0, 1.0, 2.0])
    spur = p.ref_spur_vs_channel(fouts)          # keys are snapped channels
    assert len(spur) == 5
    vals = list(spur.values())
    assert np.argmin(vals) == 2, f"minimum should sit at the crossing: {vals}"
    assert vals[2] == float("-inf"), "mismatch is exactly zero at the crossing"
    assert vals[0] > vals[1] and vals[-1] > vals[-2], f"not a V-shape: {vals}"


def test_constant_mismatch_gives_the_same_spur_everywhere():
    """The contrast case: without a slope, every channel reads identically."""
    p = presets.cppll_19p2m_4p8g()
    p.cfg.cp = replace(p.cfg.cp, mismatch_pct=2.0, leakage_a=0.0)
    vals = list(p.ref_spur_vs_channel(
        p.cfg.fout + p.cfg.fref * np.array([-2.0, 0.0, 2.0])).values())
    assert max(vals) - min(vals) < 0.5


# ----------------------------------------------------------------- dead zone
def test_dead_zone_suppresses_the_error_charge_only():
    cp = CPConfig(icp=300e-6, mismatch_pct=2.0, dead_zone_s=50e-12)
    from pllsim.blocks.chargepump import ChargePump
    blk = ChargePump(cp, 1 / 19.2e6, np.random.default_rng(0), noise=False)
    inside = blk.charge(10e-12)
    outside = blk.charge(200e-12)
    # the mismatch charge still flows inside the dead zone; the phase-dependent
    # part does not, so the two differ by exactly the error term
    assert inside == pytest.approx(cp.icp * 0.02 * cp.t_reset)
    assert outside > inside * 5


def test_dead_zone_degrades_in_band_noise():
    """A gainless window is a real noise penalty, and the sim has to show it."""
    p = presets.cppll_19p2m_4p8g()
    clean = p.simulate(30000, seed=3).jitter_fs
    p.cfg.cp = replace(p.cfg.cp, dead_zone_s=20e-12)
    dirty = p.simulate(30000, seed=3).jitter_fs
    assert dirty > 1.3 * clean, f"{dirty:.1f} fs vs {clean:.1f} fs"
    assert any("dead zone" in n for n in p.analyze().notes)


# ------------------------------------------------------------- PFD wrap/slip
def test_wrap_mode_slips_cycles_and_clamp_does_not():
    """A weak loop pulled from far away: the two detectors behave differently.

    Clamp holds at its limit and grinds in monotonically.  Wrap reverses its own
    error signal past +/-2pi, so the loop hunts and keeps slipping -- which is
    what a tri-state PFD actually does and why acquisition aids exist.
    """
    off = 600e6
    def run(mode):
        p = presets.cppll_19p2m_4p8g()
        p.cfg.cp = replace(p.cfg.cp, icp=0.2 * p.cfg.cp.icp, pfd_mode=mode)
        return p.simulate(20000, noise=False, f_start_offset=off,
                          band_select=False)
    a, b = run("clamp"), run("wrap")
    assert a.extra["cycle_slips"] == 0, "a saturating detector cannot slip"
    assert a.extra["pfd_out_of_range_cycles"] > 100
    assert b.extra["cycle_slips"] > 1000
    assert any("cycle slips" in n for n in b.notes)
    assert any("saturated" in n for n in a.notes)


def test_pfd_error_characteristic():
    tref = 1 / 19.2e6
    from pllsim.blocks.chargepump import ChargePump
    rng = np.random.default_rng(0)
    wrap = ChargePump(CPConfig(icp=1e-4, pfd_mode="wrap"), tref, rng)
    # linear over +/-Tref, then folds back with period 2*Tref
    assert wrap.pfd_error(0.3 * tref)[0] == pytest.approx(0.3 * tref)
    assert wrap.pfd_error(1.3 * tref)[0] == pytest.approx(-0.7 * tref)
    assert wrap.pfd_error(1.3 * tref)[1] is True
    clamp = ChargePump(CPConfig(icp=1e-4, pfd_mode="clamp"), tref, rng)
    assert clamp.pfd_error(1.3 * tref)[0] == pytest.approx(0.45 * tref)


def test_pfd_mode_is_validated():
    with pytest.raises(ValueError, match="pfd_mode"):
        CPConfig(icp=1e-4, pfd_mode="sawtooth")


# --------------------------------------------------------- divider retiming
def test_retiming_removes_the_divider_noise_path():
    p = presets.cppll_19p2m_4p8g()
    p.cfg.div_pn_dbchz = -130.0        # make the divider dominate
    loud = p.analyze()
    assert "divider" in loud.pn_breakdown
    p.cfg.divider_retimed = True
    quiet = p.analyze()
    assert "divider" not in quiet.pn_breakdown
    assert quiet.jitter_fs < loud.jitter_fs
    assert any("retimed" in n for n in quiet.notes)


def test_retiming_flop_jitter_is_not_free():
    p = presets.cppll_19p2m_4p8g()
    p.cfg.divider_retimed = True
    base = p.analyze().jitter_fs
    p.cfg.retime_jitter_rms_s = 2e-12
    worse = p.analyze()
    assert "retime_ff" in worse.pn_breakdown
    assert worse.jitter_fs > base


def test_retiming_shows_up_in_the_time_domain_too():
    p = presets.cppll_19p2m_4p8g()
    p.cfg.div_pn_dbchz = -125.0
    loud = p.simulate(30000, seed=7).jitter_fs
    p.cfg.divider_retimed = True
    quiet = p.simulate(30000, seed=7).jitter_fs
    assert quiet < 0.9 * loud, f"{quiet:.1f} fs vs {loud:.1f} fs"


# ------------------------------------------------------------- lock detector
def test_lock_detector_needs_a_sustained_run():
    det = LockDetector(LockDetectConfig(window_s=10e-12, count=8, down_weight=4))
    for _ in range(7):
        det.step(1e-12)
    assert not det.locked                       # one short of the count
    det.step(1e-12)
    assert det.locked
    assert det.first_lock_cycle == 7


def test_lock_detector_hysteresis_ignores_a_single_glitch():
    det = LockDetector(LockDetectConfig(window_s=10e-12, count=8, down_weight=4))
    for _ in range(8):
        det.step(1e-12)
    det.step(1e-9)                              # one bad cycle: acc 8 -> 4
    assert det.locked, "one outlier must not drop LOCK"
    for _ in range(2):
        det.step(1e-9)                          # acc -> 0
    assert not det.locked


def test_lock_detector_reports_through_the_engine():
    p = presets.cppll_19p2m_4p8g()
    p.cfg.lock_detect = LockDetectConfig(window_s=50e-12, count=200)
    sim = p.simulate(30000, noise=False, f_start_offset=5e6, band_select=False)
    st = sim.extra["lock_detect"]
    assert isinstance(st, LockStats)
    assert st.lock_time_s is not None and st.lock_time_s > 0
    assert st.lock_fraction > 0.5
    assert "lock_detect" in sim.cal_traces


def test_lock_stats_counts_unlock_events():
    tr = np.array([0, 0, 1, 1, 0, 1, 1, 1, 0.0])
    st = LockStats.from_trace(tr, 1e-9, first_cycle=2)
    assert st.n_unlock_events == 2
    assert st.lock_time_s == pytest.approx(2e-9)
