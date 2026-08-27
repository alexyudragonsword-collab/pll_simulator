"""MDLL architecture and Monte Carlo framework."""
import numpy as np
import pytest

from pllsim.arch.mdll import MDLL, MDLLConfig
from pllsim.blocks.oscillator import OscConfig
from pllsim.montecarlo import monte_carlo
from pllsim.validation import compare_domains  # noqa: I001

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
    """3.5 dB: 1-ZOH is an approximation of the reset-random-walk spectrum,
    and the fine record is a plain periodogram with no segment averaging."""
    c = compare_domains(mdll, n_cycles=150_000, seed=1, n_bins=6,
                        band=(3e5, 2.5e8), psd_source="fine",
                        sim_kwargs={"f_free_error": 2e6})
    assert c.psd_source == "fine"
    assert c.worst_db < 3.5, [f"{b.f_lo:.3g}-{b.f_hi:.3g}: {b.err_db:+.2f}"
                              for b in c.bands]


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
