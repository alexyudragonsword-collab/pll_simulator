"""MDLL architecture and Monte Carlo framework."""
import numpy as np
import pytest

from pllsim.arch.mdll import MDLL, MDLLConfig
from pllsim.blocks.oscillator import OscConfig
from pllsim.montecarlo import monte_carlo

RING = OscConfig(f0=2.4e9, gain=100e3, pn_dbchz=-95.0, pn_foffset=1e6,
                 pn_f1f3=8e5, pn_floor_dbchz=-140.0)


@pytest.fixture(scope="module")
def mdll():
    return MDLL(MDLLConfig(fref=150e6, fout=2.4e9, osc=RING,
                           mux_jitter_rms_s=40e-15, ref_pn_dbchz=-160.0))


def test_osc_highpass_and_jitter(mdll):
    ar = mdll.analyze()
    h = ar.ntfs["ntf_osc"]
    # sample-and-subtract: |NTF| ~ pi f/fref at low offset
    i = np.searchsorted(h.f, 1e5)
    assert abs(abs(h.h[i]) / (np.pi * h.f[i] / 150e6) - 1) < 0.1
    assert 150 < ar.jitter_fs < 600


def test_cross_domain_fine_psd(mdll):
    ar = mdll.analyze()
    sim = mdll.simulate(150_000, seed=1, f_free_error=2e6)
    ff, sf = sim.extra["fine_f"], sim.extra["fine_psd"]
    m = (ff > 3e5) & (ff < 2.5e8)
    tgt = np.interp(np.log10(ff[m]), np.log10(ar.f), ar.pn_breakdown["total"])
    edges = np.logspace(np.log10(3e5), np.log10(2.5e8), 7)
    for a, b in zip(edges[:-1], edges[1:]):
        mm = (ff[m] >= a) & (ff[m] < b)
        if mm.sum() < 3:
            continue
        err = 10 * np.log10(np.mean(sf[m][mm]) / np.mean(tgt[mm]))
        # 1-ZOH is an approximation of the reset-random-walk spectrum
        assert abs(err) < 3.5, f"band {a:.3g}-{b:.3g} off {err:.2f} dB"


def test_tuning_loop_kills_spur(mdll):
    sim = mdll.simulate(150_000, seed=1, f_free_error=2e6)
    spur = sim.spurs_fft.get(150e6, float("nan"))
    assert np.isnan(spur) or spur < -60.0
    # residual free-running error within a few tuning LSBs
    resid = sim.freq_out[-1] - 2.4e9
    assert abs(resid) < 20 * RING.gain * 0.02 * 50


def _mc_build(rng):
    cfg = MDLLConfig(fref=150e6, fout=2.4e9,
                     osc=OscConfig(f0=2.4e9 + rng.normal(0, 2e6), gain=100e3,
                                   pn_dbchz=-95.0 + rng.normal(0, 1.5),
                                   pn_foffset=1e6, pn_f1f3=8e5,
                                   pn_floor_dbchz=-140.0),
                     mux_jitter_rms_s=abs(rng.normal(40e-15, 10e-15)),
                     ref_pn_dbchz=-160.0)
    return MDLL(cfg), dict(n_cycles=40_000), {"pn": cfg.osc.pn_dbchz}


def test_monte_carlo_framework():
    res = monte_carlo(_mc_build, n_runs=8, seed=7, n_jobs=2)
    assert res.n_ok == 8
    assert "jitter_fs" in res.metrics and len(res.metrics["jitter_fs"]) == 8
    assert np.all(np.isfinite(res.metrics["jitter_fs"]))
    assert "pn" in res.params
    y = res.yield_frac("jitter_fs", 1000.0)
    assert 0.5 <= y <= 1.0
    assert "Monte Carlo" in res.summary()
