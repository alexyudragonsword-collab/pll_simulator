"""Optional test dependencies: skip locally, fail in CI.

A test module that `importorskip`s a GUI toolkit reports itself as *one*
skipped item, and dozens of tests vanish behind it.  That is how the two
desktop GUIs drifted for several releases, and how the 3.10 floor job first
passed while silently running 97 fewer tests than the 3.11 job.  With
PLLSIM_CI set (both CI test jobs set it) a missing optional dependency is a
failure, because CI installed it on purpose.
"""
from __future__ import annotations

import importlib
import os
import shutil
from types import ModuleType

import pytest

STRICT = bool(os.environ.get("PLLSIM_CI"))


def require_module(name: str, reason: str = "") -> ModuleType:
    """Import `name`; skip the calling module if it is missing, unless CI."""
    if STRICT:
        try:
            return importlib.import_module(name)
        except ImportError as e:
            pytest.fail(f"PLLSIM_CI is set but {name} is not importable: "
                        f"{e}. {reason}".strip(), pytrace=False)
    return pytest.importorskip(name, exc_type=ImportError,
                               reason=reason or f"{name} not installed")


def require_tool(name: str) -> str:
    """Path of executable `name`; skip the module if absent, unless CI."""
    path = shutil.which(name)
    if path is None:
        if STRICT:
            pytest.fail(f"PLLSIM_CI is set but `{name}` is not on PATH",
                        pytrace=False)
        pytest.skip(f"{name} not installed", allow_module_level=True)
    return path
