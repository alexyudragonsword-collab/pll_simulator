"""Fixed-point coefficient handling and bit-true Python mirrors.

FixedCoeff decides how a real coefficient is realized in RTL:
  * exact power of two  -> arithmetic shift (SHIFT localparam)
  * otherwise           -> signed W-bit fixed-point multiplier constant,
                           quantization error recorded (raise if > tolerance)

DlfFx / SignSignLmsFx are bit-true Python mirrors of the generated RTL
datapaths.  RTL golden vectors come from THESE (zero-tolerance comparison in
iverilog); separate tests assert each mirror tracks its float original.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field


@dataclass
class FixedCoeff:
    value: float
    frac_bits: int = 16          # F for the quantized path
    max_rel_err: float = 1e-3

    is_pow2: bool = field(init=False)
    shift: int = field(init=False, default=0)        # value = 2^-shift (pow2 path)
    q: int = field(init=False, default=0)            # quantized integer (fixed path)
    rel_err: float = field(init=False, default=0.0)

    def __post_init__(self):
        v = float(self.value)
        if v == 0.0:
            self.is_pow2, self.shift = True, 0
            self.q = 0
            return
        m, e = math.frexp(abs(v))    # v = m * 2^e, m in [0.5, 1)
        if m == 0.5 and v > 0:
            self.is_pow2 = True
            self.shift = -(e - 1)    # v = 2^(e-1) -> right shift by -(e-1)
            return
        self.is_pow2 = False
        self.q = int(round(v * (1 << self.frac_bits)))
        if self.q == 0:
            raise ValueError(
                f"coefficient {v:g} underflows {self.frac_bits} fractional bits")
        realized = self.q / (1 << self.frac_bits)
        self.rel_err = abs(realized - v) / abs(v)

    def realized(self) -> float:
        if self.is_pow2:
            return 0.0 if self.value == 0.0 else \
                math.copysign(2.0 ** (-self.shift), self.value)
        return self.q / (1 << self.frac_bits)

    def check(self, name: str, warnings: list[str],
              allow_quantized: bool = True) -> None:
        if self.is_pow2:
            return
        msg = (f"{name} = {self.value:g} is not a power of two: quantized to "
               f"{self.q}/2^{self.frac_bits} (rel err {self.rel_err:.2e})")
        if self.rel_err > self.max_rel_err and not allow_quantized:
            raise ValueError(msg)
        warnings.append(msg)


# ------------------------------------------------------------- RTL mirrors
class DlfFx:
    """Bit-true mirror of the generated DLF RTL.

    Datapath: input e as signed integer in units of 2^-F_IN (UI or LSB),
    y = (alpha * e) + acc,  acc += rho * e,  then IIR stages
    y_k += lam * (y_{k-1} - y_k), all in the same 2^-F_IN grid with
    power-of-two coefficients realized as arithmetic shifts.
    Arithmetic-shift-right of negative numbers = floor division (matches
    Verilog >>> on two's-complement).
    """

    def __init__(self, alpha: FixedCoeff, rho: FixedCoeff,
                 iir: tuple[FixedCoeff, ...] = ()):
        for c in (alpha, rho) + tuple(iir):
            if not c.is_pow2:
                raise NotImplementedError(
                    "DlfFx v1 supports power-of-two coefficients only "
                    "(all shipped presets qualify)")
        self.sh_a = alpha.shift
        self.sh_r = rho.shift
        self.sh_iir = tuple(c.shift for c in iir)
        self.acc = 0
        self.iir_state = [0] * len(iir)

    @staticmethod
    def _sar(v: int, s: int) -> int:
        return v >> s if s >= 0 else v << (-s)

    def step(self, e_fx: int) -> int:
        self.acc += self._sar(e_fx, self.sh_r)
        y = self._sar(e_fx, self.sh_a) + self.acc
        for i, sh in enumerate(self.sh_iir):
            self.iir_state[i] += self._sar(y - self.iir_state[i], sh)
            y = self.iir_state[i]
        return y


class SignSignLmsFx:
    """Bit-true mirror of the sign-sign LMS RTL.

    gain word: signed integer in units of 2^-F_G around 1.0 (= 1<<F_G);
    error/regressor DC removal by EMA with power-of-two ema = 2^-SH_EMA on
    the same fixed grids as the inputs; mu gearshift by cycle-count compare.
    Updates use only sign bits — bit-true regardless of input scaling.
    """

    def __init__(self, f_gain: int, mu: FixedCoeff, sh_ema: int,
                 gear_shift_n: int | None = None, mu_final: FixedCoeff | None = None):
        if not mu.is_pow2 or (mu_final is not None and not mu_final.is_pow2):
            raise NotImplementedError("LMS mu must be a power of two in RTL v1")
        self.f_gain = f_gain
        self.gain = 1 << f_gain                  # 1.0
        self.sh_mu = mu.shift
        self.sh_mu_final = mu_final.shift if mu_final else mu.shift
        self.gear_n = gear_shift_n
        self.sh_ema = sh_ema
        self.err_mean = 0                        # in err fixed grid
        self.reg_mean = 0                        # in reg fixed grid
        self.n = 0

    def step(self, err_fx: int, reg_fx: int) -> int:
        # EMA centering: mean += (x - mean) >>> SH_EMA (floor, as in RTL)
        self.err_mean += (err_fx - self.err_mean) >> self.sh_ema
        self.reg_mean += (reg_fx - self.reg_mean) >> self.sh_ema
        e = err_fx - self.err_mean
        d = reg_fx - self.reg_mean
        sh = self.sh_mu if (self.gear_n is None or self.n <= self.gear_n) \
            else self.sh_mu_final
        step = 1 << max(self.f_gain - sh, 0)     # mu in gain-word LSBs
        if e != 0 and d != 0:
            self.gain += step if (e > 0) == (d > 0) else -step
        self.n += 1
        return self.gain

    @property
    def gain_float(self) -> float:
        return self.gain / (1 << self.f_gain)


class FtlFx:
    """Integer mirror of pllsim_ftl RTL."""

    def __init__(self, mu: int = 1, gear_n: int = 0, mu_f: int = 1):
        self.mu, self.gear_n, self.mu_f = mu, gear_n, mu_f
        self.f_code = 0
        self.n = 0

    def step(self, drift_pos: bool, drift_zero: bool) -> int:
        mu = self.mu_f if (self.gear_n and self.n > self.gear_n) else self.mu
        self.n += 1
        if not drift_zero:
            self.f_code += -mu if drift_pos else mu
        return self.f_code


class BandSelectFx:
    """Integer mirror of pllsim_bandselect RTL (counts domain)."""

    def __init__(self, n_bands: int, target_counts: int):
        self.target = target_counts
        self.lo, self.hi = 0, n_bands - 1
        self.band = (n_bands - 1) // 2
        self.best_band = self.band
        self.best_err = (1 << 62)
        self.done = n_bands <= 1

    def observe(self, meas_counts: int) -> tuple[int, bool]:
        if self.done:
            return self.band, True
        err = meas_counts - self.target
        improved = abs(err) < self.best_err
        if improved:
            self.best_err = abs(err)
            self.best_band = self.band
        if err < 0:
            if self.band == self.hi:
                self.done = True
                self.band = self.band if improved else self.best_band
            else:
                self.lo = self.band + 1
                self.band = (self.lo + self.hi) // 2
        else:
            if self.band == self.lo:
                self.done = True
                self.band = self.band if improved else self.best_band
            else:
                self.hi = self.band - 1
                self.band = (self.lo + self.hi) // 2
        return self.band, self.done


class FllFx:
    """Integer mirror of pllsim_fll RTL (counts domain)."""

    def __init__(self, window: int, n_target_counts: int, th_eng: int,
                 th_rel: int, hyst: int = 3):
        self.window, self.n_target = window, n_target_counts
        self.th_eng, self.th_rel, self.hyst = th_eng, th_rel, hyst
        self.engaged = True
        self.ferr = 0
        self.acc = 0
        self.w = 0
        self.quiet = 0

    def step(self, cycles: int) -> tuple[bool, int]:
        if self.w == self.window - 1:
            ferr = self.acc + cycles - self.n_target
            self.acc, self.w = 0, 0
            self.ferr = ferr
            a = abs(ferr)
            if self.engaged:
                if a < self.th_rel:
                    if self.quiet == self.hyst - 1:
                        self.engaged, self.quiet = False, 0
                    else:
                        self.quiet += 1
                else:
                    self.quiet = 0
            else:
                if a > self.th_eng:
                    if self.quiet == self.hyst - 1:
                        self.engaged, self.quiet = True, 0
                    else:
                        self.quiet += 1
                else:
                    self.quiet = 0
        else:
            self.acc += cycles
            self.w += 1
        return self.engaged, self.ferr
