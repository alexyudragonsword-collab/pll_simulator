"""Loop synthesis hits its targets; bandwidth sweep is U-shaped."""
import numpy as np
import pytest

from pllsim.arch.adpll import ADPLL, ADPLLConfig, DLFConfig
from pllsim.arch.cppll import CPPLL, CPPLLConfig
from pllsim.arch.sspll import SSPLL, SSPLLConfig
from pllsim.blocks.chargepump import CPConfig
from pllsim.blocks.oscillator import OscConfig
from pllsim.blocks.sampler import SamplerConfig
from pllsim.blocks.tdc import TDCConfig
from pllsim.synth import (cppll_kdet, design_adpll_dlf, design_cp_filter,
                          design_sspll_filter, spll_kdet, sspll_kdet,
                          sweep_bandwidth)

OSC = OscConfig(f0=4.75e9, gain=60e6, pn_dbchz=-122.0, pn_foffset=1e6,
                pn_f1f3=3e5, pn_floor_dbchz=-155.0)
CP = CPConfig(icp=1.5e-3, mismatch_pct=2.0, leakage_a=1e-9, t_reset=200e-12)


@pytest.mark.parametrize("f_ugb,pm", [(0.5e6, 55), (1e6, 58), (2e6, 62)])
def test_cp_filter_hits_targets(f_ugb, pm):
    filt = design_cp_filter(cppll_kdet(CP.icp, 250), OSC.gain, f_ugb, pm, 19.2e6)
    ar = CPPLL(CPPLLConfig(fref=19.2e6, fout=4.8e9, osc=OSC, cp=CP, filt=filt,
                           ref_pn_dbchz=-162.0)).analyze()
    assert abs(ar.loop.f_ugb / f_ugb - 1) < 0.06
    assert abs(ar.loop.pm_deg - pm) < 3.5


def test_sspll_filter_synthesis_in_discrete_loop():
    """Discrete-aware synthesis hits the target on the exact SSPLL model."""
    s = SamplerConfig(amp_v=0.4, c_samp=60e-15, gm=1e-3, pulse_width=150e-12,
                      pedestal_v=1e-3)
    k_q = s.amp_v * s.gm * s.pulse_width          # C/rad
    filt = design_sspll_filter(k_q, OSC.gain, 1e6, 62, 19.2e6)
    ar = SSPLL(SSPLLConfig(fref=19.2e6, fout=4.8e9, osc=OSC, sampler=s,
                           filt=filt, ref_pn_dbchz=-162.0)).analyze()
    assert abs(ar.loop.f_ugb / 1e6 - 1.0) < 0.06
    assert abs(ar.loop.pm_deg - 62) < 3.5


def test_adpll_dlf_hits_targets():
    a, r = design_adpll_dlf(100e6, 1.5e6, 60, iir_lambdas=(0.5,))
    cfg = ADPLLConfig(fref=100e6, fout=100.503 * 100e6,
                      osc=OscConfig(f0=10e9, gain=20e3, pn_dbchz=-112,
                                    pn_foffset=1e6, pn_f1f3=4e5,
                                    pn_floor_dbchz=-150),
                      dlf=DLFConfig(alpha=a, rho=r, iir_lambdas=(0.5,)),
                      tdc=TDCConfig(t_res=0.5e-12, n_bits=8),
                      ref_pn_dbchz=-158.0)
    ar = ADPLL(cfg).analyze()
    assert abs(ar.loop.f_ugb / 1.5e6 - 1) < 0.06
    assert abs(ar.loop.pm_deg - 60) < 3.5


def test_bandwidth_sweep_u_shape():
    def make(bw):
        filt = design_cp_filter(cppll_kdet(CP.icp, 250), OSC.gain, bw, 58, 19.2e6)
        return CPPLL(CPPLLConfig(fref=19.2e6, fout=4.8e9, osc=OSC, cp=CP,
                                 filt=filt, ref_pn_dbchz=-162.0))
    sw = sweep_bandwidth(make, np.logspace(np.log10(0.2e6), np.log10(2.2e6), 7))
    j = sw["jitter_fs"]
    i = int(np.argmin(j))
    assert 0 < i < len(j) - 1                 # interior optimum (U-shape)
    assert j[0] > j[i] and j[-1] > j[i]
