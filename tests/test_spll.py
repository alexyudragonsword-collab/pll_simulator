"""SPLL: N-multiplied sampler noise (contrast with SSPLL), lock, PSD."""
import numpy as np
import pytest

from pllsim.arch.spll import SPLL, SPLLConfig
from pllsim.blocks.loopfilter import FilterDesign
from pllsim.blocks.oscillator import OscConfig
from pllsim.blocks.sampler import SamplerConfig
from pllsim.core.jitter import integrate_pn
from pllsim.validation import compare_domains


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
    # measured 2026-09-10: kT/C is 73.5 % of the budget here (x N to the
    # output) against ~1 % in the SSPLL, and the loop reads 207.6 fs
    assert p_ktc / p_tot > 0.2
    assert 100 < ar.jitter_fs < 350


def test_locks_and_matches_linear_model(pll):
    ar = pll.analyze()
    sim = pll.simulate(150_000, seed=1, f_start_offset=-30e6)
    assert sim.lock_time_s is not None
    # measured (seed 1, 150k, -30 MHz): tail 1.0 kHz off 8 GHz, and the two
    # domains 4.0 % apart (199.4 vs 207.6 fs).  35 % is the once-per-edge
    # record's band clipping plus Welch variance, not a slack budget
    assert abs(np.mean(sim.freq_out[-10_000:]) - 8e9) < 1e5
    assert abs(sim.jitter_fs - ar.jitter_fs) / ar.jitter_fs < 0.35


def test_cross_domain_psd(pll):
    """The SPLL's first PSD-band test -- it had only the scalar jitter check.

    A scalar comparison cannot see a shape error: two curves can integrate to
    the same jitter while disagreeing by 6 dB in opposite directions.  2.0 dB
    matches the stock-point measurement (worst 0.83 dB at this seed) and the
    docs' stated SPLL bound.
    """
    c = compare_domains(pll, n_cycles=150_000, seed=1)
    assert c.skipped == [], c.skipped
    assert c.worst_db < 2.0, [f"{b.f_lo:.3g}-{b.f_hi:.3g}: {b.err_db:+.2f}"
                              for b in c.bands]
