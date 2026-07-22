"""Two-point modulation: GMSK trajectories, EVM, injection in two archs."""
import numpy as np

from pllsim import presets
from pllsim.modulation import evm, gmsk_trajectory, prbs

N, SETTLE = 140_000, 60_000


def test_gmsk_trajectory_properties():
    # all-ones: +pi/2 per symbol, peak deviation h*Rb/2
    bits = np.ones(64, dtype=int)
    fdev, ph = gmsk_trajectory(bits, 100e6, 10e6)
    assert abs(fdev.max() - 2.5e6) < 0.05e6
    # steady-state phase slope: pi/2 per symbol (10 samples per symbol)
    mid = slice(300, 500)
    slope = np.polyfit(np.arange(len(ph[mid])), ph[mid], 1)[0]
    assert abs(slope - (np.pi / 2) / 10.0) < 0.01


def test_prbs_balanced():
    b = prbs(32767)
    assert b.size == 32767
    assert 0.48 < b.mean() < 0.52


def _run(pll, fref, rb, dp, seed):
    bits = prbs(int((N - SETTLE) * rb / fref) - 20, seed=7)
    fdev, _ = gmsk_trajectory(bits, fref, rb)
    mod = np.zeros(N)
    mod[SETTLE:SETTLE + fdev.size] = fdev
    ideal = 2.0 * np.pi * np.cumsum(mod) / fref
    sim = pll.simulate(N, seed=seed, mod_freq=mod, mod_dp_gain=dp)
    return evm(sim.phase_err_out[SETTLE + 4000:], ideal[SETTLE + 4000:])


def test_adpll_two_point_matched_and_mismatch():
    e0 = _run(presets.adpll_100m_10g(), 100e6, 10e6, 1.0, seed=1)
    assert e0["evm_pct"] < 1.5          # noise-limited when matched
    e5 = _run(presets.adpll_100m_10g(), 100e6, 10e6, 1.05, seed=1)
    assert e5["evm_pct"] > 3.0 * e0["evm_pct"]   # mismatch dominates


def test_sspll_two_point_markulic_class():
    from tests.test_benchmark_jssc import _markulic
    e0 = _run(_markulic(0.2503), 40e6, 2.5e6, 1.0, seed=2)
    assert e0["evm_pct"] < 2.0          # published class: -40 dB = 1%
    e10 = _run(_markulic(0.2503), 40e6, 2.5e6, 1.10, seed=2)
    assert e10["evm_pct"] > 1.8 * e0["evm_pct"]
