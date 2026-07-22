# pllsim — System-Level / Behavioral PLL Simulation

Python behavioral models of five PLL architectures with phase-noise budgeting,
spurious analysis and built-in calibration algorithms.

**Illustrated design guide** (bilingual EN/中文): open
[`docs/index.html`](docs/index.html) in a browser — design rationale, worked
examples with plots, cross-domain result comparisons and lessons learned.

| Architecture | Frequency domain | Time domain | Example | Jitter class |
|---|---|---|---|---|
| Charge-pump PLL (int-N / frac-N + DTC) | s-domain linear phase model | ref-edge event-driven | ex01, ex02 | ~170–260 fs |
| Sub-sampling PLL (+ FLL, int-N & **frac-N/DTC**) | **exact discrete z-domain** | ref-edge event-driven | ex03, ex08 | ~135–150 fs |
| Sampling PLL (reference-sampling) | s-domain | ref-edge event-driven | ex04 | ~200 fs |
| ADPLL (counter+TDC / DTC+BBPD) | exact z-domain | ref-edge event-driven | ex05 | ~110 fs |
| Injection-locked clock multiplier (+ FTL, timing cal) | z-domain realignment model | per-cycle recursion (+intra-period spur sampling) | ex06, ex08 | ~115 fs |
| Multiplying DLL (edge replacement + digital tuning) | 1−ZOH oscillator NTF | per-cycle recursion (+intra-period sampling) | ex12 | ring-limited |

Beyond the architectures: **loop synthesis** (`pllsim.synth` — filter/DLF
component values from UGB/PM targets, jitter-vs-bandwidth optimization, ex07),
**second-order impairments** (Kvco nonlinearity, supply pushing, reference-
doubler duty error, coarse band selection — ex09), a **literature benchmark**
reproducing Gao et al.'s JSSC'09/'10 sub-sampling PLL published measurements
(ex10, in-band −126 dBc/Hz / 0.15 ps class), and **Monte Carlo yield
analysis** (`pllsim.montecarlo` — multiprocess mismatch/corner sweeps with
calibration running per chip, ex11: 100 chips in ~77 s).

Coverage targets: fref = 19.2–250 MHz, fout up to 12 GHz, integrated jitter
50–200 fs (1 kHz–100 MHz band, configurable).

## Install & run

```bash
pip install -e .          # numpy, scipy, matplotlib
pytest tests/             # 43 tests: closed-form math + architecture behavior
python examples/ex01_cppll_intn_19p2m_4p8g.py   # plots land in examples/out/
```

Quick start:

```python
from pllsim import presets

pll = presets.sspll_19p2m_4p8g()
ar = pll.analyze()                 # linear model: PN breakdown, PM/UGB, jitter
print(pll.design_report(ar))
sim = pll.simulate(300_000, seed=1, f_start_offset=-25e6)   # time domain
from pllsim.plotting import plot_pn_breakdown
plot_pn_breakdown(ar, sim, save="pn.png")   # overlay: model vs periodogram
```

Every architecture follows the same contract (`pllsim.arch.base.PLLBase`):
`analyze()` returns an `AnalysisResult` (per-source PSD breakdown, loop
metrics, analytic spurs, RMS jitter), `simulate()` returns a `SimResult`
(phase/frequency/control trajectories, calibration traces, periodogram,
FFT-extracted spurs).

## Conventions

* Internal phase PSDs are **double-sideband** S_phi(f) in rad²/Hz; plots and
  spot numbers are L(f) = S_phi/2 in dBc/Hz.  Locked down by unit tests.
* RMS jitter: sigma_t = sqrt(∫S_phi df) / (2π f_out), default band 1 kHz–100 MHz.
* Frequency responses are **grid-evaluated** complex responses
  (`core.freqresp.FreqResponse`), not polynomial TFs — s-domain, z-domain,
  pure delay and ZOH elements mix freely and 12 GHz/100 kHz dynamic range
  causes no numerical trouble.
* Time domain runs **one step per reference cycle** (phase accumulation,
  closed-form divider edges, exact `expm`-based loop-filter updates) — no
  nanosecond time stepping at 12 GHz.
* Cross-domain regression: for every dual-domain architecture the settled
  time-domain periodogram must match the linear model within 2–3 dB
  band-averaged (test-enforced).

## Architecture notes

### CPPLL (`arch/cppll.py`)
Open loop `G(s) = Icp·Kvco·Z(s)/(N·s)` with 2nd/3rd-order passive filter
(state-space, exact discrete updates verified against `solve_ivp`).
Noise: reference & divider (×N·H), CP current (duty-cycled, ×2πN/Icp·H),
filter resistors (×2πKvco/s·E), VCO (×E), MASH-m ΔΣ quantization
(shaped, ×H; after DTC cancellation scaled by residual gain error and INL).
Reference spur analytic: mismatch/leakage charge → control ripple V1 →
`20·log10(Kvco·V1/2fref)`.  Time domain models the PFD/CP with cycle-slip
clamp, acquisition, fractional spurs and LMS/LUT DTC calibration transients.

### SSPLL (`arch/sspll.py`)
No divider in the loop; PD gain `A [V/rad]` is referred to **output** phase,
so CP/LF noise is not N-multiplied (reference noise still is — inherent to
×N multiplication).  Because SSPLLs run aggressive UGB/fref, `analyze()` uses
the **exact discrete loop** (`LoopFilter.charge_tf_z`, matching the simulated
update law); loop-injected noise images are ZOH-attenuated and the continuous
VCO keeps E→1 beyond fref/2.  The SSPD sine nonlinearity false-locks at any
integer multiple of fref — the hysteretic counter-FLL (proportional taper
inside the release band) acquires and hands off; both behaviors are
demonstrated and test-enforced.

### SPLL (`arch/spll.py`)
Reference-sampling dual: a divided VCO edge samples the reference sine, PD
gain referred to **reference** phase ⇒ sampler kT/C and gm noise are
×N at the output.  Same front-end as the SSPLL — ex03 vs ex04 is the honest
architecture comparison.

### ADPLL (`arch/adpll.py`)
Counter-assisted (Staszewski) mode: FCW accumulator vs counter+TDC, DLF
`L(z) = α + ρ/(1−z⁻¹)` (+IIR stages), normalized DCO, 1st-order dithered DCO
quantization.  Exact z-domain `G(z) = L(z)·(Kdco/K̂dco)·z⁻¹/(1−z⁻¹)` including
the update delay.  Calibrations: **KDCO FCAL** (open-loop two-point — a
closed-loop two-point measurement is information-free because the integrator
absorbs the perturbation), **TDC period normalization** (codes-per-period
EMA cancels TDC gain error exactly).  DTC+BBPD mode: MASH+DTC alignment,
bang-bang PD with self-consistent linearization `Kbb = sqrt(2/π)/σt`
(fixed-point iteration), sign-sign LMS DTC gain calibration.

### ILCM (`arch/ilcm.py`)
Per-reference-cycle realignment `e⁺ = (1−β)·wrap(e + Δφ_drift + φ_osc) + β·φ_inj`.
Oscillator noise enters as per-cycle phase increments ⇒ phase-PSD NTF
`(1−β)(1−z⁻¹)/(1−(1−β)z⁻¹)` (highpass, injection bandwidth ≈ β·fref/2π);
reference/injection-path lowpass ×N.  The nearest-edge wrap gives the lock
range `β·fref/2` (Adler LC cross-check `f0·Iinj/(2Q·Iosc)` reported).
Injection spur = first Fourier coefficient of the drift sawtooth — matches
the time-domain FFT within 1 dB across a 0.25–8 MHz error sweep (ex06).
The bang-bang FTL keeps the free-running frequency aligned; its residual
sets the spur floor.

## Calibration library (`calibration/`)

| Algorithm | Used by | Notes |
|---|---|---|
| `LMSGainCal` / `SignSignLMS` | DTC gain (CPPLL/ADPLL) | error-DC removal built in — the loop's equilibrium phase error is nonzero (CP mismatch/leakage) and would saturate a raw sign correlator |
| `LUTCal` | DTC INL | piecewise LUT, visit-weighted mean/ramp projection restricted to visited bins |
| `KdcoCal` | ADPLL | open-loop two-point FCAL state machine |
| `TdcPeriodCal` | ADPLL | Staszewski period normalization |
| `FLLStateMachine` | SSPLL/SPLL | counter FD, hysteresis, proportional taper in the release band |
| `FTL` | ILCM | bang-bang free-running frequency tracking, gear-shift option |
| `InjTimingCal` | ILCM | sign-sign LMS on injection timing |

All calibrators record `.trace` for convergence plots
(`plotting.plot_cal_convergence`).

## Spur analysis

* **Reference spurs** (≥ fref/2 offsets alias to DC at reference-rate
  sampling): analytic ripple models per architecture.
* **Fractional spurs** (< fref/2): expected offsets from `frac_spur_offsets`
  (k·frac folded), measured by noise-floor-subtracted integration of the
  full-length periodogram (`core.spectrum.find_spurs`); NaN = below floor.
* **Injection spurs** (fref offset): ILCM records the intra-period phase ramp
  analytically at M× oversampling so the spur is visible in the FFT, plus the
  sawtooth analytic estimate.

## Repository layout

```
src/pllsim/
  core/        freqresp, noise, jitter, spectrum, colored, deltasigma, engine, results
  blocks/      loopfilter, oscillator, chargepump, dtc, tdc, sampler, divider
  calibration/ lms, gain_cal, ftl
  arch/        base, cppll, sspll, spll, adpll, ilcm
  plotting.py  presets.py
examples/      ex01..ex06 (plots into examples/out/)
tests/         closed-form core math + architecture-level regressions
```

## Known modeling limits

* CPPLL/SPLL `analyze()` uses the continuous-time approximation (warned when
  UGB > fref/10); the SSPLL and ADPLL use exact discrete models.  Cross-domain
  tests bound the residual CT-vs-DT deviation.
* Reference-rate time-domain simulation cannot show spurs at ≥ fref/2 — those
  are reported analytically (ILCM additionally oversamples analytically).
* TDC/DTC quantization in-band noise is treated as white in the linear model;
  the deterministic (tonal) component appears in the time domain only.
* BBPD linearization is conservative when the loop is quantization-dominated;
  the time-domain result is the reference.
