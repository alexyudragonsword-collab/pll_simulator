# Cross-domain consistency: the comparator, the boundaries, the sweep

Current truth about how the linear-model-vs-time-domain contract is verified
and where its limits are.  Established 2026-08-27 (the parameter-space
validation pass); supersedes the scattered per-test knowledge before it.

## The machinery

- `pllsim.validation.compare_domains(pll, n_cycles, seed, ...)` is the one
  comparator.  Band clipped to [3×RBW, 0.45·fs] with every clip recorded;
  thin bins in `skipped`, never dropped silently; same-band jitter for both
  domains; boundary flags computed from `pllsim.core.boundaries` predicates.
- `validation.BOUNDARIES`: each capability limit as (code, predicate,
  extra_db, statement).  The engines' runtime warning notes and the sweep's
  tolerance contract call the *same predicates*, so warning and test cannot
  drift apart.
- `tests/test_cross_domain_sweep.py` (marker `sweep`, own CI job, ~5 min in
  parallel with the 18-min main jobs): 48 operating points across UGB,
  frequency-plan, near-integer-fraction and secondary axes.  Contract per
  point: worst band deviation < base_tol + extra_db of declared-and-active
  flags; over base with no flag = model defect = red; declared flag not
  firing = red.
- `validation.CROSS_DOMAIN_GAPS`: 12 pinned gaps, re-measured every push,
  drift in *either* direction fails (better means the pin is stale).
  Rendered into docs/roadmap.md by gen_roadmap.py — constants only, the
  generator never simulates.

## Physics conclusions (measured, 120k cycles, seed 1)

- **CT peaking (CPPLL/SPLL)**: deviation grows in the fref/8..fref/4 bands,
  with UGB/fref *and* with filter shape (PM 45 vs 58 differs ~1 dB at equal
  UGB).  2.1 dB at the stock 1/20 point → 7.25 dB at fref/9.6, the deepest
  loop the synthesizer will build.  ct-approx boundary fires at fref/10
  (same threshold as the long-standing note); the knee below it is pinned as
  gaps.
- **dsm-tonal**: the model budgets DSM/DTC residual as white
  (ShapedQuantization); the truth is deterministic and tonal.  For
  near-rational fractions the tones sit at frac-related offsets outside the
  band, so the in-band PSD reads *below* the model — sspll_frac stock is a
  flat −6.8 dB (127 vs 272 fs same-band), pinned.  The frac_spur table is
  the deterministic complement; the double-count is a deliberate
  conservative budget, now stated instead of latent.
- **BBPD**: +3.3 dB in-band at stock, inside the +2..4 dB the docs always
  claimed; boundary allowance 1.5 dB over the 3.0 base.
- **SSPLL (exact z-domain) is robust everywhere swept** — the discrete
  model's whole point, now demonstrated rather than asserted.
- **ILCM/MDLL robust on the frequency-plan axis** (0.5–3.5 dB); MDLL's
  fref×2.0 point sits at 3.45 vs its 3.5 tolerance and is pinned.

## Pitfalls (contains: pitfall)

- **A sweep harness can fabricate its own gaps.**  Scaling fref on a
  fractional preset without keeping `cfg.frac.frac` consistent locks the
  loop to the configured fraction, MHz away from cfg.fout.  Every
  "off-plan fractional configs never lock" conclusion from calibration, and
  three 12–16 dB adpll_bb "gaps" briefly pinned, were this bug.  With
  consistent configs those points sit at 3.7–4.7 dB inside their flagged
  allowance.  The not-locked guard caught it; the wrong pins were removed
  with the reason recorded in place.
- **The fabricated-gap construction was reachable from every GUI** (found
  on a phone the day the campaign merged: fref 52→104 MHz on the spll_frac
  workbench, fout/frac untouched, "jitter" 1.6 ns).  `guiutil.apply_overrides`
  edited configs with `setattr`, which never re-runs `__post_init__` — so the
  construction-time refusal SPLL/SSPLL already had was bypassed, and
  CPPLL/ADPLL had no such refusal at all.  Since 2026-08-27: apply_overrides
  re-validates (children first) after every edit, all four fractional configs
  refuse a fout/fref/frac mismatch with the numbers and the corrective action
  in the message, and the bridge hands that refusal to the page in-band.
  Later the same day the fix moved a level up, on the user's call: frac.frac
  is *derived* from (fref, fout) on every GUI edit and no longer offered as
  an input, so the contradiction cannot be typed at all — the refusal stays
  as the backstop for hand-built configs.  Deliberate frac-vs-plan mismatch
  experiments now require the library, which is where they belong.
- **A legal fout is not a reachable fout** (2026-09-04).  ILCM/MDLL accept
  any integer multiple, but their digital tuning ranges are finite: fout×2
  railed the ring and the run read as an ordinary result 2.4 GHz off, with
  no lock detector to say otherwise.  `postprocess` now checks the tail
  frequency error against `f0` with the same `never_locked` predicate the
  comparator's refusal uses (fref/1000 over the last 5000 cycles) and notes
  it.  Analog loops with unbounded tuning laws (no v_min/v_max set) still
  follow fout anywhere — physically optimistic, numerically self-consistent,
  a modelling-range statement rather than a defect.
  - *Correction, 2026-09-09:* it is now a **stated** modelling-range
    boundary, `tuning-swing` in the registry.  analyze() notes when fout
    needs more than ±1.5 V (`TUNING_SWING_V`) of travel from f0 with no
    range set, or lies outside a set range (the varactor rails); simulate()
    reads the same from the run's own control-voltage tail (which rail, or
    "parked at +4 V").  The health-check plan's first idea — give the
    presets v_min/v_max — was **rejected after measuring** the operating
    points: every stock loop sits 0.6–1.0 V from f0 and the GUIs' default
    −100 MHz hop travels 1.67 V on a 60 MHz/V oscillator, so any physical
    range turns the hop page into a rail demonstration.  The coarse band
    bank is the physical answer to that hop, and it is a separate feature;
    the presets stay unbounded and say so when it matters.
- **MASH-2 for the SSPLL/SPLL, evaluated and deferred (2026-09-09, P2-16).**
  Measured with the modulators themselves (200k steps, three fractions):
  a MASH-1 residue spans exactly 1 UI (rms 0.29 UI), MASH-2 spans 2 UI
  (±1, rms 0.41), MASH-3 spans 4 UI (±2, rms 0.71) — not the "4–8 UI" the
  refusal message used to claim; the message now carries the measured
  numbers.  The shipped SSPLL/SPLL DTCs cover 1.02–1.60 UI (Wu'19 sits at
  1.02), so MASH-2 saturates every one of them; supporting it means a DTC
  of ≥ 2 UI (one more bit at the same LSB, or a coarser LSB with the
  quantization penalty that implies) *and* a bipolar target mapping in both
  engines (today's `(1 + r)/fout − range/2` assumes r ∈ [−1, 0]).  The
  benefit is a residue with 2nd-order shaping instead of the MASH-1 tones
  the `dsm-tonal` register pins (4.4–9.3 dB); the cost is the DTC range and
  its INL over twice the span.  Not implemented: no benchmark preset needs
  it (Markulić and Wu are both MASH-1 designs), and doing it without a
  paper to anchor the DTC assumptions would be a model change nothing
  measures.
- **`lock_time_s is None` does not mean unlocked.**  The detector thresholds
  are tuned for the design point; off-plan loops converge in fact while it
  stays silent.  NotLockedError requires None *and* tail frequency error
  > fref/1000.  ILCM/MDLL are exempt (no detector).
- **`n_crossings` counted alias images** until 2026-08-27: stock SSPLL
  reported 15, ADPLL 6, all crossings above fref/2 where a sampled response
  is periodic.  `loop_metrics(gol, f_limit=fref/2)` now; the
  conditional-stability boundary is only meaningful since this fix.
- **flicker-floor cannot fire in practice** below ~1.6M-cycle records: the
  3×RBW clip always sits above max(fref/n, fref/65536) until then.  Kept in
  the registry for long GUI runs; exempted, with this reason, from the
  sweep's boundary-coverage test.
- **The jitter headline pair was apples-to-oranges** whenever int_band
  reached past 0.45·fref (sim clipped, model full-band; 8.64 vs 100 MHz at
  fref=19.2M).  postprocess now emits a note; compare_domains returns a
  same-band pair.  This mismatch is also how sspll_frac's −6.8 dB hid from
  the ±35% scalar jitter test for its whole life.

## Where the numbers live

Boundary table + pinned gaps: docs/roadmap.md (generated).  Per-preset
stock bounds: docs/index.html §8 (now includes MDLL and the sspll_frac
row).  Contract prose: CONTRIBUTING.md "cross-domain test" bullet.
