"""FixedCoeff behavior and fixed-point mirrors vs float originals."""
import numpy as np
import pytest

from pllsim.calibration.lms import SignSignLMS
from pllsim.export.fixedpoint import DlfFx, FixedCoeff, SignSignLmsFx


def test_pow2_detection():
    for v, sh in [(0.5, 1), (0.0625, 4), (2.0 ** -11, 11), (1.0, 0), (4.0, -2)]:
        c = FixedCoeff(v)
        assert c.is_pow2 and c.shift == sh and c.realized() == v


def test_quantization_and_warning():
    c = FixedCoeff(0.3, frac_bits=16)
    assert not c.is_pow2
    assert abs(c.realized() - 0.3) / 0.3 < 1e-4
    warnings = []
    c.check("alpha", warnings)
    assert warnings and "quantized" in warnings[0]
    with pytest.raises(ValueError):
        FixedCoeff(1e-9, frac_bits=8)   # underflow


def test_dlffx_matches_float():
    """DlfFx tracks the float PI+IIR within the input-quantization bound."""
    f_in = 16
    sh_a, sh_r, sh_l = 4, 11, 1
    fx = DlfFx(FixedCoeff(2.0 ** -sh_a), FixedCoeff(2.0 ** -sh_r),
               (FixedCoeff(2.0 ** -sh_l),))
    rng = np.random.default_rng(0)
    acc = 0.0
    s = 0.0
    max_err = 0.0
    for _ in range(20000):
        e = rng.normal(0.0, 0.3)
        e_fx = int(round(e * (1 << f_in)))
        y_fx = fx.step(e_fx) / (1 << f_in)
        acc += e * 2.0 ** -sh_r
        y = e * 2.0 ** -sh_a + acc
        s += (y - s) * 2.0 ** -sh_l
        max_err = max(max_err, abs(y_fx - s))
    # error bounded by accumulated floor-rounding: << typical signal scale
    assert max_err < 20000 * 2.0 ** -f_in


def test_sslmsfx_converges_like_float():
    """Closed-loop: both calibrators converge to 1/(1+eps) on the same data."""
    eps = 0.08
    flt = SignSignLMS(init=1.0, mu=2.0 ** -16, ema=2.0 ** -10)
    fx = SignSignLmsFx(f_gain=24, mu=FixedCoeff(2.0 ** -16), sh_ema=10)
    rng = np.random.default_rng(1)
    for _ in range(120_000):
        reg = rng.uniform(-2.0, 2.0)
        noise = rng.normal(0.0, 0.3)
        # residual error after correction: zero when g = 1/(1+eps)
        err_f = (1.0 - flt.value * (1 + eps)) * reg + noise
        err_x = (1.0 - fx.gain_float * (1 + eps)) * reg + noise
        flt.step(err_f, reg)
        fx.step(int(round(err_x * (1 << 16))), int(round(reg * (1 << 16))))
    target = 1.0 / (1 + eps)
    assert abs(flt.value - target) < 0.01
    assert abs(fx.gain_float - target) < 0.01
    assert abs(fx.gain_float - flt.value) < 0.01
