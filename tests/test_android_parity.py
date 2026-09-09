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
    "lightbox-stage", "lightbox-overlay", "lightbox-readout",
    "lightbox-cursor", "lightbox-delta",
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
    # a count, not a set, so adding a tab is a decision someone makes on
    # purpose -- the drawer holds nine comfortably, a horizontal bar could
    # not hold eight, which is why the bar is gone.  11 since 2026-09-09:
    # Fit (pasted CSV) joined; MonteCarlo and Export stay out, see
    # cairn/android-app.md
    assert len(tabs) == 11, tabs


def test_the_drawer_has_its_slide_rule():
    """A shell with no styling renders as nothing.  The drawer is #drawer
    translated off-screen and slid back; that rule is the shell.

    Mutation: delete the transform from style.css and this goes red.  The
    horizontal-bar shell that used to sit beside it was removed once the two
    had been compared on a device -- see cairn/android-app.md.
    """
    css = (WWW / "style.css").read_text()
    assert "#drawer {" in css and "translateX(-100%)" in css, \
        "the drawer has no slide rule"
    assert "#drawer.open { transform: translateX(0); }" in css, \
        "the drawer never slides back in"
    # the code, not the prose: "?nav=" also appears in the comment recording
    # that the switch was removed, which is how this first failed
    js = APP_JS.read_text()
    for gone in ("URLSearchParams", "dataset.nav", 'dataset["nav"]'):
        assert gone not in js, \
            f"app.js still reads a navigation mode via {gone}"


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


def test_a_control_inside_the_viewer_keeps_its_own_taps():
    """setPointerCapture does not merely retarget pointer events -- it moves
    the click target to the capturing element too.  Capturing on #lightbox
    therefore swallowed the close button entirely: tapping the X did nothing
    at all for a release, and no test had ever tapped it.

    Mutation: delete the guard and this goes red; the browser harness catches
    the same thing by actually pressing the button.
    """
    js = APP_JS.read_text()
    import re
    body = re.search(r'lb\.addEventListener\("pointerdown".*?\n\}\);', js, re.S)
    assert body, "the viewer lost its pointerdown handler"
    guard = 'if (ev.target.closest("button")) return;'
    assert guard in body.group(0), \
        "the viewer captures taps meant for its own buttons"
    # the *call*, not the word: the first match was inside the comment that
    # explains the call, so this compared the guard against its own docstring
    assert body.group(0).index(guard) < body.group(0).index("lb.setPointerCapture("), \
        "the guard runs after the capture, which is too late"


def test_the_cursor_map_reaches_the_page_from_every_plot():
    """A plot rendered without its map is a plot whose cursor silently is not
    there.  Both halves have to be wired: the bridge spreads _plot() into the
    reply, and the page hands r.cursor to pngHtml.
    """
    import re
    js = APP_JS.read_text()
    # single-argument calls: those are the plots rendered with no map.  The
    # pie is the only legitimate one -- a wedge has no coordinate system.
    bare = re.findall(r"pngHtml\(([a-z_]+\.[a-z_]+)\)", js)
    assert bare == ["r.pie_png"], \
        f"these plots render without their cursor map: {bare}"
    # the module's own file, not path arithmetic from WWW: counting parents
    # got it wrong and pointed at android/src/, which does not exist
    text = Path(appbridge.__file__).read_text()
    assert '"png": _png(fig)' not in text, \
        "a bridge plot still ships the image without its cursor map"


def test_the_android_build_has_no_navigation_flavors_left():
    """Removing the bar means removing what selected it.  A leftover flavor
    would ship an APK whose page has no such mode, and `assembleDebug` would
    stop being a valid task name again.
    """
    gradle = (WWW.parents[3] / "build.gradle.kts").read_text()
    for gone in ("flavorDimensions", "productFlavors", "NAV_MODE",
                 "applicationIdSuffix"):
        assert gone not in gradle, f"{gone} outlived the shell it selected"
    # parents[1] is android/app/src/main -- parents[2] pointed a level up at
    # android/app/src, which has no java/ under it
    kt = (WWW.parents[1] / "java/com/pllsim/app/MainActivity.kt").read_text()
    assert "BuildConfig" not in kt and "?nav=" not in kt, \
        "MainActivity still passes a navigation mode to the page"


def test_the_form_renders_bool_fields_as_checkboxes():
    # the bridge now emits kind="bool" for divider_retimed / ftl / timing_cal;
    # a page that only knows text inputs would show "false" in a text box and
    # send back whatever was typed
    js = APP_JS.read_text(encoding="utf-8")
    assert 'f.kind === "bool"' in js
    assert 'type="checkbox"' in js and 'data-kind="bool"' in js
    # and the override collector reads the checkbox, not its .value
    assert 'inp.dataset.kind === "bool"' in js
