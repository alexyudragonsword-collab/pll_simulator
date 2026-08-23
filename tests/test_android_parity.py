"""The Android page and the bridge must not drift apart.

The browser harness beside this file is the real check, but it needs
Playwright and several minutes, so it runs by hand.  These are the parts
that can be checked from text alone, in every CI run, at no cost -- and they
are the parts that already went wrong: `appbridge` gained a `bank` method
that no page ever called, which looks tested (it has bridge tests) and does
nothing for the user.
"""
from pathlib import Path

import pytest

from pllsim import appbridge

WWW = Path(__file__).resolve().parents[1] / "android/app/src/main/assets/www"
APP_JS = WWW / "app.js"
INDEX = WWW / "index.html"


def test_every_bridge_method_is_called_by_the_page():
    """A bridge method with no caller is half a feature.

    Mutation: add a method to appbridge._METHODS and this goes red until the
    page calls it.  Deleting the `bank` call from app.js does the same.
    """
    js = APP_JS.read_text()
    unused = [m for m in appbridge._METHODS if f'"{m}"' not in js]
    assert not unused, (
        f"appbridge exposes {unused} that android/…/app.js never calls — "
        "wire the render in the same change, or drop the method")


def test_the_page_calls_nothing_the_bridge_does_not_expose():
    """The other direction: a typo'd method name fails only at runtime, in
    a WebView, where the user sees an error card and nobody sees a log."""
    import re
    js = APP_JS.read_text()
    called = set(re.findall(r'\bcall\(\s*"([a-z_]+)"', js))
    missing = sorted(called - set(appbridge._METHODS))
    assert not missing, f"app.js calls {missing}, which appbridge has no entry for"


@pytest.mark.parametrize("element_id", [
    "preset", "form", "analyze-out", "bank-out", "simulate-out",
    "sp-preset", "sp-mmeas-note", "sp-ref-note", "hop-fll", "sel-out",
    "mod-sps", "dr-rate", "bench-out",
])
def test_ids_app_js_drives_exist_in_the_page(element_id):
    """app.js addresses the DOM by id; a renamed id in index.html turns a
    live caption into silence, which is exactly how a warning goes missing.
    """
    assert f'id="{element_id}"' in INDEX.read_text(), \
        f"app.js drives #{element_id} but index.html no longer defines it"


def test_every_tab_button_has_a_panel():
    import re
    html = INDEX.read_text()
    tabs = set(re.findall(r'<button data-tab="([a-z]+)"', html))
    panels = set(re.findall(r'<div id="tab-([a-z]+)"', html))
    assert tabs == panels, f"tab buttons {tabs} vs panels {panels}"
    assert len(tabs) == 8, tabs
