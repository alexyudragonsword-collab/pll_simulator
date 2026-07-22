"""ILCM: realignment model, lock range, spur vs analytic, FTL."""
import numpy as np
import pytest

from pllsim.arch.ilcm import ILCM, ILCMConfig, injection_spur_dbc
from pllsim.blocks.oscillator import OscConfig


@pytest.fixture(scope="module")
def pll():
    return ILCM(ILCMConfig(
        fref=250e6, fout=12e9,
        osc=OscConfig(f0=12e9, gain=1.0, pn_dbchz=-105.0, pn_foffset=1e6,
                      pn_f1f3=5e5, pn_floor_dbchz=-145.0),
        beta=0.6, q_tank=8, i_ratio=0.15, inj_jitter_rms_s=15e-15,
        ref_pn_dbchz=-155.0, ftl_f_lsb=20e3))


def test_noise_model_and_jitter(pll):
    ar = pll.analyze()
    assert 60 < ar.jitter_fs < 200
    # injection bandwidth ~ -fref ln(1-beta)/2pi = 36.5 MHz
    assert 30e6 < ar.loop.f_ugb < 45e6
    # oscillator NTF is a highpass on the phase PSD
    h = ar.ntfs["h_osc"]
    assert abs(h.h[0]) < 0.01
    assert abs(abs(h.h[np.searchsorted(h.f, 100e6)]) - 1) < 0.7


def test_cross_domain_psd(pll):
    ar = pll.analyze()
    sim = pll.simulate(150_000, seed=1, f_free_error=3e6)
    m = (sim.f_psd > 1e5) & (sim.f_psd < 60e6)
    fm, sm = sim.f_psd[m], sim.s_phi_psd[m]
    tgt = np.interp(np.log10(fm), np.log10(ar.f), ar.pn_breakdown["total"])
    edges = np.logspace(np.log10(fm[0]), np.log10(fm[-1]), 8)
    for a, b in zip(edges[:-1], edges[1:]):
        mm = (fm >= a) & (fm < b)
        if mm.sum() < 3:
            continue
        err = 10 * np.log10(np.mean(sm[mm]) / np.mean(tgt[mm]))
        assert abs(err) < 2.0, f"band {a:.3g}-{b:.3g} off {err:.2f} dB"


def test_injection_spur_matches_analytic(pll):
    fe = 2e6
    sim = pll.simulate(60_000, seed=2, f_free_error=fe, calibration=False,
                       fine_oversample=4)
    spur = sim.spurs_fft[250e6]
    th = injection_spur_dbc(2 * np.pi * fe / 250e6, 0.6)
    assert abs(spur - th) < 3.0


def test_lock_range(pll):
    bound = pll.cfg.lock_range_hz()      # beta*fref/2 = 75 MHz
    s_in = pll.simulate(20_000, seed=0, f_free_error=0.5 * bound,
                        calibration=False, noise=False)
    assert s_in.extra["slips"] == 0
    s_out = pll.simulate(20_000, seed=0, f_free_error=1.3 * bound,
                         calibration=False, noise=False)
    assert s_out.extra["slips"] > 100


def test_ftl_converges_and_kills_spur(pll):
    sim = pll.simulate(150_000, seed=1, f_free_error=3e6, fine_oversample=4)
    resid = 3e6 + sim.cal_traces["ftl_fcorr"][-1]
    assert abs(resid) < 5 * pll.cfg.ftl_f_lsb
    # spur with FTL far below the uncorrected 3 MHz case (~-38 dBc)
    spur = sim.spurs_fft.get(250e6, float("nan"))
    assert np.isnan(spur) or spur < -60.0
