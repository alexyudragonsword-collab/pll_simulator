# Compiled kernels: the time-domain loops with and without numba

Current truth about how the six engines' per-cycle loops run, established
2026-09-10 (health-check plan item 21, P4).  Supersedes the "pure Python
per-cycle for loop" statement in the 2026-09-08 health check.

## What it is

- Every engine's loop and every block's per-cycle arithmetic is a *kernel*:
  a module-level function of scalars and arrays, decorated with
  `core.jit.kernel`.  With `pip install -e .[fast]` (numba) the decorator
  compiles it on first use and caches the machine code next to the module;
  without numba it returns the function unchanged.  `PLLSIM_JIT=0` forces
  the interpreted path.  `core.jit.backend()` says which one is running.
- Block objects (`LoopFilter`, `ChargePump`, `DTC`, `SamplingPD`, `TDC`,
  `BBPD`, the modulators, the calibrators, the FLL/FTL, the lock detector)
  are the *object view* of the same kernels: their methods pack state into
  the arrays the kernels take and unpack it after.  `arch/base.py` has one
  `*_kernel_args()` helper per block kind, so the engines spell the
  hand-off identically and mypy can count the arguments.
- Random draws: each kernel takes a standard-normal pool drawn before the
  loop and consumes it through a cursor in the order the block objects used
  to draw.  numpy's Generator gives the same stream one sample at a time or
  all at once (verified), so the realizations did not change.

## Measured (40k cycles, seed 1, this container, 2026-09-10)

| run | Python | numba | speed-up |
|---|---|---|---|
| cppll_19p2m_4p8g | 0.39 s | 0.032 s | 12x |
| cppll_frac_38p4m_6g | 0.83 s | 0.039 s | 21x |
| sspll_frac_19p2m_4p806g | 0.73 s | 0.036 s | 21x |
| spll_frac_52m_6p253g | 1.42 s | 0.035 s | 40x |
| adpll_100m_10g (tdc) | 0.16 s | 0.023 s | 7x |
| adpll_bb_100m_10g | 0.41 s | 0.034 s | 12x |
| ilcm_250m_12g | 0.19 s | 0.049 s | 4x |
| mdll_150m_2p4g | 0.16 s | 0.038 s | 4x |
| cppll_19p2m_4p8g, fine_oversample=64 | 122 s | 2.5 s | 49x |
| sspll_19p2m_4p8g, fine_oversample=64 | 52 s | 1.0 s | 53x |

The floor at ~25-50 ms is the noise synthesis and the FFT post-processing,
which is why the loops that were already cheap (ILCM, MDLL, TDC-ADPLL)
gain least.  First call in a fresh process pays the compile (2-8 s per
kernel, then cached under `__pycache__`).

## Decisions

- **numba, not Cython, for the host.**  The plan suggested reusing the
  Android Cython flow.  Cython on the untyped object code gives ~1.5-2x;
  the 10-50x needs typed kernels, which in Cython means either a second
  implementation or Cython's pure-Python-mode annotations plus a C compiler
  on every user's machine and a per-platform wheel matrix.  numba is one
  pip install, and the interpreted twin *is the same function*
  (`jit.pure(f)`), so there is nothing to keep in step.  The phone keeps
  Cython (source protection) and runs the kernels interpreted.
- **Bit-identity between the two paths is a test**, not a hope:
  `tests/test_kernels.py` runs every preset both ways (subprocess with
  `PLLSIM_JIT=0`) and requires every record and calibration trace equal to
  the last bit.  Rules a kernel has to follow are in the `core/jit.py`
  docstring; each was found by breaking it (below).
- **Old-vs-new** (goldens of the 0.9.4 loops, 18 presets x 7-11 option
  combinations, 3000 cycles, seed 1; scratch only, not committed): ILCM,
  MDLL, both ADPLL modes bit-identical; CPPLL, SSPLL, SPLL at the 1e-16 to
  1e-9 relative level (the loop filter's `ad @ x` went from BLAS, whose FMA
  differs from an explicit sum in ~half of all 2x2 products, to an explicit
  sum; the SPLL's per-cycle eigen path likewise).  Jitter figures move by
  < 1e-8 relative; nothing in README/docs changed digit.  One deliberate
  realization change: the BBPD metastability coin flip is now the sign of
  the next pool draw instead of a uniform, so runs with
  `bb_meta_window_s > 0` differ from 0.9.4 after their first metastable
  cycle (statistically the same detector; `_extra/adpll_bb_meta` golden:
  6481 -> 6480 fs).

## Pitfalls (each cost a red test)

- `np.exp(scalar)`, `x ** 2`, `x ** 0.5` lower differently in numba (849,
  20, 17 of 20 000 draws differ); `math.exp`, `x * x`, `math.sqrt` do not.
  `np.sin` on a Python float is libm and matches.
- Matrix-vector products go through BLAS; write the 2x2/3x3 loops out.
- **numpy scalars in the interpreted path**: indexing a complex128 array
  yields `np.complex128`, whose division multiplies by a reciprocal where
  CPython and numba divide.  One bit apart at cycle 2195 of 3000 on
  `spll_frac_52m_6p253g`, found only by logging every `lf_pulse` call of
  the interpreted run and replaying it through the compiled kernel.
  `loopfilter.cdiv` spells the division out in real arithmetic.  Float ops
  on numpy scalars are IEEE-identical; complex division is the exception.
- `math.floor`/`round` return ints in a kernel; keep the quantizer outputs
  float (`float(math.floor(x))`) so the types stay what `np.floor` gave.
- A loop variable named `s` shadowed the complex accumulator `s` in
  `lf_drive_fine` -- numba unified the types and ran; mypy caught it.
- mypy counts every argument after a star-argument of *unknown* length as
  one too many; the engines' `cfg` is typed `Any` on the base class, so
  `*c.osc.law_params()` was unknown.  `osc_law_args()` gives it a fixed
  length, and the kernel calls take one `args: tuple[Any, ...]`.
- `KdcoCal` averaged its estimates with `np.mean` (pairwise summation above
  8 elements); the kernel sums serially.  Identical for the default 4
  rounds; a `rounds > 8` run would differ at the ULP.
- `LUTCal`'s projection used `w @ lut`; now a serial sum.  ULP-level on the
  one LUT test, inside its 20 % margin.
- **The mypy gate needs numba AND mypy 2.x in the same environment.**  The
  container ships mypy 1.19, where rebinding an imported `njit` to None is
  accepted; CI installs 2.3.1, where it is "None into an overloaded
  function".  The scratch `venv_ci` had 2.3.1 but no numba (no pip in it),
  so it inferred Any and passed too -- three environments, three answers,
  and only CI's was the gate.  Build one venv with `mypy==2.3.1` plus the
  `[fast]` extra and run the old code through it first: `_load_njit()`
  returns rather than rebinds precisely because that pattern goes red there
  and green here.
