"""CPPLL architecture-level tests: lock, cross-domain PSD consistency."""
import numpy as np
import pytest

from pllsim.arch.cppll import CPPLL, CPPLLConfig
from pllsim.blocks.chargepump import CPConfig
from pllsim.blocks.loopfilter import FilterDesign
from pllsim.blocks.oscillator import OscConfig
from pllsim.validation import compare_domains


@pytest.fixture(scope="module")
def pll():
    cfg = CPPLLConfig(
        fref=19.2e6, fout=4.8e9,
        osc=OscConfig(f0=4.75e9, gain=60e6, pn_dbchz=-122.0, pn_foffset=1e6,
                      pn_f1f3=3e5, pn_floor_dbchz=-155.0),
        cp=CPConfig(icp=1.5e-3, mismatch_pct=2.0, leakage_a=1e-9, t_reset=200e-12),
        filt=FilterDesign(c1=680e-12, r2=20e3, c2=3.3e-12, r3=2e3, c3=2.2e-12),
        ref_pn_dbchz=-162.0,
    )
    return CPPLL(cfg)


def test_loop_metrics_sane(pll):
    ar = pll.analyze()
    assert 0.5e6 < ar.loop.f_ugb < 2e6
    assert 45 < ar.loop.pm_deg < 70
    assert ar.loop.n_crossings == 1
    assert 50 < ar.jitter_fs < 300


def test_locks_from_offset(pll):
    sim = pll.simulate(60_000, noise=False, seed=0, f_start_offset=-40e6)
    assert sim.lock_time_s is not None
    assert sim.lock_time_s < 40e-6
    # steady state on frequency
    assert abs(np.mean(sim.freq_out[-5000:]) - 4.8e9) < 5e3


def test_cross_domain_psd(pll):
    """Time-domain periodogram matches linear model within 2.5 dB band-averaged.

    2.5 dB: Welch variance + the real CT-vs-DT loop deviation near UGB
    (UGB/fref ~ 1/20 here) both land in the peaking band.  Mutation: tighten
    to 1.5 dB and the peaking bands go red (worst is ~2.1 dB at this seed).
    """
    c = compare_domains(pll, n_cycles=200_000, seed=3)
    assert c.skipped == [], c.skipped
    assert c.worst_db < 2.5, [f"{b.f_lo:.3g}-{b.f_hi:.3g}: {b.err_db:+.2f}"
                              for b in c.bands]
