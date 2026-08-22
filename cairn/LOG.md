# Project Cairn Log

This file records substantive progress in reverse-chronological order — newest entry at the top, right below this line. Keep each entry short — summary and pointer only; conclusions settle into `cairn/<topic>.md`.

## 2026-08-22 · mypy gate closed: files = ["src/pllsim"], 85/85, 0 errors

- export/ (24 errors) fixed at the *source*: FracConfig.dtc and
  SSPLL/SPLL.frac were annotated `"object | None"` since their creation —
  the type information died there, and every consumer error was fallout.
  Real types + a `_need()` narrowing helper in rnm_golden (restating what
  arch `__post_init__` validation already guarantees). `_DsmBase` gained the
  `step` contract its three subclasses always had.
- webgui/ (15) fixed: `HopResult.sim` object→`SimResult | None`;
  session_state round-trips annotated; arch-specific simulate kwargs go
  through a typed dict; 5_Fit's guard checked only one of two arrays.
- The files list collapsed to `["src/pllsim"]` — nothing is outside, so the
  roadmap's exclusion table is empty and gen_roadmap says so explicitly.
- Measurement trap logged: `cmd | tail; echo $?` reports tail's exit, not
  the command's — several earlier "exit=0" full-suite reads were unverified.
  pipefail from now on.

## 2026-08-22 · Android app v2: Spurs and Hop tabs

- appbridge grew 7 methods (spur_predict/spur_spectrum/spur_sweep/ref_spur,
  hop_check/hop/hop_stats); 6 new tests, each mutation-proven able to fail —
  including one whose first assertion over-specified the physics (in-band
  channels are a |NTF|~1 plateau, not a strict maximum at the smallest beat)
  and one that couldn't catch a dropped µs conversion until bounded both ways.
- Found en route: webgui Spurs page's "k max" input was read and passed to
  nothing for four releases — the decorative-parameter bug in the GUI layer.
  Removed.
- Both tabs driven end to end in Chromium against the real bridge.

## 2026-08-22 · Android app builds green; APK artifact produced

- `android.yml` run 2 on `7c7c5a6`: success in 2m45s after the sdist fix
  (run 1 died in Gradle 8 task validation — `install("../..")` trap, see
  `cairn/android-app.md`). Artifact `pllsim-debug-apk`, 84 MB, arm64+x86_64.
- Chaquopy resolved numpy/scipy/matplotlib for Python 3.10 from its own
  repo with pllsim's floors (`numpy>=1.24, scipy>=1.8, matplotlib>=3.7`) —
  the open question about its matplotlib version resolved itself green.
- Still unverified: touch on a physical phone (needs a sideload).
- Shipped as one PR (#36, two commits) rather than the planned two.

## 2026-08-18 · appbridge: JSON layer for the Android app (PR-1 of 2)

- `src/pllsim/appbridge.py` + tests: str→str JSON RPC over the existing
  `guiutil` machinery, in-package so pytest reaches it. 5 mutations each
  turned a test red before the suite was trusted.
- Found and fixed en route: `np.trapezoid` (numpy≥2-only) made the declared
  `numpy>=1.24` floor a lie; floors now measured — full suite green on
  Python 3.10 + numpy 1.24.4 + scipy 1.8.1, so `scipy>=1.8`.
- `GROUP_LABELS` moved webgui→guiutil (third consumer appeared).
- Conclusions to settle in `cairn/android-app.md` with PR-2.

## 2026-08-18 · Project Cairn initialized

- Initialized Project Cairn structure: `AGENTS.md`, `CLAUDE.md` (now the
  one-line `@AGENTS.md` stub), `.cairn/config.yaml`, `cairn/LOG.md`.
- Config: `git_policy: track`, `language: en`, graduation provider deferred
  (`none`), `migration_mode: start_fresh`.
- Retrofit, not greenfield: the 95 lines of always-read rules that were in
  `CLAUDE.md` (verify-do-not-infer, the generated-file table, the release
  mechanism, the two physics conventions) moved verbatim into `AGENTS.md`
  below the Cairn sections. Nothing was dropped — the pre-Cairn file is
  recoverable at `git show HEAD:CLAUDE.md`.
- No `cairn/ROADMAP.md` was created. `docs/roadmap.md` already fills that role
  and is *generated* (`docs/gen_roadmap.py`) so its numbers are measured; a
  second hand-written roadmap is the drift that file exists to prevent. See
  `AGENTS.md` → Reading order, step 4.
- `.gitignore` untouched: `track` writes no ignore rule, and no existing rule
  covered `cairn/`.
- Details: `AGENTS.md` and `.cairn/config.yaml`.
