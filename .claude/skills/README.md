# Skills in this repository

| entry | what it is |
|---|---|
| `pllsim-android-build/` | **live skill.** How *this* repo's APK is built — both variants, the pinned toolchain, and `inspect_apk.py`. Loaded automatically when working here |
| `python-android-apk.zip` | **archive, not loaded.** The general version: packaging any Python library as a Chaquopy APK, with a working project skeleton and a cross-compiler |

## Why the general one is a zip

It is stored, not installed, on purpose. Its description covers Android/Python
packaging broadly, so as a live skill it would compete with
`pllsim-android-build/` for triggering every time anyone touched `android/`
here — and the specific one is the right answer inside this repo. A zip is
inert to the skill loader, which only walks directories containing a
`SKILL.md`.

To use it on another project:

```bash
unzip .claude/skills/python-android-apk.zip -d ~/.claude/skills/
```

It was distilled from the work in this repository, so the two overlap; the
general one restates the reasoning without pllsim's specifics and adds the
parts this repo never needed — choosing a Python version from your
dependencies, and the project skeleton itself.
