"""Delta-sigma modulator correctness: mean, range, shaping slope, residual."""
import numpy as np

from pllsim.core.deltasigma import Efm1, Mash11, Mash111, run_sequence
from pllsim.core.spectrum import phase_psd


def test_means_and_ranges():
    bits = 16
    frac = 27007  # odd -> long period
    n = 1 << 16   # full period of EFM1 at 2^16
    for cls, lo, hi in [(Efm1, 0, 1), (Mash11, -1, 2), (Mash111, -3, 4)]:
        seq = run_sequence(cls(bits), frac, n)
        assert seq.min() >= lo and seq.max() <= hi
        assert abs(seq.mean() - frac / (1 << bits)) < 1e-3


def test_efm1_exact_mean_over_period():
    bits = 12
    frac = 1234
    seq = run_sequence(Efm1(bits), frac, 1 << 12)
    assert seq.sum() == frac  # accumulator overflows exactly frac times per period


def test_residual_bittrue():
    """residual_ui equals sum(y) - n*frac/M computed independently."""
    bits = 20
    frac = 700001
    for cls in (Efm1, Mash11, Mash111):
        m = cls(bits)
        tot = 0
        for k in range(5000):
            tot += m.step(frac)
            ref = tot - (k + 1) * frac / (1 << bits)
            assert abs(m.residual_ui() - ref) < 1e-9
        # shaped error must remain bounded
        assert abs(m.residual_ui()) < 8.0


def test_mash111_noise_shaping_slope():
    """PSD of (y - mean) rises ~60 dB/dec below fs/10."""
    bits = 24
    frac = (1 << 23) + 12345
    fs = 1.0
    seq = run_sequence(Mash111(bits), frac, 1 << 18).astype(float)
    f, s = phase_psd(seq - seq.mean(), fs, nfft=1 << 14, detrend="constant")
    m1 = (f > 1e-4) & (f < 3e-4)
    m2 = (f > 1e-3) & (f < 3e-3)
    slope_db_dec = 10 * np.log10(np.mean(s[m2]) / np.mean(s[m1]))
    assert 50.0 < slope_db_dec < 70.0
