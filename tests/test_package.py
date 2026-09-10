"""The package's public surface: __all__ says what it means.

`validation` -- the comparator every cross-domain test runs on -- was not
in __all__ for its whole life; nothing checked.  Two properties, both
mutation-tested by editing the list: every name resolves, and every
top-level module has a name.
"""
import importlib
from pathlib import Path

import pytest

import pllsim

PKG = Path(pllsim.__file__).parent


def test_every_all_name_resolves():
    for name in pllsim.__all__:
        assert hasattr(pllsim, name), f"__all__ lists {name!r} but pllsim has no such attribute"


@pytest.mark.parametrize("mod", sorted(
    p.stem for p in PKG.glob("*.py") if not p.stem.startswith("_")))
def test_every_top_level_module_is_in_all(mod):
    assert mod in pllsim.__all__, f"pllsim.{mod} exists but __all__ does not name it"
    importlib.import_module(f"pllsim.{mod}")
