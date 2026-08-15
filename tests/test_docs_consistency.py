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
import json
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


# ------------------------------------------------- the config reference
def test_the_config_reference_is_regenerated():
    """A generated file checked in is a file that drifts unless something
    compares it.  Regenerate into a temp location and diff."""
    gen = ROOT / "docs" / "gen_config_reference.py"
    out = ROOT / "docs" / "config-reference.md"
    assert out.exists(), "run docs/gen_config_reference.py"
    before = out.read_text()
    r = subprocess.run([sys.executable, str(gen)], capture_output=True,
                       text=True, cwd=ROOT)
    assert r.returncode == 0, r.stdout + r.stderr
    after = out.read_text()
    if before != after:
        out.write_text(before)          # leave the tree as we found it
        raise AssertionError(
            "docs/config-reference.md is stale -- run "
            "python docs/gen_config_reference.py")


def test_the_roadmap_is_regenerated():
    """The gap register has to describe today's code, or it is a wish list.

    It quotes how many type errors stand between each excluded package and the
    gate; those move whenever the code does, and a stale count would make the
    remaining work look larger or smaller than it is.
    """
    gen = ROOT / "docs" / "gen_roadmap.py"
    out = ROOT / "docs" / "roadmap.md"
    assert out.exists(), "run docs/gen_roadmap.py"
    before = out.read_text()
    r = subprocess.run([sys.executable, str(gen)], capture_output=True,
                       text=True, cwd=ROOT)
    assert r.returncode == 0, r.stdout + r.stderr
    if before != out.read_text():
        out.write_text(before)
        raise AssertionError("docs/roadmap.md is stale -- run "
                             "python docs/gen_roadmap.py")


def test_the_roadmap_names_only_packages_that_are_really_excluded():
    """An entry for a package already in the gate is finished work presented
    as outstanding, which is the way this kind of page usually goes wrong."""
    import tomllib as _t
    gated = set(_t.loads((ROOT / "pyproject.toml").read_text())
                ["tool"]["mypy"]["files"])
    text = (ROOT / "docs" / "roadmap.md").read_text()
    for path in sorted(gated):
        assert f"`{path}` |" not in text, \
            f"roadmap lists {path} as excluded, but it is in the mypy gate"


def test_every_editable_field_has_a_unit_and_a_label():
    """A form box labelled with its raw field name tells a user nothing.

    22 fields were in that state -- the impairment knobs added over several
    releases, each of which reached the forms without reaching the table that
    labels them.
    """
    from pllsim.guiutil import FIELD_INFO, enumerate_fields
    missing = set()
    for name, factory in presets.ALL_PRESETS.items():
        for s in enumerate_fields(factory().cfg):
            leaf = s.path.split(".")[-1]
            if leaf not in FIELD_INFO:
                missing.add(f"{name}:{s.path}")
    assert not missing, \
        f"no FIELD_INFO entry (raw name shown in both GUIs): {sorted(missing)}"


# ------------------------------------------------------- the release notes
def _tags() -> list[str]:
    """Version tags, or a skip when the checkout simply has none.

    A tagless checkout is a legitimate environment -- `actions/checkout`
    fetches no tags unless asked, and `git clone --no-tags` is a thing -- and
    an empty `git tag` exits 0, so a return-code check is not enough.
    Asserting against nothing there tests the checkout, not the repository.

    The cost is that these checks skip wherever tags are absent, so CI fetches
    them (`fetch-depth: 0`); shortening that back means losing this coverage
    silently.
    """
    r = subprocess.run(["git", "tag"], capture_output=True, text=True, cwd=ROOT)
    tags = sorted(t for t in r.stdout.split() if t.startswith("v")) \
        if r.returncode == 0 else []
    if not tags:
        pytest.skip("no version tags in this checkout (shallow or --no-tags)")
    return tags


def test_every_release_has_notes():
    """One file per tag, no exceptions.

    The notes are where "which number changed and why" is recorded, so a
    release without them is a release whose baseline moved silently.  v0.9.1
    and v0.9.2 both shipped before this test existed and both were missing:
    the work had been written up in docs/index.html and the PR body, neither
    of which is where someone diffing two versions goes looking.
    """
    tags = _tags()
    have = {p.stem for p in (ROOT / "docs" / "release-notes").glob("v*.md")}
    missing = [t for t in tags if t not in have]
    assert not missing, f"no release notes for: {missing}"


def test_the_version_being_shipped_has_notes():
    """The check that would have caught v0.9.1 and v0.9.2 never shipping.

    ci.yml's auto-release job walks docs/release-notes/v*.md and tags whatever
    has no tag yet -- so a release-notes file is not documentation *about* a
    release, it is what *causes* one.  Both versions bumped pyproject without
    one, the job found nothing to do, and a no-op is a legitimate success: two
    releases went green while shipping nothing.
    """
    import pllsim
    want = ROOT / "docs" / "release-notes" / f"v{pllsim.__version__}.md"
    assert want.exists(), (
        f"{want.name} is missing, so auto-release will not tag "
        f"v{pllsim.__version__} -- it walks that directory, not pyproject")


def test_an_untagged_release_says_why_in_its_own_notes():
    """A notes file with no tag would make auto-release retry forever.

    It walks the directory on every push, so a version it can never tag is a
    permanently red job rather than a one-off.  v0.9.1 is exactly that: CI
    cannot create a tag pointing at its commit, because a ref whose
    .github/workflows/ci.yml differs from the current one is refused to
    GITHUB_TOKEN by git push and by the refs API alike.  The file carries a
    `<!-- no-tag: ... -->` marker saying so, and the job skips it.
    """
    import pllsim
    tags = set(_tags())
    for p in sorted((ROOT / "docs" / "release-notes").glob("v*.md")):
        if p.stem in tags or p.stem == "v" + pllsim.__version__:
            continue
        assert "<!-- no-tag:" in p.read_text(), (
            f"{p.name} has no tag and is not the version being shipped, so "
            "auto-release will retry it on every push -- either it is the "
            "current version, or it needs a no-tag marker explaining why not")


def test_no_notes_for_a_version_that_was_never_bumped_to():
    """A file ahead of pyproject would tag a version the code is not at."""
    import pllsim
    cur = tuple(int(x) for x in pllsim.__version__.split("."))
    ahead = []
    for p in (ROOT / "docs" / "release-notes").glob("v*.md"):
        try:
            v = tuple(int(x) for x in p.stem[1:].split("."))
        except ValueError:
            ahead.append(p.stem)
            continue
        if v > cur:
            ahead.append(p.stem)
    assert not ahead, f"release notes ahead of pyproject {cur}: {sorted(ahead)}"


def test_the_notes_name_their_own_version():
    """A file copied from the previous release and half-edited is the failure
    mode here, and it always shows up in the first line."""
    for p in sorted((ROOT / "docs" / "release-notes").glob("v*.md")):
        first = p.read_text().splitlines()[0]
        assert p.stem in first, \
            f"{p.name} opens with {first!r}, which does not name {p.stem}"


# ------------------------------------------------------------- the deck
# The management deck is a binary, so nothing in it can be diffed and every
# number in it was once typed by hand -- which is how the v0.9.0 deck came to
# claim 405 tests and 20 examples one release after both had moved.  The
# numbers now come from collect_facts.py; these check that the shipped .pptx
# was actually rebuilt from a current facts.json, since a generator nobody
# runs is not better than a hardcoded number.
DECKS = sorted((ROOT / "docs" / "reports").glob("*.pptx"))


def _facts() -> dict:
    p = ROOT / "docs" / "reports" / "facts.json"
    if not p.exists():
        pytest.skip("facts.json absent -- run docs/reports/collect_facts.py")
    return json.loads(p.read_text())


def test_exactly_one_deck_ships():
    """Two decks means one of them is the stale one somebody will send."""
    assert len(DECKS) == 1, f"expected one .pptx in docs/reports, found {DECKS}"


def test_the_deck_facts_are_current():
    f = _facts()
    import pllsim
    from pllsim.synth import sweepable_presets  # noqa: F401  (import parity)
    assert f["version"] == pllsim.__version__
    assert f["presets"] == len(presets.ALL_PRESETS)
    assert f["examples"] == len(list((ROOT / "examples").glob("ex*.py")))
    assert f["architectures"] == \
        len(list((ROOT / "src" / "pllsim" / "arch").glob("*.py"))) - 2
    actual = _collected_test_count()
    assert 0.85 * actual <= f["tests"] <= 1.15 * actual, (
        f"facts.json says {f['tests']} tests, the suite collects {actual} -- "
        "re-run docs/reports/collect_facts.py and rebuild the deck")


def test_the_shipped_deck_matches_those_facts():
    """The .pptx has to have been rebuilt, not just facts.json regenerated."""
    pptx = pytest.importorskip("pptx")
    f = _facts()
    prs = pptx.Presentation(str(DECKS[0]))
    blob = []
    for slide in prs.slides:
        for shape in slide.shapes:
            if shape.has_text_frame:
                blob.append(shape.text_frame.text)
            if shape.has_table:
                for row in shape.table.rows:
                    blob.append(" | ".join(c.text for c in row.cells))
    text = "\n".join(blob)
    assert f"v{f['version']}" in text, "the deck does not carry the current version"
    assert f"{f['tests']} 项自动化测试" in text
    assert f"{f['examples']} 个可运行示例" in text
    assert f"{f['presets']} 个预设配置" in text
    # and the filename says which release it is, so a stale one is self-labelling
    assert f["version"] in DECKS[0].name, \
        f"{DECKS[0].name} does not name version {f['version']}"


def test_the_deck_benchmark_table_is_the_live_one():
    """The deck's README promised these came from benchmark_table().  They
    did not -- they were five hardcoded rows that happened to still be right."""
    f = _facts()
    live = presets.benchmark_table()
    assert len(f["benchmarks"]) == len(live)
    for got, want in zip(f["benchmarks"], live):
        assert got["paper"] == want["paper"]
        assert got["linear [fs]"] == pytest.approx(want["linear [fs]"], abs=0.1)


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
