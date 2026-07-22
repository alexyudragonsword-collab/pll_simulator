"""SPLL fractional mode + the three JSSC benchmarks of ex14.

Benchmark bounds are deliberately loose (same policy as test_benchmark.py):
published measurements are class targets for architectural consistency, not
parameter replication — the undisclosed circuit values are assumptions.
"""
import numpy as np
import pytest

from pllsim import presets
from pllsim.arch.adpll import ADPLL, ADPLLConfig, DLFConfig
from pllsim.arch.cppll import FracConfig
from pllsim.arch.spll import SPLL, SPLLConfig
from pllsim.arch.sspll import SSPLL, SSPLLConfig
from pllsim.blocks.dtc import DTCConfig
from pllsim.blocks.loopfilter import FilterDesign
from pllsim.blocks.oscillator import OscConfig
from pllsim.blocks.sampler import SamplerConfig
from pllsim.calibration.lms import SignSignLMS
from pllsim.core.jitter import ldbc_from_sphi
from pllsim.synth import design_sspll_filter


# ------------------------------------------------------- SPLL fractional mode
def test_spll_frac_locks_at_fractional_channel():
    pll = presets.spll_frac_52m_6p253g()
    sim = pll.simulate(60_000, seed=1)
    assert sim.lock_time_s is not None
    f_tail = sim.freq_out[-5000:].mean()
    assert abs(f_tail - pll.cfg.fout) < 1e-4 * pll.cfg.fout
    # the channel is genuinely fractional: no integer N reaches it
    assert abs(pll.cfg.fout / pll.cfg.fref % 1.0 - 0.2503) < 1e-9


def test_spll_frac_config_guards():
    c = presets.spll_frac_52m_6p253g().cfg
    with pytest.raises(ValueError):        # frac mismatch with fout
        SPLLConfig(fref=c.fref, fout=c.fout, osc=c.osc, sampler=c.sampler,
                   filt=c.filt,
                   frac=FracConfig(frac=0.5, mash_order=1, dtc=c.frac.dtc))
    with pytest.raises(ValueError):        # MASH order > 1 rejected
        SPLLConfig(fref=c.fref, fout=c.fout, osc=c.osc, sampler=c.sampler,
                   filt=c.filt,
                   frac=FracConfig(frac=0.2503, mash_order=2, dtc=c.frac.dtc))
    with pytest.raises(ValueError):        # integer-N with fractional fout
        SPLLConfig(fref=c.fref, fout=c.fout, osc=c.osc, sampler=c.sampler,
                   filt=c.filt).n_div


def test_spll_fractionalization_nearly_free():
    """With a calibrated DTC the fractional SPLL pays little over integer-N."""
    frac_pll = presets.spll_frac_52m_6p253g()
    c = frac_pll.cfg
    int_pll = SPLL(SPLLConfig(
        fref=c.fref, fout=120 * c.fref, osc=c.osc, sampler=c.sampler,
        filt=c.filt, ref_pn_dbchz=c.ref_pn_dbchz, fll_i=c.fll_i,
        fll_engage=c.fll_engage, fll_release=c.fll_release,
        int_band=c.int_band))
    ji = int_pll.simulate(80_000, seed=2).jitter_fs
    jf = frac_pll.simulate(80_000, seed=2).jitter_fs
    assert jf < 1.35 * ji, f"fractional penalty too high: {jf:.0f} vs {ji:.0f}"


def test_spll_frac_lms_converges_to_inverse_gain_error():
    pll = presets.spll_frac_52m_6p253g()
    sim = pll.simulate(120_000, seed=3, dtc_gain_init_error=0.08)
    g = sim.cal_traces["dtc_gain"][-1]
    assert abs(g - 1.0 / 1.08) < 0.01 * (1.0 / 1.08)


# ------------------------------------------------- Part 1: Dartizio JSSC 2023
def _dartizio():
    return ADPLL(ADPLLConfig(
        fref=500e6, fout=(18 + 0.503) * 500e6,
        osc=OscConfig(f0=9.25e9, gain=100e3, pn_dbchz=-112.0, pn_foffset=1e6,
                      pn_f1f3=1e6, pn_floor_dbchz=-147.0),
        dlf=DLFConfig(alpha=0.5, rho=0.5 * 2**-8),
        mode="dtc_bbpd",
        frac=FracConfig(frac=0.503, mash_order=2,
                        dtc=DTCConfig(t_res=250e-15, n_bits=12,
                                      jitter_rms_s=60e-15),
                        dtc_cal=SignSignLMS(init=1.0, mu=1e-5,
                                            gear_shift_n=100_000,
                                            mu_final=1e-6)),
        bb_jitter_rms_s=150e-15, ref_pn_dbchz=-158.0,
        int_band=(10e3, 100e6)))


def test_dartizio23_consistency():
    """Published: 9.25 GHz fractional channels, < 77 fs rms."""
    pll = _dartizio()
    ar = pll.analyze()
    assert 40 < ar.jitter_fs < 100         # linear under-reads BB loops
    sim = pll.simulate(250_000, seed=3)
    assert 55 < sim.jitter_fs < 105        # published 77 fs class


# ------------------------------------------------ Part 2: Markulic JSSC 2016
def _markulic(frac):
    samp = SamplerConfig(amp_v=0.6, c_samp=100e-15, gm=2e-3,
                         pulse_width=200e-12, pedestal_v=1e-3)
    osc = OscConfig(f0=10.20e9, gain=60e6, pn_dbchz=-109.5, pn_foffset=1e6,
                    pn_f1f3=4e5, pn_floor_dbchz=-145.0)
    filt = design_sspll_filter(samp.amp_v * samp.gm * samp.pulse_width,
                               osc.gain, 1.4e6, 60.0, 40e6)
    fr, fout = None, 10.24e9
    if frac is not None:
        fout = (256 + frac) * 40e6
        fr = FracConfig(frac=frac, mash_order=1,
                        dtc=DTCConfig(t_res=150e-15, n_bits=10,
                                      jitter_rms_s=30e-15),
                        dtc_cal=SignSignLMS(init=1.0, mu=5e-6,
                                            gear_shift_n=60_000,
                                            mu_final=5e-7))
    return SSPLL(SSPLLConfig(
        fref=40e6, fout=fout, osc=osc, sampler=samp, filt=filt,
        ref_pn_dbchz=-158.0, fll_i=1e-6, fll_engage=2e6, fll_release=400e3,
        frac=fr, int_band=(10e3, 40e6)))


def test_markulic16_consistency():
    """Published: 176 fs integer-N / 198 fs worst fractional at 10.24 GHz."""
    ji = _markulic(None).analyze().jitter_fs
    jf = _markulic(0.2503).analyze().jitter_fs
    assert 130 < ji < 230                  # published 176 fs class
    assert 150 < jf < 260                  # published 198 fs (worst channel)
    assert jf > ji                          # residual makes frac >= int
    assert jf < 1.5 * ji                    # ... but nearly free


# ------------------------------------------------------ Part 3: Wu JSSC 2019
def _wu():
    return SPLL(SPLLConfig(
        fref=52e6, fout=(120 + 0.2503) * 52e6,
        osc=OscConfig(f0=6.2e9, gain=60e6, pn_dbchz=-124.0, pn_foffset=1e6,
                      pn_f1f3=2e5, pn_floor_dbchz=-154.0),
        sampler=SamplerConfig(amp_v=0.8, c_samp=3e-12, gm=10e-3,
                              pulse_width=1e-9, pedestal_v=1e-3),
        filt=FilterDesign(c1=1e-9, r2=3e3, c2=4.7e-12, r3=1e3, c3=2.2e-12),
        ref_pn_dbchz=-165.0, div_pn_dbchz=-165.0,
        fll_i=2e-6, fll_engage=3e6, fll_release=600e3,
        frac=FracConfig(frac=0.2503, mash_order=1,
                        dtc=DTCConfig(t_res=160e-15, n_bits=10,
                                      jitter_rms_s=20e-15,
                                      gain_error_residual=0.002),
                        dtc_cal=SignSignLMS(init=1.0, mu=5e-6,
                                            gear_shift_n=60_000,
                                            mu_final=5e-7)),
        int_band=(10e3, 10e6)))


def test_wu19_consistency():
    """Published: 75 fs rms over 10 kHz - 10 MHz, spur < -64 dBc."""
    pll = _wu()
    ar = pll.analyze()
    assert 55 < ar.jitter_fs < 100         # published 75 fs class
    i200k = np.searchsorted(ar.f, 200e3)
    inband = ldbc_from_sphi(ar.pn_breakdown["total"][i200k])
    assert -118 < inband < -107
    sim = pll.simulate(100_000, seed=4, dtc_gain_init_error=0.05)
    assert sim.jitter_fs < 120
    spurs = [v for v in sim.spurs_fft.values() if np.isfinite(v)]
    assert spurs and max(spurs) < -64.0    # published spur bound
