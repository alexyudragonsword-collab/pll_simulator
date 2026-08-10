"""The numbers README and docs/index.html state, against the repository.

These have now drifted twice -- the README claimed 150 tests, then 204, while
the suite had grown well past both -- and a stale count in the one file a
reader opens first is worse than no count, because it is the number they will
quote.  Documentation that states a fact about the code is code, and this is
its test.

Counts that change on almost every commit (the test total) are checked against
a band rather than for equality: a hard equality would fail on every PR that
adds a test, which trains people to edit the number without reading it.  A
band still catches the drift that actually happened, which was 2x.
"""
import ast
import re
import subprocess
import sys
from pathlib import Path

import pytest
import tomllib

from pllsim import presets

ROOT = Path(__file__).resolve().parents[1]
README = (ROOT / "README.md").read_text()
INDEX = (ROOT / "docs" / "index.html").read_text()

_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
          "seven": 7, "eight": 8, "nine": 9, "ten": 10}


def _collected_test_count() -> int:
    """What `pytest --collect-only` reports, i.e. what a reader would see."""
    r = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/", "--collect-only", "-q"],
        capture_output=True, text=True, cwd=ROOT)
    assert r.returncode == 0, r.stdout[-2000:] + r.stderr[-2000:]
    n = sum(int(m.group(1))
            for m in re.finditer(r"^\S+\.py: (\d+)$", r.stdout, re.M))
    assert n > 0, "could not parse a collection summary:\n" + r.stdout[-2000:]
    return n


def test_readme_test_count_is_in_the_right_decade():
    m = re.search(r"pytest tests/\s+# (\d+) tests", README)
    assert m, "the README quickstart no longer states a test count"
    stated, actual = int(m.group(1)), _collected_test_count()
    assert 0.85 * actual <= stated <= 1.15 * actual, (
        f"README says {stated} tests, the suite collects {actual}")


# the docs quote two different preset counts on purpose: the whole set, and
# the subset whose loop the synthesizer can re-derive (ILCM and MDLL have no
# loop filter at all).  Each is pinned to its own source of truth.
_SUBSET = r"any of the (\d+) presets whose loop can be re-synthesized"


def test_stated_preset_count_matches_all_presets():
    from pllsim.synth import sweepable_presets
    total, subset = len(presets.ALL_PRESETS), len(sweepable_presets())
    for name, text in (("README", README), ("docs/index.html", INDEX)):
        for m in re.finditer(_SUBSET, text):
            assert int(m.group(1)) == subset, (
                f"{name} says {m.group(1)} presets are sweepable; "
                f"sweepable_presets() returns {subset}")
        spans = [m.span() for m in re.finditer(_SUBSET, text)]
        for m in re.finditer(r"(\d+) presets", text):
            if any(a <= m.start() < b for a, b in spans):
                continue
            assert int(m.group(1)) == total, (
                f"{name} says {m.group(1)} presets, ALL_PRESETS holds {total}")


def test_stated_architecture_count_matches_the_arch_package():
    """Spelled out in words in both files, which no grep for digits catches."""
    actual = len(list((ROOT / "src" / "pllsim" / "arch").glob("*.py"))) - 2
    for name, text in (("README", README), ("docs/index.html", INDEX)):
        got = {_WORDS[w] for w in re.findall(
            r"\b(" + "|".join(_WORDS) + r")\s+PLL architectures", text)}
        assert not (got - {actual}), \
            f"{name} claims {got} architectures; arch/ has {actual}"


def test_the_example_range_stops_where_the_examples_do():
    last = max(int(p.name[2:4]) for p in (ROOT / "examples").glob("ex*.py"))
    m = re.search(r"ex01\.\.ex(\d+)", README)
    assert m and int(m.group(1)) == last, \
        f"README says ex01..ex{m.group(1) if m else '?'}; the last is ex{last:02d}"


def _layout_block() -> str:
    m = re.search(r"## Repository layout\s*```(.*?)```", README, re.S)
    assert m, "the README no longer has a repository-layout block"
    return m.group(1)


def test_the_layout_block_names_every_top_level_module():
    """A module nobody lists is a module nobody finds.

    corners.py, lockdetect.py and tdcspurs.py all shipped without ever
    reaching this block, and blocks/divider stayed in it for two releases
    after being deleted.
    """
    block = _layout_block()
    pkg = ROOT / "src" / "pllsim"
    missing = [p.name for p in sorted(pkg.glob("*.py"))
               if p.name != "__init__.py" and p.name not in block]
    missing += [p.name + "/" for p in sorted(pkg.iterdir())
                if p.is_dir() and not p.name.startswith("_")
                and p.name + "/" not in block]
    assert not missing, f"not listed in the README layout block: {missing}"


@pytest.mark.parametrize("pkg", ["core", "blocks", "calibration", "arch"])
def test_the_layout_block_lists_each_package_accurately(pkg):
    """Both directions: nothing missing, and nothing that no longer exists."""
    lines = _layout_block().splitlines()
    i = next((k for k, ln in enumerate(lines)
              if ln.strip().startswith(pkg + "/")), None)
    assert i is not None, f"{pkg}/ is not in the layout block"
    # a long package wraps; a continuation line is one that does not open a
    # new entry, and reading only the first physical line would let anything
    # past the wrap go unchecked
    entry = [lines[i].split(pkg + "/", 1)[1]]
    for ln in lines[i + 1:]:
        if not ln.strip() or re.match(r"\s*\S+(/|\.py)", ln):
            break
        entry.append(ln)
    listed = set(re.findall(r"[a-z_][a-z_0-9]*", " ".join(entry)))
    real = {p.stem for p in (ROOT / "src" / "pllsim" / pkg).glob("*.py")
            if p.name != "__init__.py"}
    assert not (real - listed), f"{pkg}/: not listed: {sorted(real - listed)}"
    stale = {n for n in listed - real
             if (ROOT / "src" / "pllsim" / pkg).exists()}
    assert not stale, f"{pkg}/: listed but gone: {sorted(stale)}"


def test_the_package_docstring_names_every_architecture():
    import pllsim
    doc = pllsim.__doc__
    for cls in ("CPPLL", "SSPLL", "SPLL", "ADPLL", "ILCM", "MDLL"):
        assert cls in doc, f"{cls} is missing from the pllsim docstring"


def test_the_version_the_package_reports_is_the_one_pyproject_declares():
    """A stale editable install reports the version of whenever you installed.

    That is not a code bug, but it is a real trap: every number a run stamps
    into a report carries it.  The fix is `pip install -e .` again, and this
    test is how you find out you need to.
    """
    import pllsim
    want = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"]
    assert pllsim.__version__ == want, (
        f"pllsim.__version__ is {pllsim.__version__} but pyproject declares "
        f"{want} -- reinstall the package (pip install -e .)")


def test_no_public_module_is_unreachable_from_the_package():
    """`import pllsim; pllsim.corners` used to raise while pllsim.presets worked.

    Nothing signals which of two sibling modules needs its own import, so a
    submodule that the docs name has to be reachable from the package.
    """
    import pllsim
    named = {m.group(1) for m in re.finditer(r"`pllsim\.([a-z_]+)`", README)}
    named |= {m.group(1) for m in re.finditer(r"pllsim\.([a-z_]+)", INDEX)}
    real = {p.stem for p in (ROOT / "src" / "pllsim").glob("*.py")
            if p.name != "__init__.py"}
    for mod in sorted(named & real):
        assert hasattr(pllsim, mod), \
            f"the docs reference pllsim.{mod}, which the package does not expose"


def test_ast_and_collection_agree_that_the_suite_is_not_shrinking():
    """A guard on the guard: if collection ever silently returns a partial
    count, the band test above would pass against a wrong actual."""
    defs = 0
    for f in sorted((ROOT / "tests").glob("test_*.py")):
        tree = ast.parse(f.read_text())
        defs += sum(1 for n in ast.walk(tree)
                    if isinstance(n, ast.FunctionDef) and n.name.startswith("test_"))
    assert _collected_test_count() >= defs, \
        "collection found fewer tests than there are test functions"
