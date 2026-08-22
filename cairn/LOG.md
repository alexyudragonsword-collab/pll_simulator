# Project Cairn Log

This file records substantive progress in reverse-chronological order — newest entry at the top, right below this line. Keep each entry short — summary and pointer only; conclusions settle into `cairn/<topic>.md`.

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
