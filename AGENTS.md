# pllsim Collaboration Rules

> This project uses Project Cairn to organize project knowledge: `AGENTS.md` is
> the rules-and-navigation entry point, `cairn/` is the project knowledge/state
> layer.  The `CLAUDE.md` in the same directory contains only one line,
> `@AGENTS.md`, so Claude Code reads the same rules; Codex reads this file
> directly.

## Project one-liner

A behavioural / system-level PLL simulator: six architectures, each carrying a
linear phase-noise model and a time-domain engine that are required to agree.

## Init configuration

- Graduation provider(s): none yet (deferred — connect a knowledge base at first graduation)
- Knowledge base index: not configured yet
- Graduation target: not configured yet

## Reading order after entering the project

1. Read this file (AGENTS.md) first.
2. Read `cairn/LOG.md` from the top (newest first) for recent progress and key
   decisions.
3. Read the relevant `cairn/` topic notes as needed for the task at hand.
4. There is deliberately **no `cairn/ROADMAP.md`**.  This project's register of
   known gaps is `docs/roadmap.md`, which is *generated* (`python
   docs/gen_roadmap.py`) so its numbers are measured rather than remembered,
   and pinned by `tests/test_docs_consistency.py`.  A second hand-written
   roadmap would be the exact drift both of those exist to prevent.

## Document responsibilities

| File | Role | Maintenance |
|---|---|---|
| `AGENTS.md` (root) | Rules and navigation | Rarely changes |
| `CLAUDE.md` (root) | One-line `@AGENTS.md` stub | Written once, never touched again |
| `cairn/LOG.md` | Chronological log | New entry at the top (newest first), each ≤ 20 lines, summary + pointer only |
| `cairn/<topic>.md` | Knowledge topic note (current truth) | Updated in place; pitfalls go in a body section, tagged via `contains`; revisions get a LOG pointer |
| `cairn/Reference/` | External raw input | Created as needed; append-only |
| `cairn/Cited.md` | Knowledge base citation list | Pointers only, never copies of the source |
| `docs/roadmap.md` | Measured gap register | **Generated** — never hand-edited (see below) |

> Everything else is created only when a concrete signal calls for it (a
> decision needs recording, a pitfall gets solved, a goal outlasts one session)
> — not pre-built as empty shells.  Engineering assets (contracts, config,
> specs consumed by code or process) are not managed by this system; they stay
> in the code tree, not in `cairn/`.

## Conflict arbitration rules

- Priority: **topic notes > LOG history**; rule-level conflicts are resolved by
  this file.
- Physics and design conclusions follow the latest record in the `cairn/` topic
  notes, not older LOG entries.
- Where a `cairn/` note and a *measured* artefact (a test, a generated doc, a
  run) disagree, the measurement wins and the note is wrong.  Say so in the
  note rather than averaging them.

## Knowledge base consumption reflex

- Before work whose reusable kernel — any conclusion it produces or depends on
  — would be graduation-worthy, consult this project's own `cairn/` topic
  notes; no external knowledge base is connected yet (provider deferred — see
  Init configuration above), so the external index check and `cairn/Cited.md`
  citations activate once one is connected.

## Document collaboration rules

- Before making a change, judge whether the user wants "discuss/suggest" or
  "just edit the doc directly"; when they say "take a look first / evaluate
  first," give analysis first — don't rewrite a formal doc outright.
- When correcting a past judgment, append a correction note; don't silently
  overwrite it.
- Don't write an unconfirmed judgment as a settled fact.

## Knowledge distillation rules

- After every substantive step forward, add one entry to the top of
  `cairn/LOG.md` (summary + pointer); let conclusions settle into the `cairn/`
  topic notes.
- **Completion reply gate:** before any completion claim — including but not
  limited to work being complete or implemented, finalized, updated,
  synchronized, verified or tests passing; a problem being fixed or resolved; a
  deliverable being ready to use; a statement that work has ended; and
  semantically equivalent wording — run the Cairn checkpoint in the skill's
  `references/maintenance.md`; update only the records its trigger matrix
  requires, verify them, then reply.  An explicit read-only / no-edit request
  forbids Cairn writes.
- Cross-project reusable experience gets distilled via the graduation mechanism
  once a knowledge base is connected (provider deferred — see Init
  configuration above).

---

The rest of this file is the project's own operating rules — what you would
otherwise learn by breaking it.  [`CONTRIBUTING.md`](CONTRIBUTING.md) is the
real contributor guide and is not repeated here; this is the part specific to
working on this repository without a human watching each step.

## Verify, do not infer

This codebase has a history of parameters that read correctly and did nothing,
and of tests that passed against nothing.  Every one was found by *running*
something, not by reading:

- A corner axis that named a supply voltage no equation touched — found by
  sweeping it 0.5 → 2.0 and watching the jitter stay at 258.3043 fs.
- A spur predictor 4.3 dB off — found by comparing it to the time domain,
  which nothing had done.
- A cross-reference check whose regex matched **zero** instances, so every
  assertion in it passed on nothing.
- A GUI test that pressed buttons by index and kept passing after a button was
  inserted ahead of it.

So: after writing a check, break the thing it checks and confirm it goes red.
After claiming a parameter works, drive it and show the number moving.  State
what you measured, not what you expect.

## Commands

```bash
pytest tests/ -q                    # ~18 min.  Use -k <name> while iterating.
ruff check src tests examples packaging
mypy                                # file list in pyproject.toml
QT_QPA_PLATFORM=offscreen pytest tests/test_guiqt_smoke.py -q
```

The full suite is long enough that it is tempting to report before it
finishes.  Do not: say it is still running, or wait.

## Three front ends, one contract — verify all of them

`webgui/` (Streamlit), `guiqt/` (PySide6) and `android/` (WebView over
`appbridge`) render the same library.  A change to anything they share —
`guiutil`, `presets`, `plotting`, an `arch/` signature, a config field —
reaches all three, and **a change is not done until all three are checked**.
Checking means running them, not reasoning that they should be fine: every
drift this project has had was invisible from the source.

| surface | how to actually verify it |
|---|---|
| web | `QT_QPA_PLATFORM=offscreen pytest tests/test_gui_smoke.py tests/test_gui_compute.py -q` — Streamlit `AppTest` execs each page |
| Qt | `QT_QPA_PLATFORM=offscreen pytest tests/test_guiqt_smoke.py -q`, then **read the count**: these tests *skip* without PySide6 and the system GL libs (`libegl1 libgl1 libxkbcommon0 libdbus-1-3`) instead of failing, and that silence is how the two GUIs drifted for several releases |
| Android bridge | `pytest tests/test_appbridge.py -q` — pure Python, no SDK needed |
| Android page | `python tests/android_page_harness.py` — starts its own shim for `window.host` and drives every tab in real Chromium against the real bridge, including the plot viewer's pinch (real multi-touch, through CDP).  Needs `pip install playwright`; not in CI.  The overlay that swallowed every tap, and the ADPLL crash in the measured spectrum, were both found this way and by nothing else |
| Android build | Actions → *Android APK* → Run workflow, or locally `gradle -p android :app:assembleDebug`.  Manual only; it does not run on push.  Every run makes **two** APKs — interpreted (.py from an sdist) and compiled (`core`/`arch`/`blocks`/`calibration` as `.so`, from wheels `packaging/android_wheel.py` cross-compiles).  The workflow looks *inside* both rather than trusting the build log: one must carry source and the other objects, because the two builds share a workspace and a reused pip output would silently ship the same APK twice |

Two rules that follow from the same lesson:

- **A new bridge method is half a feature.** `appbridge._METHODS` gaining an
  entry that no page calls looks tested and does nothing — `bank` sat that
  way.  Wire the render in the same change; `tests/test_android_parity.py`
  now fails if you do not, and it costs no browser.
- **Parity is a property to re-check, not to assume.** When the surfaces
  legitimately differ (phone defaults, unit choices, the phone's navigation),
  record it in `cairn/android-app.md` under Parity so the next reader can tell
  a decision from a gap.
- **The phone navigates by a left drawer**, not by the page list either
  desktop GUI uses.  A horizontal bar coexisted with it for one release so the
  two could be compared on a device; the comparison settled on the drawer and
  the bar was deleted the same day, along with the `?nav=` switch and the
  Gradle flavors.  Keeping a shell nobody chose is how the two desktop GUIs
  drifted.

## Do not hand-edit these

They are generated, and `tests/test_docs_consistency.py` fails when they go
stale:

| file | regenerate with |
|---|---|
| `docs/config-reference.md` | `python docs/gen_config_reference.py` |
| `docs/roadmap.md` | `python docs/gen_roadmap.py` |
| `docs/reports/facts.json` + the `.pptx` | `python docs/reports/collect_facts.py` then `cd docs/reports && node build_deck.js` |
| `examples/out/**` | run the example that writes it |

A new config field also needs an entry in `guiutil.FIELD_INFO`, which is where
its unit and bilingual label come from for the reference *and* both GUI forms.

## Numbers in prose are code

`README.md` and `docs/index.html` state counts — architectures, presets,
examples, tests — that are checked against the package.  They have drifted
twice before the test existed.  If you add a preset, an example or an
architecture, that test tells you which sentences to update; do not edit the
number without re-reading the sentence around it.

Be careful with blanket search-and-replace on those files: a regex that
resynced the test count also rewrote two *historical* counts inside release
notes, turning "the README claimed 150 tests" into a false statement about the
past.

## Releasing

`docs/release-notes/vX.Y.Z.md` **causes** a release; it does not describe one.
The `auto-release` job walks that directory on pushes to `main`.  Write the
notes in the same change as the `pyproject` version bump — they cannot be
backfilled, because CI cannot tag an older commit at all (a ref whose
`.github/workflows/ci.yml` differs from the current one is refused to
`GITHUB_TOKEN` by `git push` and by the refs API alike).

Tags and releases can only be deleted by a human.  If a tag ends up on the
wrong commit, say so and ask — do not paper over it.

## Physics conventions that are easy to get wrong

Full list in `CONTRIBUTING.md`; these are the two that have actually caused
silent errors:

- Phase PSDs are **double-sideband** `S_φ` in rad²/Hz; plots and spot figures
  are `L(f) = S_φ/2` in dBc/Hz, and `ipn_dbc` sits 3.01 dB below the integral
  of `S_φ`.  Mixing them is a silent 3 dB — and a silent √2 in any jitter
  derived from it.  `core.jitter.convert_phase_noise` is the one place that
  turns degrees, jitter and integrated dBc into each other; it returns *both*
  dBc conventions precisely so a caller cannot pick the wrong one by
  accident.  All three GUIs expose it.
- A continuous current scaled by duty cycle and a per-cycle sampled charge
  injection differ by exactly **2**.  Say which convention a new noise source
  is in.

When the linear model and the time domain disagree, one of them is wrong.
Finding out which is the work; averaging them is not.
