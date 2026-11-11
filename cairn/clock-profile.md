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

## After an integer multiplier (issue #71, 2026-11-11)

Second consumer: mmw60_trx (60 GHz transceiver) builds its LO as a sub-7 GHz
PLL followed by xN, and reads only the file.  Agreed on the issue and
implemented as `write_clock_profile(..., multiply_by, floor_dbchz,
spur_rejection_db)` / `pllsim export --multiply-by`:

- **N is an integer >= 2.**  The request moved a 6.253 GHz profile to
  60.48 GHz by 20*log10(9.672); the realisable chain retunes the PLL to
  f_c/N.  Wu'19 at 6.048 GHz (N = 10) also needs `osc.f0` recentred: from
  6.2 GHz it trips `tuning-swing` (-2.53 V); 82.16 fs either way.
- **Up to f_in/2: N^2 * L_in + floor; above: floor alone.**  The PLL's
  profile has no information past f_in/2, so nothing is extrapolated and the
  step at f_in/2 is where the PLL's curve ends.  Interpolating the input onto
  the output grid costs 0.00007 dB worst (measured on the 6.048 GHz curve).
- **No defaults for the floor or the harmonic rejection.**  Nothing here
  measures a multiplier; ex22's -160 dBc/Hz / 40 dB are labelled placeholders
  in the file's `source`.  Correction to my first reply on the issue: I took
  mmw60_trx's "-85..-110 dBc/Hz @ 1 MHz" for a multiplier floor; it is the
  LO level at 1 MHz they sweep (Wu'19 x10 is -98.5 there).  A floor shows
  only above the PLL's far-out x N^2 level, about -134 dBc/Hz.
- **Spurs:** input spurs + 20*log10(N); the N-1 / N+1 leakage is ONE entry
  at f_in, because the format's spur is already a PM sideband pair.  My
  issue reply said "two entries"; one is what the format means.
- **Four keys of their own** (`multiply_by`, `f_in_hz`, `floor_dbchz`,
  `spur_rejection_db`), all or none, written only when multiplied.  The
  unmultiplied files kept the same keys and data, byte for byte (checked on
  8 presets), because this library's own reader rejected unknown keys and
  Halo_Serdes' reader is not known to accept them.  (Correction 2026-11-11:
  the comment lines have changed since, see "Sideband wording" below; the
  data lines have not.)
- **Frequency-plan finding, not a model one:** 60.48 GHz / 52 MHz =
  15120/13, so every integer N puts the divider on a k/13 fraction and the
  first fractional tone at fref/13 = 4 MHz: -63.7 dBc at 6.048 GHz, -43.7 x10.
  Only a different reference frequency moves it.

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

## Sideband wording in the file header (2026-11-11)

mmw60_trx converted `ipn_dbc` to phase variance without the factor 2 and was
3 dB low on every phase-noise EVM term; the file said `L(f) = S_phi/2` but
not "single-sideband" in words.  The header now states, and tests check
against the library: `l_dbc_hz` is SSB; S_phi = 2 * 10^(L/10); an
integrated SSB dBc is 10*log10(variance/2) (equals `ipn_dbc` to 1e-9 dB on
all seven anchors); a spur's `dbc` is one sideband of a PM pair, peak phase
deviation 2 * 10^(dbc/20) (`find_spurs` on a synthetic tone agrees to
< 1e-4 dB; the RMS reading would be 3.01 dB off).  Only `#` lines changed.

Open, not ours to fix: the Halo_Serdes plan document gives a spur's sine
amplitude as sqrt(2 * 10^(dbc/10)) / (2 pi f0).  That is the RMS phase, not
the peak, so a sine built with it is 3 dB low.  The plan is a document, and
whether Halo_Serdes' code does this is unverified.

Correction 2026-11-11, after reading halo_serdes@13ef843: its code is right.
`tx/clock.py::spur_amplitudes_s` uses the peak, 2 * 10^(dbc/20), and its
docstring names the RMS form as the RMS.  The 3 dB error was only ever in
the plan document.  The same read found two real consumer-side problems,
raised as halo_serdes#149:

- Its `f0_hz` override is documented for "a divided or multiplied clock"
  and changes only the phase-to-seconds scale.  For xN the curve should rise
  20*log10(N) and seconds stay put, so the override gives N times too little
  jitter: measured with its own `ClockProfile`, Wu'19 reads 80.85 fs, the
  override to x10 reads 8.09 fs, our real x10 file reads 80.85 fs.
- Its loader rejects unknown keys, so a multiplied file from #72 does not
  load (`unknown clock-profile key(s) ['f_in_hz', ...]`).  The format is
  theirs to extend; until they decide, multiplied files are for mmw60_trx.

Its shipped profiles cite `67fe1c7`, reachable only as refs/pull/67/head;
the tree equals main's squash commit `63d1012`.

## Pitfalls

- A profile written from a default `analyze()` of a > 2 GHz preset is
  refused by design; the fix is the one-keyword change the error names, not
  a wider tolerance and not a flat tail.
- The `source` line carries the commit of the checkout the writer ran from,
  so a file regenerated after a merge changes in that line only.
