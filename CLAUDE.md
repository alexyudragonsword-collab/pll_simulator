# Notes for AI assistants

[`CONTRIBUTING.md`](CONTRIBUTING.md) is the real guide and is not repeated
here.  This file is the part that is specific to working on this repository
without a human watching each step.

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

The Qt tests **skip** without PySide6 and system GL libraries rather than
fail — that silence is how the two GUIs drifted apart for several releases.
If you touch `guiqt/`, confirm they actually ran.

The full suite is long enough that it is tempting to report before it
finishes.  Do not: say it is still running, or wait.

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
  of `S_φ`.  Mixing them is a silent 3 dB.
- A continuous current scaled by duty cycle and a per-cycle sampled charge
  injection differ by exactly **2**.  Say which convention a new noise source
  is in.

When the linear model and the time domain disagree, one of them is wrong.
Finding out which is the work; averaging them is not.
