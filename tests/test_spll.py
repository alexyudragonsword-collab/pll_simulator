"""SPLL: N-multiplied sampler noise (contrast with SSPLL), lock, PSD."""
import numpy as np
import pytest

from pllsim.arch.spll import SPLL, SPLLConfig
from pllsim.blocks.loopfilter import FilterDesign
from pllsim.blocks.oscillator import OscConfig
from pllsim.blocks.sampler import SamplerConfig
from pllsim.core.jitter import integrate_pn


@pytest.fixture(scope="module")
def pll():
    return SPLL(SPLLConfig(
        fref=100e6, fout=8e9,
        osc=OscConfig(f0=7.92e9, gain=80e6, pn_dbchz=-118.0, pn_foffset=1e6,
                      pn_f1f3=3e5, pn_floor_dbchz=-152.0),
        sampler=SamplerConfig(amp_v=0.4, c_samp=100e-15, gm=4e-3,
                              pulse_width=800e-12, pedestal_v=1e-3),
        filt=FilterDesign(c1=330e-12, r2=12e3, c2=2.2e-12, r3=1.5e3, c3=1e-12),
        ref_pn_dbchz=-160.0,
        fll_i=2e-6, fll_engage=3e6, fll_release=600e3))


def test_sampler_noise_is_n_multiplied(pll):
    """In the reference-sampling PLL the sampler kT/C is a major in-band
    contributor (x N to output); in the SSPLL it is negligible."""
    ar = pll.analyze()
    p_ktc = integrate_pn(ar.f, ar.pn_breakdown["sampler_ktc"], *ar.int_band)
    p_tot = integrate_pn(ar.f, ar.pn_breakdown["total"], *ar.int_band)
    assert p_ktc / p_tot > 0.2
    assert 100 < ar.jitter_fs < 350


def test_locks_and_matches_linear_model(pll):
    ar = pll.analyze()
    sim = pll.simulate(150_000, seed=1, f_start_offset=-30e6)
    assert sim.lock_time_s is not None
    assert abs(np.mean(sim.freq_out[-10_000:]) - 8e9) < 1e5
    assert abs(sim.jitter_fs - ar.jitter_fs) / ar.jitter_fs < 0.35
