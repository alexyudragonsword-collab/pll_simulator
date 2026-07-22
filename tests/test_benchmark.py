"""Literature benchmark: Gao et al. JSSC 2009/2010 sub-sampling PLL.

Published: fref 55.25 MHz -> 2.21 GHz, in-band -126 dBc/Hz, 0.15 ps rms
(10 kHz - 100 MHz), companion chip BW = fref/20.  Sampler/filter inputs are
technology-plausible assumptions; the assertion is architectural consistency.
"""
import numpy as np

from pllsim.arch.sspll import SSPLL, SSPLLConfig
from pllsim.blocks.oscillator import OscConfig
from pllsim.blocks.sampler import SamplerConfig
from pllsim.core.jitter import ldbc_from_sphi
from pllsim.synth import design_sspll_filter

FREF, FOUT = 55.25e6, 2.21e9


def test_gao_sspll_consistency():
    osc = OscConfig(f0=2.19e9, gain=30e6, pn_dbchz=-121.0, pn_foffset=1e6,
                    pn_f1f3=2e5, pn_floor_dbchz=-150.0)
    samp = SamplerConfig(amp_v=0.8, c_samp=800e-15, gm=2e-3,
                         pulse_width=200e-12, pedestal_v=0.5e-3)
    filt = design_sspll_filter(samp.amp_v * samp.gm * samp.pulse_width,
                               osc.gain, FREF / 20, 60.0, FREF)
    pll = SSPLL(SSPLLConfig(fref=FREF, fout=FOUT, osc=osc, sampler=samp,
                            filt=filt, ref_pn_dbchz=-160.0,
                            fll_i=1e-6, fll_engage=1.5e6, fll_release=300e3,
                            int_band=(10e3, 100e6)))
    ar = pll.analyze()
    inband = ldbc_from_sphi(ar.pn_breakdown["total"][np.searchsorted(ar.f, 200e3)])
    assert abs(inband - (-126.0)) < 3.0            # published -126 dBc/Hz
    assert 0.10 < ar.jitter_fs / 1e3 < 0.20        # published 0.15 ps rms
    sim = pll.simulate(150_000, seed=1)
    assert 0.09 < sim.jitter_fs / 1e3 < 0.20
