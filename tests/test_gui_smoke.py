"""GUI smoke: every page runs headless via streamlit AppTest (no browser).

Skipped automatically when streamlit is not installed (pip install
pllsim[gui]).  These verify the pages import, render and — for the
workbench — produce an analyze() result end-to-end.
"""
from pathlib import Path

import pytest

st = pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402

from pllsim.webgui import package_dir  # noqa: E402

GUI = package_dir()
PAGES = sorted(p.name for p in (GUI / "pages").glob("*.py"))


def _apptest(path: Path, timeout: float = 60) -> AppTest:
    at = AppTest.from_file(str(path), default_timeout=timeout)
    at.run()
    return at


def test_home_renders():
    at = _apptest(GUI / "Home.py")
    assert not at.exception
    assert "pllsim" in at.title[0].value


@pytest.mark.parametrize("page", PAGES)
def test_every_page_renders(page):
    at = _apptest(GUI / "pages" / page)
    assert not at.exception, f"{page}: {at.exception}"


def test_workbench_analyze_end_to_end():
    at = _apptest(GUI / "pages" / "1_Workbench.py", timeout=120)
    at.button[0].click().run()          # Run analyze
    assert not at.exception
    # jitter metric rendered with a number
    assert any("fs" in str(m.value) for m in at.metric)


def test_selector_end_to_end():
    at = _apptest(GUI / "pages" / "3_Selector.py", timeout=180)
    at.button[0].click().run()
    assert not at.exception
    assert at.dataframe                 # ranked table present
