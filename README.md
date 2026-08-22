# pllsim — System-Level / Behavioral PLL Simulation

Python behavioral models of six PLL architectures with phase-noise budgeting,
spurious analysis and built-in calibration algorithms.

**Illustrated design guide** (bilingual EN/中文): open
[`docs/index.html`](docs/index.html) in a browser — design rationale, worked
examples with plots, cross-domain result comparisons and lessons learned.

Also: [`CONTRIBUTING.md`](CONTRIBUTING.md) (setup, the conventions that bite,
how to add a preset/example/architecture, how a release actually happens),
[`docs/config-reference.md`](docs/config-reference.md) (every editable config
field with its units), [`docs/release-notes/`](docs/release-notes) (one file
per version: which number changed and why) and
[`docs/roadmap.md`](docs/roadmap.md) (known gaps, measured — plus the limits
that are scope rather than backlog).  MIT licensed.

| Architecture | Frequency domain | Time domain | Example | Jitter class |
|---|---|---|---|---|
| Charge-pump PLL (int-N / frac-N + DTC) | s-domain linear phase model | ref-edge event-driven | ex01, ex02 | ~170–260 fs |
| Sub-sampling PLL (+ FLL, int-N & **frac-N/DTC**) | **exact discrete z-domain** | ref-edge event-driven | ex03, ex08 | ~135–150 fs |
| Sampling PLL (reference-sampling, int-N & **frac-N/DTC**) | s-domain | ref-edge event-driven | ex04, ex14 | ~75–200 fs |
| ADPLL (counter+TDC / DTC+BBPD) | exact z-domain | ref-edge event-driven | ex05 | ~110 fs |
| Injection-locked clock multiplier (+ FTL, timing cal) | z-domain realignment model | per-cycle recursion (+intra-period spur sampling) | ex06, ex08 | ~115 fs |
| Multiplying DLL (edge replacement + digital tuning) | 1−ZOH oscillator NTF | per-cycle recursion (+intra-period sampling) | ex12 | ring-limited |

Beyond the architectures: **loop synthesis** (`pllsim.synth` — filter/DLF
component values from UGB/PM targets, jitter-vs-bandwidth optimization, ex07),
**second-order impairments** (Kvco nonlinearity, supply pushing, reference-
doubler duty error, coarse band selection — ex09), **literature benchmarks
against four JSSC papers** — Gao'09/'10 integer-N SSPLL (ex10, in-band
−126 dBc/Hz / 0.15 ps class), Dartizio'23 DTC+BBPD digital PLL (77 fs @
9.25 GHz), Markulić'16 fractional DTC-SSPLL (176/198 fs @ 10.24 GHz) and
Wu'19 fractional sampling PLL (75 fs @ 6.25 GHz, 10 kHz–10 MHz band) — all
landing on the published jitter with labelled technology-plausible
assumptions (ex14), **deterministic fractional-spur prediction** (bit-true
MASH-through-DTC tones referred through the loop NTF, 0.2 dB against the
time domain; worst-channel law and INL spec extraction — ex15),
**bench-data import** (`pllsim.fit`: Leeson fit, closed-loop estimators,
NNLS budget attribution with identifiability groups — ex16), **two-point
GMSK modulation + EVM** (`pllsim.modulation`, ADPLL and SSPLL injection —
ex17), an **architecture selector** (`pllsim.selector` ranks all seven
architectures against a requirement with synthesized loops — ex18),
**channel-hop settling analysis** (`pllsim.settling`: pull-in/phase
settling instants, seed-population statistics and the FLL hand-off
stability bound — ex19), **drift-tracking validation** (per-cycle DTC
gain trajectories through the background LMS: tracking walls, spur
penalty, mu selection rule — ex20), **named PVT corners, lock detection and
injection pulling** (`pllsim.corners` applies SS/FF/SF/FS without retuning
the loop, `blocks.lockdetect` is the asymmetric up/down counter real silicon
ships, `OscConfig.pull_*` is Adler — ex21), **Monte Carlo yield analysis**
(`pllsim.montecarlo` — multiprocess mismatch/corner sweeps with calibration
running per chip, ex11: 100 chips in ~77 s), and a **Verilog-AMS export
bridge** (`pllsim.export`, ex13 — per config: bit-true synthesizable RTL for
the digital blocks verified with iverilog at zero tolerance, a cycle-true
wreal/RNM top with golden-CSV testbench for Cadence digital-top regressions,
and an electrical VAMS netlist for block-level AMS verification).

Coverage targets: fref = 19.2–250 MHz, fout up to 12 GHz, integrated jitter
50–200 fs (1 kHz–100 MHz band, configurable).

## Install & run

```bash
pip install -e .          # numpy, scipy, matplotlib
pytest tests/             # 461 tests: closed-form math + architecture behavior
python examples/ex01_cppll_intn_19p2m_4p8g.py   # plots land in examples/out/
```

**GUI** — every capability behind a workbench, in two flavors:

```bash
pip install -e .[gui]     # browser (streamlit), bilingual zh/EN
pllsim-web

pip install -e .[guiqt]   # native desktop (PySide6), bilingual zh/EN
pllsim-gui                # or: python -m pllsim.guiqt
```

Pages (both flavors): architecture workbench (preset -> edit every Config
field -> analyze/simulate with plots), loop synthesis, architecture
selector, spur prediction, measured-PN fitting, two-point modulation, hop
settling, drift tracking, Monte Carlo, VAMS export, benchmarks.

**Windows executables** (no Python needed): two GitHub Actions workflows
build ONEFILE exes for both GUIs and smoke-test them on the runner before
upload — `windows-exe` (PyInstaller: fast build, self-extracting) and
`windows-exe-nuitka` (Nuitka: real C compilation via MSVC — much slower
build, faster startup; qt and web build as independent jobs).  Trigger
either from Actions -> Run workflow and pick `target` = `qt`, `web` or
`both` — these are Windows runners and the web compile is the long one,
so both is opt-in.  Download `pllsim-gui-qt[-nuitka].exe`
(desktop, windowed) and `pllsim-gui-web[-nuitka].exe` (starts the local
server and opens your browser; its console window is the server log) from
the run's artifacts, or pass an existing release tag to attach them as
release assets.  Expect large files (Python + numpy/scipy/matplotlib
bundled; the web exes also carry streamlit).

**Android app** (workbench only, fully offline): `android/` is a Gradle
project embedding CPython via Chaquopy — a WebView front end over
`pllsim.appbridge`, with the parameter form generated from the same
`guiutil.FIELD_INFO` as both desktop GUIs.  Build a sideload APK from
Actions -> Android APK -> Run workflow (manual only; it is not a release
gate), or locally with Android Studio opened on `android/` — after first
running `python -m build --sdist --outdir android/app/pysrc .` from the
repo root, which produces the pllsim archive the app embeds (the Gradle
config refuses to guess and says exactly this if it is missing).  The app pins
Python 3.10 because Chaquopy's package repository has no scipy wheel for
anything newer — the pyproject dependency floors are verified against that
stack, and `cairn/android-app.md` records the constraints before you change
any of this.

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

* **Reference spurs** (at fref and its harmonics): analytic ripple models per
  architecture, and measurable in the time domain with `fine_oversample`.
  In lock a type-II loop has already zeroed the *net* per-period charge, so
  what remains is a doublet of opposite-sign pulses that cancels in area; the
  fref component survives only through `2·sin(π·fref·Δt)`, which is 38 dB of
  suppression for a 200 ps reset at 19.2 MHz.  Leakage is exempt — a constant
  current has no fref component, so its whole fundamental comes from the
  narrow correction pulse.
* **Fractional spurs** (< fref/2): expected offsets from `frac_spur_offsets`
  (k·frac folded), measured by noise-floor-subtracted integration of the
  full-length periodogram (`core.spectrum.find_spurs`); NaN = below floor.
* **Injection spurs** (fref offset): ILCM records the intra-period phase ramp
  analytically at M× oversampling so the spur is visible in the FFT, plus the
  sawtooth analytic estimate.

## Repository layout

```
src/pllsim/
  core/        freqresp, noise, jitter, spectrum, colored, deltasigma, engine,
               results, dtcspurs, tdcspurs
  blocks/      loopfilter, oscillator, chargepump, dtc, tdc, sampler, lockdetect
  calibration/ lms, gain_cal, ftl
  arch/        base, cppll, sspll, spll, adpll, ilcm, mdll
  export/      RTL + RNM + electrical-VAMS emitters, golden engine, manifest
  guiqt/       PySide6 desktop GUI      webgui/  Streamlit web GUI
  corners.py  fit.py  modulation.py  montecarlo.py  selector.py
  settling.py  synth.py
  guiutil.py   GUI-support introspection (no GUI dependency)
  appbridge.py JSON bridge for embedded hosts (the Android app)
  plotting.py  presets.py
examples/      ex01..ex21 (plots into examples/out/)
tests/         closed-form core math + architecture-level regressions
```

## What CI enforces

`ruff` on `src tests examples packaging`; `mypy` on the physics core, the
blocks, the calibrators and the analysis modules (the file list is in
`pyproject.toml` — `arch/` and `webgui/pages/` are named there as *not yet*
checked rather than silenced, so the gate cannot be mistaken for whole-package
coverage); the full test suite on Python 3.11 and 3.12 with a coverage floor.

Two things the coverage number does not say.  The Streamlit pages are driven
by 23 tests through `AppTest`, which execs each file rather than importing it,
so coverage attributes none of it — `webgui/Home.py` reads 0% while its test
passes.  And a covered line is a line that ran, not a line whose answer was
checked; the physics is pinned by cross-domain comparison, not by that
percentage.

## Known modeling limits

* CPPLL/SPLL `analyze()` uses the continuous-time approximation (warned when
  UGB > fref/10); the SSPLL and ADPLL use exact discrete models.  Cross-domain
  tests bound the residual CT-vs-DT deviation.
* A record taken once per reference edge cannot show spurs at ≥ fref/2 — the
  control node's ripple lives inside one reference period, so one sample per
  edge sees a single point on it.  Pass `fine_oversample=M` and the analog
  loops record M control-voltage samples per period from the charge pump's
  actual current waveform, which puts the reference spur in the FFT
  (`simulate()` then reports it in `spurs_fft`; 0.02 dB against the analytic
  model at M = 512).  M must resolve `cp.t_reset` or the reading comes back
  low, and both GUIs say so next to the knob.  ILCM and MDLL oversample by
  default because their jitter figure is defined inside the period.
* TDC/DTC quantization in-band noise is treated as white in the linear model;
  the deterministic (tonal) component appears in the time domain only.
* BBPD linearization is conservative when the loop is quantization-dominated;
  the time-domain result is the reference.
