# Contributing to pllsim

This file is the things you would otherwise learn by breaking them.  The
design rationale lives in [`docs/index.html`](docs/index.html); this is the
mechanics.

## Setup

```bash
pip install -e .[test,gui,guiqt]
pip install ruff mypy pytest-cov
pytest tests/                    # ~18 min; -x -k <name> while iterating
```

`QT_QPA_PLATFORM=offscreen` is needed for the desktop-GUI tests on a headless
box.  They *skip* without PySide6 and its system GL libraries rather than
fail, which is exactly how the two GUIs drifted apart for several releases —
if you touch `guiqt/`, make sure those tests are actually running for you.

## What CI enforces

| gate | command |
|---|---|
| lint | `ruff check src tests examples packaging` |
| types | `mypy` (file list in `pyproject.toml`) |
| tests | `pytest tests/` on 3.11 and 3.12 |
| coverage | floor of 88% (`[tool.coverage.report]`) |

The mypy gate is the whole package (`files = ["src/pllsim"]`) — every module
whose types carry a *convention* (rad²/Hz vs dBc/Hz, seconds vs UI, amps vs
coulombs), and everything else too, since `export/` and `webgui/` — the last
two paths outside — were fixed and gated together.  If something ever has to
leave the gate, it goes in `docs/gen_roadmap.py`'s `TYPE_CANDIDATES`, so its
cost is **measured** in [`docs/roadmap.md`](docs/roadmap.md) rather than
remembered here; silencing with `ignore_errors` is not an option, because a
blanket ignore reads as "type-checked".

## Conventions that will bite you

* **Phase PSDs are double-sideband** `S_φ(f)` in rad²/Hz.  Plots and spot
  numbers are `L(f) = S_φ/2` in dBc/Hz, and `ipn_dbc` sits 3.01 dB below the
  integral of `S_φ` for the same reason.  Mixing the two is a silent 3 dB and
  has happened more than once.
* **Two conventions for noise injection.**  `CurrentNoise(duty=...)` scales a
  continuous current by its duty cycle; a per-cycle *sampled* charge injection
  is `2σ²/fref`.  They differ by exactly 2.  The charge-pump path carries the
  factor deliberately (`duty = 2*t_reset/tref`); if you add a source, say
  which convention it is in.
* **Every dual-domain architecture has a cross-domain test.**  The settled
  time-domain periodogram must match the linear model within 2–3 dB
  band-averaged.  When they disagree, one of them is wrong — finding out which
  is where most of §9 of the design guide came from.
* **`analyze()` is not allowed to invent numbers.**  An impairment that is not
  configured is an absent key, not a `-600 dBc` entry; an architecture that
  genuinely has no such mechanism says so in `notes` rather than returning a
  blank.  A sub-sampling loop reports no reference spur *because it has none*,
  and that sentence is the deliverable.

## Testing

Two habits this codebase learned the hard way.

**Drive one source to dominance before comparing.**  A test that compares
*total* jitter with a 2–3 dB tolerance will pass with a single contributor 3 dB
wrong.  Raise the source under test to >90% of the budget, then compare.
Three real physics bugs survived for months behind total-comparison tests.

**Prove your test can fail.**  After writing a check, break the thing it
checks and confirm it goes red.  Vacuous tests here have included: a regex
matching zero instances (so every assertion passed on nothing), an assertion
whose `or` branch accepted anything, and a button test that pressed by index
and kept passing after a button was inserted ahead of it.  Where the check is
subtle, leave the mutation in the docstring so the next reader knows what it
is guarding.

**Numbers in prose are code.**  `tests/test_docs_consistency.py` pins the
counts in `README.md`, `docs/index.html` and the management deck against the
package.  If you add a preset, an example or an architecture, that test tells
you which sentences to update.

Two files there are generated, and the same test fails when they go stale:

```bash
python docs/gen_config_reference.py     # after adding or renaming a config field
python docs/gen_roadmap.py              # after changing the mypy gate
python docs/reports/collect_facts.py    # then: cd docs/reports && node build_deck.js
```

A new config field also needs an entry in `guiutil.FIELD_INFO` — that is where
its unit and bilingual label come from, for the reference *and* for both GUI
forms.  Without one the form shows the raw field name, which tells a user
nothing about what to type; the test rejects it.

## How to add …

**A preset** — write the factory in `src/pllsim/presets.py`, register it in
`ALL_PRESETS`, and give it a docstring saying where the numbers come from.
Both GUIs and the selector pick it up from that dict; nothing else needs
touching.  A literature-anchored preset also goes in `BENCHMARKS` with its
published figure, and `benchmark_table()` recomputes the linear column live.

**An example** — `examples/exNN_<slug>.py`, `matplotlib.use("Agg")` before
pyplot, figures into `examples/out/`.  The header docstring should say what
question the example answers, not what functions it calls.  CI runs every
example on merges to `main` and a fast subset on every push; if yours runs in
a few seconds, add it to the subset.

**An architecture** — subclass `arch.base.PLLBase` and implement `analyze()`
and `simulate()`.  The shared helpers in `base.py` (`supply_ripple_v`,
`pull_hz`, `attach_fine`, `start_offset_kwarg`) exist so that a config field
on the common `OscConfig` is not a decoration on five of six engines — wire
them up rather than reimplementing.  Then: a preset, a cross-domain test, and
the docs counts.

**An impairment** — model it in `blocks/`, expose it as a config field, give
it both an `analyze()` path and a `simulate()` path, and add a test that drives
that source to dominance across the two.  An impairment with only one of the
two paths is how a parameter becomes decorative.

## Releasing

`docs/release-notes/vX.Y.Z.md` is not documentation *about* a release — it is
what *causes* one.  The `auto-release` job in `ci.yml` walks that directory on
every push to `main` and tags plus releases anything without a tag.

So a release is: bump `version` in `pyproject.toml`, write the notes file with
the matching name, merge.  Skipping the notes file means the version bump
ships silently and no tag is ever created — which happened to v0.9.1 and
v0.9.2, because iterating over an unchanged directory is a legitimate success.
CI now fails on `main` when `pyproject`'s version has no notes file.

Write the notes **in the same change as the version bump**.  They cannot be
backfilled: tagging an older commit is impossible from CI, because a ref whose
`.github/workflows/ci.yml` differs from the current one is refused to
`GITHUB_TOKEN` by `git push` ("without workflows permission" — a PAT scope no
`permissions:` block can grant) and by the refs API alike.  A version that
already shipped without notes therefore stays untagged: it carries a
`<!-- no-tag: -->` marker explaining why, the job skips it, and its content
goes out with the next release.  `v0.9.1` is the example in the tree.

Write the notes for someone diffing two versions: **every number that changed,
and why**.  If jitter figures move, say which presets and by how much.  A
release that quietly re-baselines a number is worse than one that breaks.

## Pull requests

Say what you found and how you know, not what you touched — the diff already
says that.  If a fix changes a published number, the PR body carries the
before/after table.
