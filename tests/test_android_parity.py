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
    "drawer", "scrim", "menu-btn", "section-title",
    "lightbox", "lightbox-img", "lightbox-close",
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


def test_both_navigation_shells_are_wired():
    """The bar is kept only so it can be compared with the drawer, and a
    shell with no styling is a shell that renders as nothing.  Both modes
    must exist in the CSS and app.js must know how to pick one.

    Mutation: delete either `[data-nav="..."]` block from style.css, or the
    `?nav=` read from app.js, and this goes red.
    """
    css = (WWW / "style.css").read_text()
    # the load-bearing rule of each shell, not merely "the selector appears
    # somewhere": the bar is #tabs laid out as a row, the drawer is #drawer
    # translated off-screen.  Matching the selector alone passed while one
    # shell's layout rule was renamed away.
    assert '[data-nav="tabs"] #tabs { display: flex' in css, \
        "the bar shell has no layout rule"
    assert '[data-nav="drawer"] #drawer {' in css and \
        "translateX(-100%)" in css, "the drawer shell has no slide rule"
    js = APP_JS.read_text()
    assert '"nav"' in js and "documentElement.dataset.nav" in js, \
        "app.js no longer selects a shell from the ?nav= parameter"


def test_the_scrim_cannot_swallow_taps_while_hidden():
    """An author `display` beats the UA's [hidden]{display:none}: the busy
    overlay intercepted every tap that way, invisibly, and the drawer scrim
    is the same shape of element.  The rule has to be there in text; the
    harness checks it by hit-testing a real page.
    """
    css = (WWW / "style.css").read_text()
    assert "#scrim[hidden] { display: none; }" in css, \
        "the scrim has no explicit hidden rule -- see cairn/android-app.md"


def test_the_plot_viewer_cannot_swallow_taps_while_hidden():
    """Same failure mode as the scrim, one layer higher and far worse: the
    viewer is `display: flex` and covers the entire screen, so if the author
    rule ever beats `[hidden]` the app becomes an unresponsive black page.
    """
    css = (WWW / "style.css").read_text()
    assert "#lightbox { position: fixed" in css and "display: flex" in css, \
        "the viewer lost its layout rule"
    assert "#lightbox[hidden] { display: none; }" in css, \
        "the viewer has no explicit hidden rule -- see cairn/android-app.md"


def test_plots_are_bound_to_the_viewer_by_delegation():
    """Plots are injected into a dozen output containers by nine different
    render paths.  A per-render binding is one somebody forgets on the next
    tab -- which is the same shape as the bridge method with no caller.

    Mutation: narrow the listener to a single container and this goes red.
    """
    js = APP_JS.read_text()
    assert 'closest("img.plot")' in js, \
        "app.js no longer opens the viewer from a delegated plot click"
    assert 'document.addEventListener("click"' in js, \
        "the plot click is bound per-render rather than delegated"
    # not `"closeLightbox()" in js`: that string also lives in the close
    # button's handler, so the check passed with the back branch deleted.
    # The body of onAndroidBack is what has to contain it, and the viewer is
    # the topmost layer, so it must be consumed before the drawer.
    import re
    body = re.search(r"window\.onAndroidBack = function \(\) \{(.*?)\n\};",
                     js, re.S)
    assert body, "window.onAndroidBack is gone -- back would leave the app"
    body = body.group(1)
    assert "closeLightbox()" in body, \
        "back does not close the plot viewer; it would exit the app instead"
    assert body.index("closeLightbox()") < body.index("setDrawer(false)"), \
        "back closes the drawer before the viewer, but the viewer is on top"


def test_the_gradle_flavors_match_the_shells():
    """Build-time selection and page-time selection have to name the same
    two shells, or an APK ships a mode the page does not implement."""
    import re
    gradle = (WWW.parents[3] / "build.gradle.kts").read_text()
    flavors = set(re.findall(r'create\("([a-z]+)"\)', gradle))
    assert flavors == {"tabs", "drawer"}, flavors
    for mode in flavors:
        assert f'"{mode}"' in gradle, mode
