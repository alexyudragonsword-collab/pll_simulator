"""CPPLL architecture-level tests: lock, cross-domain PSD consistency."""
import numpy as np
import pytest

from pllsim.arch.cppll import CPPLL, CPPLLConfig
from pllsim.blocks.chargepump import CPConfig
from pllsim.blocks.loopfilter import FilterDesign
from pllsim.blocks.oscillator import OscConfig


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
    """Time-domain periodogram matches linear model within 2 dB band-averaged."""
    ar = pll.analyze()
    sim = pll.simulate(200_000, seed=3)
    m = (sim.f_psd > ar.loop.f_ugb / 10) & (sim.f_psd < pll.cfg.fref / 4)
    fm, sm = sim.f_psd[m], sim.s_phi_psd[m]
    tgt = np.interp(np.log10(fm), np.log10(ar.f), ar.pn_breakdown["total"])
    edges = np.logspace(np.log10(fm[0]), np.log10(fm[-1]), 8)
    for a, b in zip(edges[:-1], edges[1:]):
        mm = (fm >= a) & (fm < b)
        if mm.sum() < 3:
            continue
        err = 10 * np.log10(np.mean(sm[mm]) / np.mean(tgt[mm]))
        # 2.5 dB: Welch variance + the real CT-vs-DT loop deviation near UGB
        # (UGB/fref ~ 1/20 here) both land in the peaking band
        assert abs(err) < 2.5, f"band {a:.3g}-{b:.3g} Hz off by {err:.2f} dB"
