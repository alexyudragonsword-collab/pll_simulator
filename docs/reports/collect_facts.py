"""Emit the numbers the deck quotes, straight from the library.

The deck is a binary.  Every count in it -- architectures, presets, examples,
tests, the version, the benchmark table -- was typed in by hand, and the
v0.9.0 deck went stale within one release: it still said 405 tests and 20
examples after the suite reached 437 and ex21 landed.  Its own README said a
binary with no source only goes quietly out of date, which is exactly what
happened to the numbers inside it.

So they are computed here and read by build_deck.js.  Nothing in the deck
states a fact about the code that this file did not measure.

    python collect_facts.py            # writes facts.json next to this file
"""
import ast
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))


def collected_tests() -> int:
    """What `pytest --collect-only` reports, i.e. what a reader would see.

    Falls back to counting test functions by AST if pytest cannot run here,
    which is a floor rather than a guess -- parametrized cases only ever make
    the real number larger, so the deck would understate rather than inflate.
    """
    try:
        r = subprocess.run(
            [sys.executable, "-m", "pytest", "tests/", "--collect-only", "-q"],
            capture_output=True, text=True, cwd=ROOT, timeout=1800)
        n = sum(int(m.group(1))
                for m in re.finditer(r"^\S+\.py: (\d+)$", r.stdout, re.M))
        if r.returncode == 0 and n:
            return n
    except Exception:
        pass
    n = 0
    for f in sorted((ROOT / "tests").glob("test_*.py")):
        tree = ast.parse(f.read_text())
        n += sum(1 for x in ast.walk(tree)
                 if isinstance(x, ast.FunctionDef) and x.name.startswith("test_"))
    return n


def release_count() -> int:
    """Tagged releases.  The deck cites this as evidence of release discipline,
    so it has to be the tag count and not a number someone remembers."""
    r = subprocess.run(["git", "tag"], capture_output=True, text=True, cwd=ROOT)
    return len([t for t in r.stdout.split() if t.startswith("v")])


def main() -> int:
    import pllsim
    from pllsim import presets

    facts = {
        "version": pllsim.__version__,
        "architectures": len(list((ROOT / "src" / "pllsim" / "arch").glob("*.py"))) - 2,
        "presets": len(presets.ALL_PRESETS),
        "examples": len(list((ROOT / "examples").glob("ex*.py"))),
        "tests": collected_tests(),
        "releases": release_count(),
        # the linear column is recomputed by benchmark_table() on every call;
        # the published and time-domain columns are the paper and the run
        "benchmarks": presets.benchmark_table(),
    }
    out = Path(__file__).with_name("facts.json")
    out.write_text(json.dumps(facts, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(facts, ensure_ascii=False, indent=2))
    print(f"\nwritten to {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
