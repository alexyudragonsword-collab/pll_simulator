"""Deterministic fractional-spur prediction from TDC nonlinearity.

The TDC-based ADPLL has no DTC code sequence to replay, which is why its
analyze() used to hand back an empty spur table and a note saying to read
the number out of simulate().  The mechanism is nonetheless just as
deterministic as the DTC case, and it is worth being able to see before
running anything.

With a fractional FCW the TDC input sweeps its range at the fractional beat
rate: the normalized code is

    x[n] = (n * frac) mod 1 ,

so any systematic INL is a fixed function g(x) sampled along that ramp.
Expand g in a Fourier series on [0, 1),

    g(x) = sum_k c_k exp(j 2 pi k x) ,

and each harmonic maps to a tone at fold(k*frac)*fref -- one spur per k,
with amplitude |c_k| in seconds at the PD input.  Referring that to the
output through the loop's own response,

    spur [dBc] = 20 log10( 2*pi*fout*|c_k| * |NTF(f_spur)| / 2 ) ,

the same accounting core.dtcspurs uses.  Nothing here is fitted: the
coefficients come from the declared INL shape, and integer k*frac values
(the near-integer channels) land the spur inside the loop bandwidth where
|NTF| ~ 1, which is exactly where the measurement is worst.
"""
from __future__ import annotations

import numpy as np

TWOPI = 2.0 * np.pi


def inl_fourier_coeffs(inl_sin, n_harm: int = 16, n_grid: int = 4096
                       ) -> np.ndarray:
    """|c_k| for k = 1..n_harm of the INL shape over its normalized range.

    inl_sin is (amplitude_s, cycles, phase) exactly as TDCConfig declares it.
    A whole number of cycles gives one nonzero coefficient; a fractional
    number spreads across k, which is the honest answer and not a artefact.
    """
    amp, cyc, ph = inl_sin
    x = np.arange(n_grid) / n_grid
    g = amp * np.sin(TWOPI * cyc * x + ph)
    ck = np.fft.rfft(g) / n_grid
    out = np.zeros(n_harm)
    for k in range(1, n_harm + 1):
        if k < ck.size:
            out[k - 1] = 2.0 * abs(ck[k])      # one-sided amplitude
    return out


def tdc_inl_spur_table(inl_sin, frac: float, fref: float, fout: float,
                       ntf=None, n_harm: int = 16,
                       f_min: float = 1e3) -> dict[float, float]:
    """{offset_hz: spur_dbc} from a sinusoidal TDC INL on a fractional channel.

    Returns an empty table for an integer channel: with frac = 0 the TDC sits
    on one code and its INL is a static offset, not a tone.
    """
    if not inl_sin or frac <= 0.0 or frac >= 1.0:
        return {}
    amps = inl_fourier_coeffs(inl_sin, n_harm)
    # a whole number of INL cycles leaves one real coefficient and a floor of
    # FFT round-off; publishing those as -350 dBc entries would read as
    # findings rather than as zeros
    floor = 1e-6 * float(np.max(amps)) if np.max(amps) > 0 else 0.0
    out: dict[float, float] = {}
    for k, a in enumerate(amps, start=1):
        if a <= floor:
            continue
        nu = (k * frac) % 1.0
        f_sp = min(nu, 1.0 - nu) * fref
        if not (f_min < f_sp < 0.5 * fref):
            continue
        gain = 1.0
        if ntf is not None:
            gain = float(np.interp(f_sp, ntf.f, np.abs(ntf.h)))
        phi1 = TWOPI * fout * a * gain          # peak output phase [rad]
        dbc = float(20.0 * np.log10(max(phi1 / 2.0, 1e-30)))
        key = round(f_sp, 3)
        # two harmonics can fold onto the same offset; powers add
        if key in out:
            dbc = float(10.0 * np.log10(10 ** (dbc / 10) + 10 ** (out[key] / 10)))
        out[key] = dbc
    return out
