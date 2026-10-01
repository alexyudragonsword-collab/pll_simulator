# Clock phase-noise profile: the seam between pllsim and a SerDes link

Current truth about the one file pllsim hands to Halo_Serdes, established
2026-10-01 with `src/pllsim/export/clock_profile.py`, ex22 and
`tests/test_export_clock_profile.py`.  The plan it implements is the
"pll_simulator 接入 Halo_Serdes 时钟路径" document (claude.ai artifact
b92e525d-117a-47a5-a3ea-e42c8d811415); the consumer side of that plan lives
in the Halo_Serdes repository, not here.

## The contract

- One YAML file per clock: `f0_hz`, `f_hz` (log-uniform, 100 Hz .. f0/2),
  `l_dbc_hz` (the **total** L(f) of the linear model, same length), `spurs`
  (`[{f_hz, dbc}]`, offset ascending) and `source` (English free text:
  preset, model, package version, commit).  The format is the consumer's;
  pllsim obeys it and adds nothing but `#` comment lines.
- `l_dbc_hz` is L(f) = S_phi/2 -- single sideband -- not the double-sideband
  S_phi this package carries internally.  Timing is phase / (2 pi f0_hz); the
  file states f0 so a half-rate clock is not converted with 1/UI.
- The two libraries do not import each other.  The writer is numpy-only
  (checked by a static import test) because the consumer's phone build
  carries numpy and scipy and vendors `core/colored.py::synth_from_psd` and
  `core/jitter.py::integrate_pn` from here.
- Producer entry points: `write_clock_profile(ar, path, *, source, fref)`,
  `read_clock_profile(path)` (hand-rolled reader for exactly this subset so
  the base install needs no YAML library; PyYAML is the reference parser in
  the tests, in the `[test]` extra), `profile_grid(f0)`, `default_source()`,
  `pllsim export <preset> --clock-profile FILE`, and ex22 for the seven JSSC
  anchors of ex14.

## Decisions, with the measurements behind them

- **Analyse on the profile grid; never extrapolate.**  The default
  `analyze()` grid stops at 1 GHz while f0/2 is 1.2-5.1 GHz for six of the
  seven anchors.  Holding the last model value flat to f0/2 reads as the
  obvious fallback and integrates the Dartizio ADPLL to 747 fs over
  100 Hz..f0/2 against the model's own 179 fs, because the default grid's
  last point sits on a z-domain lobe at exactly 2 fref.  `profile_curve`
  therefore raises on a grid that does not reach f0/2 and names
  `profile_grid` in the message; the CLI and ex22 analyse on it, so the
  seven shipped files carry the model point for point and the file's
  integral equals `ar.jitter_fs` to round-off (gate 1e-6, algebra).
- **Resampling is a fallback and its error is where the curve is sharp.**
  A foreign grid is interpolated linearly in (log f, dB).  Measured by
  interpolating the profile back onto the model's own points: 0.0039 dB on
  the s-domain SPLL from a 37/decade grid; 0.366 dB on the MDLL's default
  grid at 185 MHz, the 1-ZOH null near fref/2, with a 99th percentile of
  0.0015 dB.  The null is a resolution limit of any 60/decade grid, the
  model's own included, so the gate is the percentile and the maximum is
  pinned, not widened.
- **PyYAML floats.**  `repr` writes `1e-05` and `1e+16`; YAML 1.1's resolver
  wants a dot in the mantissa and a signed exponent and otherwise hands the
  consumer a *string*.  `yaml_float` repairs the form and keeps the value
  bit-exact; a test parametrised over the awkward cases pins it.
- **Spur offsets come from the key.**  `frac_spur@<f>Hz` carries its own;
  `ref_spur` sits at fref, which `AnalysisResult` does not hold, hence the
  `fref=` keyword (raises without it).  `frac_offset_hz` in the same dict is
  a frequency annotation, not a spur, and is left out; a non-finite level is
  left out too.

## Known limits (measured 2026-10-01, the seven anchors on the profile grid)

- The whole-profile jitter (100 Hz..f0/2) is what a consumer integrating the
  file end to end sees, and for the sampled-loop models it is far above the
  benchmark band figure: ADPLL 179 fs vs 59 in band, ILCM 639 vs 83, MDLL
  875 vs 541; the s-domain loops sit within 10-15 % of their band figure.
  That is the clock the model describes, not an export artefact -- but the
  z-domain lobes above fref are only roughly resolved by a log grid: the
  ADPLL's whole-profile jitter reads 179 / 160 / 176 fs at 60 / 200 / 600
  points per decade and the ILCM's 639 / 672 / 674, while in-band figures
  move by < 2e-4.  Whether Halo_Serdes should see those lobes at all is a
  question about the sampled-loop models above fref, deferred with the
  plan's "剖面频偏下限" item; the density is a keyword on `profile_grid`.
- `ar.jitter_fs` on the profile grid differs from the default-grid figure by
  up to 3e-6 relative (Markulic 164.7116 vs 164.7121 fs): same model, a
  different trapezoid.  The benchmark tests keep reading the default grid.

## Pitfalls

- A profile written from a default `analyze()` of a > 2 GHz preset is
  refused by design; the fix is the one-keyword change the error names, not
  a wider tolerance and not a flat tail.
- The `source` line carries the commit of the checkout the writer ran from,
  so a file regenerated after a merge changes in that line only.
