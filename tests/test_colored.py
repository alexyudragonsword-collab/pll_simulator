"""Colored-noise synthesis PSD accuracy (band-averaged)."""
import numpy as np
import pytest

from pllsim.core.colored import OscPhaseNoiseGen, synth_from_psd
from pllsim.core.noise import LeesonOscillator
from pllsim.core.spectrum import phase_psd


def band_avg_db_error(f, s_meas, s_target, f1, f2, n_bands=8):
    edges = np.logspace(np.log10(f1), np.log10(f2), n_bands + 1)
    errs = []
    for a, b in zip(edges[:-1], edges[1:]):
        m = (f >= a) & (f < b)
        if m.sum() < 3:
            continue
        errs.append(10 * np.log10(np.mean(s_meas[m]) / np.mean(s_target[m])))
    return np.array(errs)


@pytest.mark.parametrize("slope", [0, -1, -2])
def test_synth_psd_slopes(slope):
    fs, n = 100e6, 1 << 20
    rng = np.random.default_rng(1234 + slope)
    c = 1e-8

    def target(f):
        return c * (f / 1e5) ** slope

    x = synth_from_psd(target, fs, n, rng)
    f, s = phase_psd(x, fs, nfft=1 << 16, detrend="constant")
    # lowest band starts ~3x the Welch resolution bin (fs/nfft ~ 1.5 kHz)
    errs = band_avg_db_error(f, s, target(f), 5e3, 1e7)
    assert np.all(np.abs(errs) < 1.0)


def test_random_walk_variance():
    """White-FM part: accumulated phase variance grows linearly, slope = sw."""
    prof = LeesonOscillator.from_spot("vco", -110.0, 1e6, f_1f3=0.0, floor_dbchz=-300.0)
    fs = 50e6
    rng = np.random.default_rng(7)
    gen = OscPhaseNoiseGen(prof, fs, rng)
    n = 200000
    d, add = gen.steps(n)
    assert np.allclose(add, 0.0)
    var = np.var(d)
    expect = 2 * np.pi**2 * prof.k2 / fs
    assert abs(var - expect) / expect < 0.05


def test_oscgen_full_profile_psd():
    """Accumulated phase PSD matches Leeson profile in the 1/f^3 + 1/f^2 region."""
    prof = LeesonOscillator.from_spot("vco", -110.0, 1e6, f_1f3=2e5, floor_dbchz=-155.0)
    fs = 100e6
    rng = np.random.default_rng(42)
    gen = OscPhaseNoiseGen(prof, fs, rng)
    n = 1 << 21
    d, add = gen.steps(n)
    phi = np.cumsum(d) + add
    f, s = phase_psd(phi, fs, nfft=1 << 17)
    errs = band_avg_db_error(f, s, prof.psd(f), 1e4, 2e7)
    assert np.all(np.abs(errs) < 1.5)
