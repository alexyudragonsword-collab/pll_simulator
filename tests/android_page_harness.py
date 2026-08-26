"""Drive the Android app's page in a real browser, against the real bridge.

Not collected by pytest (no `test_` prefix) and not part of CI: it needs
Playwright and a Chromium build, and the pages it drives run real
simulations.  It is the *only* way to check the Android front end short of
sideloading an APK, which is why `AGENTS.md` names it as the required check
for `android/app/src/main/assets/www/`.

    pip install playwright
    python tests/android_page_harness.py [screenshot.png]

The only thing faked is `window.host`: the Kotlin bridge is replaced by a
small HTTP shim that forwards to `pllsim.appbridge.call` in this process, so
every number on the page is computed by the same code the app ships.  The
invisible overlay that swallowed every tap, and the ADPLL crash in the
measured spectrum, were both found here and by nothing else.
"""
from __future__ import annotations

import json
import sys
import threading
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

from pllsim import appbridge

WWW = Path(__file__).resolve().parents[1] / "android/app/src/main/assets/www"
PORT = 8765

SHIM = """
window.host = {
  call(id, method, argsJson) {
    fetch('/rpc', {method: 'POST', headers: {'Content-Type': 'application/json'},
                   body: JSON.stringify({method, args: JSON.parse(argsJson)})})
      .then(r => r.text())
      .then(t => window.onHostReply(id, t))
      .catch(e => window.onHostReply(id,
          JSON.stringify({ok: false, error: String(e)})));
  }
};
"""


class _Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(WWW), **kw)

    def do_POST(self):
        if self.path != "/rpc":
            self.send_error(404)
            return
        req = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        body = appbridge.call(req["method"],
                              json.dumps(req.get("args", {}))).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


def serve() -> HTTPServer:
    srv = HTTPServer(("127.0.0.1", PORT), _Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def run_into(page, out_id: str, button_id: str, timeout: int = 300_000):
    """Click and wait for output, without reading the previous run's DOM.

    Waiting on a selector the last run already satisfied passes on nothing --
    that is how the first version of this harness "verified" a button it had
    never actually pressed.
    """
    page.evaluate(f"document.getElementById('{out_id}').innerHTML = ''")
    page.click("#" + button_id)
    page.wait_for_function(
        f"document.getElementById('{out_id}').innerHTML !== ''",
        timeout=timeout)
    errs = page.locator(f"#{out_id} .error")
    assert not errs.count(), errs.first.inner_text()


def open_section(page, name: str):
    """Reach a section the way a user would: open the drawer, pick, and let
    it close.  An entry that leaves the drawer covering the content is the
    bug this checks for.
    """
    if not page.locator("#drawer.open").count():
        # only when closed: an open drawer covers the hamburger, and
        # clicking through it lands on whatever entry sits there
        page.click("#menu-btn")
        page.wait_for_selector("#drawer.open", timeout=10_000)
    page.click(f'#tabs button[data-tab="{name}"]')
    page.wait_for_selector("#drawer:not(.open)", timeout=10_000)
    # state="hidden", not a `[hidden]` selector: wait_for_selector defaults
    # to state="visible", so waiting for `#scrim[hidden]` waits for a
    # display:none element to become visible -- which never happens, and
    # cost a 10 s timeout before it was read carefully
    page.wait_for_selector("#scrim", state="hidden", timeout=10_000)


def _nav_shell(page):
    """All ten sections must be reachable, and nothing invisible may be
    sitting on top of the content."""
    # the scrim must never intercept taps while closed -- the busy overlay
    # swallowed every tap for exactly this reason, and hit-testing the point
    # is the only way to see it
    hit = page.evaluate(
        "(() => { const e = document.elementFromPoint(200, 400);"
        "  if (!e) return 'none';"
        "  if (e.closest('#scrim')) return 'scrim';"
        "  if (e.closest('#lightbox')) return 'lightbox';"
        "  return 'content'; })()")
    assert hit == "content", f"something invisible is covering the page: {hit}"

    assert page.locator("#menu-btn").is_visible()
    # open, pick, and confirm the header now names where we are
    open_section(page, "spurs")
    assert page.locator("#section-title").inner_text() == "Spurs", \
        page.locator("#section-title").inner_text()
    # the scrim closes it
    page.click("#menu-btn")
    page.wait_for_selector("#drawer.open", timeout=10_000)
    page.mouse.click(390, 500)                       # on the scrim, past the drawer
    page.wait_for_selector("#drawer:not(.open)", timeout=10_000)
    # and so does a drag, which is the whole point of the shell
    page.mouse.move(3, 500)
    page.mouse.down()
    page.mouse.move(240, 500, steps=12)
    page.mouse.up()
    page.wait_for_selector("#drawer.open", timeout=10_000)
    page.mouse.move(240, 500)
    page.mouse.down()
    page.mouse.move(10, 500, steps=12)
    page.mouse.up()
    page.wait_for_selector("#drawer:not(.open)", timeout=10_000)
    open_section(page, "workbench")
    print("nav: hamburger, scrim, edge-drag open and drag-close all work")


def _units_set(page, kind: str, value: str):
    """Set the converter's inputs and wait for the readout to be *this* answer.

    Not for "some answer": every keystroke fires a call, so the previous
    input's reply may still be in flight.  The page stamps each render with
    the request that produced it, so waiting for the stamp to catch up with
    the latest request is exact.  Waiting for text to appear instead read a
    stale readout and asserted against it -- which passed, and was wrong.
    """
    page.select_option("#un-kind", kind)
    page.fill("#un-value", value)
    page.wait_for_function(
        "() => +(document.getElementById('un-out').dataset.seq || 0) === unSeq",
        timeout=30_000)


def _units(page):
    """The phase-noise unit converter, checked against the library it wraps.

    Two things here are page behaviour rather than bridge behaviour, so only
    a browser sees them: that typing recomputes without pressing anything,
    and that both dBc conventions are actually rendered.  A converter showing
    one of them would be the exact error it exists to prevent.
    """
    from pllsim.core.jitter import convert_phase_noise

    open_section(page, "units")
    page.fill("#un-f0", "10e9")

    # no click anywhere in this function: `input` alone must produce answers
    _units_set(page, "deg", "0.5")
    want = convert_phase_noise(10e9, deg=0.5)
    out = page.locator("#un-out").inner_text()
    for label, value in (("jitter", f"{want.jitter_fs:.6}"),
                         ("DSB", f"{want.ipn_dbc_dsb:.4f}"),
                         ("SSB", f"{want.ipn_dbc_ssb:.4f}")):
        assert value in out, f"{label} {value} missing from readout: {out!r}"

    # the other direction, and through the convention the rest of the package
    # reports -- the one a reader is most likely to paste in
    _units_set(page, "ipn_dbc_ssb", "-45.5587")
    want = convert_phase_noise(10e9, ipn_dbc_ssb=-45.5587)
    out = page.locator("#un-out").inner_text()
    assert f"{want.deg:.6}" in out, (want.deg, out)
    assert "-45.5587 dBc" in out, out

    # outside small angle the page has to say so rather than quietly serving
    # numbers it cannot support
    _units_set(page, "deg", "30")
    assert "small-angle" in page.locator("#un-out .note").inner_text()
    _units_set(page, "deg", "0.5")
    assert page.locator("#un-out .note").count() == 0, "the warning stuck"

    # and a refused input must not leave the previous answer standing
    _units_set(page, "deg", "-1")
    out = page.locator("#un-out").inner_text()
    assert "error" in out.lower() or "ValueError" in out, out

    print("units: converts live in both directions, shows DSB and SSB, "
          "warns past small angle, rejects bad input")


def _fom(page):
    """The FoM tab, against the numbers the library and the literature give.

    The PLL half is checked with a published triple -- Dartizio'23 reports
    77 fs, 17.2 mW and FoM -249.9 dB -- so this compares the phone against a
    paper, not against my arithmetic.  Both halves recompute on typing; the
    tab has no button at all.
    """
    open_section(page, "fom")

    def settled(out_id, fill):
        before = page.evaluate(
            f"+(document.getElementById('{out_id}').dataset.seq || 0)")
        fill()
        page.wait_for_function(
            "([id, s]) => +(document.getElementById(id).dataset.seq || 0) > s",
            arg=[out_id, before], timeout=30_000)

    settled("fom-pll-out", lambda: (page.fill("#fom-jit", "77"),
                                    page.fill("#fom-pwr", "17.2")))
    out = page.locator("#fom-pll-out").inner_text()
    assert "-249.91" in out, out
    assert "FoM_N" not in out, f"N was blank; FoM_N should not appear: {out}"

    settled("fom-pll-out", lambda: page.fill("#fom-n", "250"))
    out = page.locator("#fom-pll-out").inner_text()
    assert "FoM_N" in out, out

    settled("fom-vco-out", lambda: (page.fill("#fom-f0", "10e9"),
                                    page.fill("#fom-off", "1e6"),
                                    page.fill("#fom-l", "-120"),
                                    page.fill("#fom-vpwr", "10")))
    out = page.locator("#fom-vco-out").inner_text()
    assert "-190.00" in out, out
    # the sideband warning is the point of the note, not decoration
    assert "single sideband" in out, out

    # a blank optional must stay absent rather than become a zero
    settled("fom-vco-out", lambda: page.fill("#fom-ftr", "10"))
    out = page.locator("#fom-vco-out").inner_text()
    assert "FoM_T" in out and "-190.00" in out, out

    settled("fom-pll-out", lambda: page.fill("#fom-pwr", "0"))
    out = page.locator("#fom-pll-out").inner_text()
    assert "error" in out.lower() or "ValueError" in out, out

    print("fom: PLL half matches the published -249.9 dB, VCO half -190.00, "
          "optionals stay optional, bad power rejected")


def drive(browser, shot: str | None) -> None:
    # has_touch: the plot viewer's pinch and double-tap are touch
    # gestures, and a mouse-only context never dispatches them
    page = browser.new_page(viewport={"width": 412, "height": 915},
                            has_touch=True)
    errors: list[str] = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.add_init_script(SHIM)
    page.goto(f"http://127.0.0.1:{PORT}/index.html")
    page.wait_for_selector("#app:not([hidden])", timeout=60_000)
    page.wait_for_selector("#form input[data-path]", timeout=60_000)
    # the page boots in Chinese; one toggle so assertions below can
    # quote the English string rather than a translation of it
    page.click("#lang")
    page.wait_for_selector("#form input[data-path]", timeout=60_000)

    _nav_shell(page)
    _workbench(page)
    _plot_viewer(page)
    _plot_cursor(page)
    _spurs(page)
    _hop(page)
    _selector_and_handoff(page)
    _synth_mod_drift_bench(page)
    _units(page)
    _fom(page)

    if shot:
        page.screenshot(path=shot, full_page=True)
    assert not errors, errors
    print("OK — every section driven, no page errors")
    page.close()


def main(shot: str | None = None) -> int:
    from playwright.sync_api import sync_playwright

    srv = serve()
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                executable_path="/opt/pw-browsers/chromium")
            drive(browser, shot)
            browser.close()
    finally:
        srv.shutdown()
    return 0


def _workbench(page):
    page.select_option("#preset", "cppll_19p2m_4p8g")
    page.wait_for_selector("#form input[data-path]", timeout=60_000)
    # the coarse-band bank is empty for every stock preset (osc_bank_report
    # needs a control-voltage range), so give the varactor one through the
    # form -- the only state in which any of the three GUIs shows the table
    page.locator("details", has=page.locator(
        'input[data-path="osc.v_min"]')).locator("summary").click()
    page.fill('input[data-path="osc.v_min"]', "0.2")
    page.fill('input[data-path="osc.v_max"]', "1.0")
    page.click("#run-analyze")
    page.wait_for_selector("#analyze-out img.plot", timeout=180_000)
    assert page.locator("#bank-out table.rows tr").count() > 1, "no bank table"
    base = page.locator("#analyze-out .metric b").first.inner_text()
    page.fill('input[data-path="osc.pn_dbchz"]', "-90")
    page.wait_for_selector("#edited:not([hidden])")
    page.evaluate("document.getElementById('analyze-out').innerHTML = ''")
    page.click("#run-analyze")
    page.wait_for_selector("#analyze-out img.plot", timeout=180_000)
    worse = page.locator("#analyze-out .metric b").first.inner_text()
    assert float(worse.split()[0]) > float(base.split()[0]) * 1.5, (base, worse)
    # every preset's linear model carries the IPN breakdown, not only the
    # benchmark tab's five: curve + pie is two plots, and the share table
    # is read back rather than the image trusted
    assert page.locator("#analyze-out img.plot").count() == 2
    cells = page.locator("#analyze-out table.rows td").all_inner_texts()
    shares = [float(c) for c in cells[1::3]]
    assert abs(sum(shares) - 100.0) < 0.3, shares
    print(f"workbench: bank renders; a form edit moved {base} -> {worse}; "
          f"IPN pie sums to {sum(shares):.1f}%")


def _pinch(page, a, b, a2, b2, steps: int = 8):
    """A real two-finger pinch, through Chromium's input pipeline.

    `page.mouse` cannot express two contacts, and dispatching synthetic DOM
    events would only test the harness's own events -- so this goes through
    CDP's touch input, the same path a finger takes.
    """
    cdp = page.context.new_cdp_session(page)

    def pts(p, q):
        return [{"x": p[0], "y": p[1], "id": 1}, {"x": q[0], "y": q[1], "id": 2}]

    cdp.send("Input.dispatchTouchEvent",
             {"type": "touchStart", "touchPoints": pts(a, b)})
    for i in range(1, steps + 1):
        f = i / steps
        cdp.send("Input.dispatchTouchEvent", {"type": "touchMove", "touchPoints": pts(
            (a[0] + (a2[0] - a[0]) * f, a[1] + (a2[1] - a[1]) * f),
            (b[0] + (b2[0] - b[0]) * f, b[1] + (b2[1] - b[1]) * f))})
    cdp.send("Input.dispatchTouchEvent", {"type": "touchEnd", "touchPoints": []})


def _scale(page) -> float:
    return float(page.locator("#lightbox").get_attribute("data-scale"))


def _plot_viewer(page):
    """The full-screen plot viewer, driven as a finger drives it.

    A phase-noise plot spans eight decades in a 412 px column, so this is the
    difference between seeing that a curve exists and reading it.  The scale
    is published in a data attribute for exactly this reason: a screenshot
    cannot tell you whether a pinch scaled by the right amount.
    """
    import math
    page.locator("#analyze-out img.plot").first.click()
    page.wait_for_selector("#lightbox:not([hidden])", timeout=10_000)
    assert _scale(page) == 1.0

    # double-tap magnifies to the image's own resolution -- no more, because
    # past native it only softens the detail the zoom exists to show
    nat_w, disp_w = page.evaluate(
        "(() => { const e = document.getElementById('lightbox-img');"
        "  return [e.naturalWidth, e.offsetWidth]; })()")
    page.touchscreen.tap(206, 450)
    page.touchscreen.tap(206, 450)
    page.wait_for_function(
        "parseFloat(document.getElementById('lightbox').dataset.scale) > 1.5",
        timeout=5_000)
    native = max(2.0, min(8.0, nat_w / disp_w))
    assert abs(_scale(page) - native) < 0.02, (_scale(page), native)

    page.touchscreen.tap(206, 450)
    page.touchscreen.tap(206, 450)
    page.wait_for_function(
        "parseFloat(document.getElementById('lightbox').dataset.scale) < 1.05",
        timeout=5_000)

    # a two-finger pinch scales by the ratio of the finger separation; an
    # assertion that merely says "bigger than before" passes on any nonsense
    a, b, a2, b2 = (150, 400), (260, 500), (90, 330), (320, 570)
    want = (math.dist(a2, b2) / math.dist(a, b))
    _pinch(page, a, b, a2, b2)
    page.wait_for_function(
        "parseFloat(document.getElementById('lightbox').dataset.scale) > 1.5",
        timeout=5_000)
    assert abs(_scale(page) - want) < 0.05, (_scale(page), want)

    # and a drag moves it, but only while zoomed in
    before = page.evaluate(
        "getComputedStyle(document.getElementById('lightbox-stage')).transform")
    page.mouse.move(206, 450)
    page.mouse.down()
    page.mouse.move(120, 380, steps=10)
    page.mouse.up()
    after = page.evaluate(
        "getComputedStyle(document.getElementById('lightbox-stage')).transform")
    assert before != after, "a zoomed plot did not pan"

    # rotating the phone relayouts the image; the anchor has to be re-measured
    page.set_viewport_size({"width": 915, "height": 412})
    page.wait_for_function(
        "document.getElementById('lightbox').dataset.scale === '1.000'",
        timeout=5_000)
    page.set_viewport_size({"width": 412, "height": 915})

    assert page.evaluate("window.onAndroidBack()") is True, \
        "back did not consume the open viewer"
    page.wait_for_selector("#lightbox", state="hidden", timeout=10_000)
    print(f"plot viewer: opens at 1.0, double-tap -> {native:.2f} (native), "
          f"pinch -> {want:.2f}, pan + rotate + back all work")


def _plot_cursor(page):
    """The readout, checked against the model rather than against itself.

    The whole promise of a cursor is that the number under it is the number
    on the curve, so the rows are compared with a fresh `analyze()` in this
    process -- the same check a reader would do by hand, and the only one
    that can catch the transfer quietly rounding the value away.
    """
    import math

    from pllsim import presets
    from pllsim.core.jitter import ldbc_from_sphi

    # _workbench left osc.pn_dbchz at -90 and a varactor range on the form,
    # so the plot on screen is NOT the stock preset.  Comparing its readout
    # against presets.cppll_19p2m_4p8g() reported vco as -111.12 where the
    # preset says -142.84 and looked exactly like a broken cursor -- it was a
    # broken assertion.  Re-select the preset (which clears the overrides) so
    # the page and the reference are the same configuration.
    page.select_option("#preset", "cppll_19p2m_4p8g")
    page.wait_for_selector("#form input[data-path]", timeout=60_000)
    page.click("#run-analyze")
    page.wait_for_selector("#analyze-out img.plot", timeout=180_000)
    assert page.locator("#edited").is_hidden(), "the form still carries edits"

    # the pie has no coordinate system, so it must offer no cursor at all
    page.locator("#analyze-out img.plot").nth(1).click()
    page.wait_for_selector("#lightbox:not([hidden])", timeout=10_000)
    assert page.locator("#lightbox-cursor").is_hidden(), \
        "the IPN pie was offered a cursor"
    # and the close button must work -- tapping the X did nothing at all for
    # a release, because pointer capture on #lightbox moved the click target
    page.click("#lightbox-close")
    page.wait_for_selector("#lightbox", state="hidden", timeout=10_000)

    # The viewer's box has to agree with the map it is read through, so this
    # swaps the breakdown (9/6) in over the pie (7.5/5.5) and measures inside
    # one synchronous block.
    #
    # Kept, but read the comment: this was written chasing a "wrong reading"
    # that looked like an image-load race and was actually the assertion below
    # comparing against a preset the page was no longer showing.  It is a
    # cheap invariant, not evidence of a race -- and it does not go red when
    # the layout defences are removed, because by here the PNG is cached and
    # Chromium knows its intrinsic size immediately.
    page.locator("#analyze-out img.plot").nth(1).click()
    page.wait_for_selector("#lightbox:not([hidden])", timeout=10_000)
    page.wait_for_function(
        "document.getElementById('lightbox-img').complete", timeout=10_000)
    box = page.evaluate(
        "(() => { const ims = document.querySelectorAll('#analyze-out img.plot');"
        "  const pn = ims[0], d = plotData.get(pn.dataset.cursor);"
        "  openLightbox(pn.src, pn.dataset.cursor, pn.dataset.nocursor);"
        "  const s = document.getElementById('lightbox-stage')"
        "    .getBoundingClientRect();"
        "  return [s.width / s.height, d.w / d.h]; })()")
    assert abs(box[0] - box[1]) < 0.01, (
        "the viewer's box came from the previous image, so every cursor "
        f"reading would be at the wrong abscissa: {box}")
    page.evaluate("closeLightbox()")
    page.wait_for_selector("#lightbox", state="hidden", timeout=10_000)

    page.locator("#analyze-out img.plot").first.click()
    page.wait_for_selector("#lightbox:not([hidden])", timeout=10_000)
    page.click("#lightbox-cursor")
    page.wait_for_selector("#lightbox-readout:not([hidden])", timeout=10_000)
    page.mouse.move(206, 500)
    page.mouse.down()
    page.mouse.move(300, 500, steps=6)
    page.mouse.up()

    shown = page.locator("#lightbox-readout").inner_text().splitlines()
    xs = float(page.locator("#lightbox").get_attribute("data-cursor-x"))
    ar = presets.cppll_19p2m_4p8g().analyze()
    i = min(range(ar.f.size), key=lambda k: abs(ar.f[k] - xs))
    assert abs(ar.f[i] - xs) / xs < 1e-4, (ar.f[i], xs)
    truth = {k: ldbc_from_sphi(s)[i] for k, s in ar.pn_breakdown.items()}
    seen = {}
    for row in shown[1:]:
        name, _, value = row.strip().rpartition(" ")
        seen[name.strip()] = float(value)
    assert len(seen) == len(truth), (sorted(seen), sorted(truth))
    for name, value in seen.items():
        key = "total" if name.startswith("total") else name
        assert abs(value - truth[key]) < 0.01, (name, value, truth[key])
    order = [float(v) for v in seen.values()]
    assert order == sorted(order, reverse=True), order

    page.click("#lightbox-delta")
    page.mouse.move(300, 500)
    page.mouse.down()
    page.mouse.move(150, 500, steps=6)
    page.mouse.up()
    text = page.locator("#lightbox-readout").inner_text()
    x2 = float(page.locator("#lightbox").get_attribute("data-cursor-x"))
    j = min(range(ar.f.size), key=lambda k: abs(ar.f[k] - x2))
    tot = ldbc_from_sphi(ar.pn_breakdown["total"])
    want_slope = (tot[j] - tot[i]) / math.log10(ar.f[j] / ar.f[i])
    assert f"{want_slope:+.1f} dB/dec".replace("+", "+") in text or \
        f"{want_slope:.1f} dB/dec" in text, (text, want_slope)

    page.evaluate("window.onAndroidBack()")
    page.wait_for_selector("#lightbox", state="hidden", timeout=10_000)
    print(f"plot cursor: {len(seen)} curves read at {xs:.4g} Hz, all within "
          f"0.01 dB of analyze(); slope {want_slope:+.1f} dB/dec; "
          f"pie offers none; X closes")


def _spurs(page):
    open_section(page, "spurs")
    page.select_option("#sp-preset", "cppll_frac_38p4m_6g")
    page.dispatch_event("#sp-preset", "change")
    page.fill("#sp-m", "4")                      # coarser than t_reset
    page.dispatch_event("#sp-m", "change")
    page.wait_for_function(
        "document.getElementById('sp-ref-note').textContent.includes('MB')",
        timeout=60_000)
    note = page.locator("#sp-ref-note").inner_text()
    assert "under-resolved" in note, note        # the silent-low-reading trap
    run_into(page, "sp-predict-out", "sp-predict")
    page.fill("#sp-mmeas", "128")
    page.fill("#sp-ncyc", "20000")
    run_into(page, "sp-measure-out", "sp-measure")
    assert not any("ignored" in t for t in
                   page.locator("#sp-measure-out .note").all_inner_texts())
    # an architecture with no intra-period record says so rather than
    # silently returning a spectrum that cannot contain the reference spur
    page.select_option("#sp-preset", "adpll_bb_100m_10g")
    page.dispatch_event("#sp-preset", "change")
    page.wait_for_function(
        "document.getElementById('sp-ref-note').textContent"
        ".includes('no intra-period record')", timeout=60_000)
    run_into(page, "sp-measure-out", "sp-measure")
    assert any("ignored" in t for t in
               page.locator("#sp-measure-out .note").all_inner_texts())
    print("spurs: coarse-M warning, M applied on CPPLL, ignored on ADPLL")


def _hop(page):
    open_section(page, "hop")
    page.select_option("#hop-preset", "cppll_19p2m_4p8g")
    page.wait_for_function(
        "document.getElementById('hop-fll').textContent.includes('no FLL')",
        timeout=60_000)
    page.select_option("#hop-preset", "sspll_19p2m_4p8g")
    page.wait_for_function(
        "document.getElementById('hop-fll').textContent.includes('margin')",
        timeout=60_000)
    page.fill("#hop-hz", "-50e6")
    page.fill("#hop-ncyc", "25000")
    run_into(page, "hop-out", "hop-run")
    assert page.locator("#hop-out img.plot").count() == 1
    print("hop:", page.locator("#hop-fll p").inner_text()[:48])


def _selector_and_handoff(page):
    open_section(page, "selector")
    run_into(page, "sel-out", "sel-run")
    heads = page.locator("#sel-out table.rows th").all_inner_texts()
    assert "PM [deg]" in heads, heads
    assert page.locator("#sel-out table.rows tr").count() - 1 == 7
    page.locator("#sel-out button.handoff").first.click()
    page.wait_for_selector("#wb-candidate:not([hidden])", timeout=60_000)
    page.wait_for_selector("#form input[data-path]", timeout=60_000)
    assert page.locator("#preset").is_disabled()
    page.evaluate("document.getElementById('analyze-out').innerHTML = ''")
    page.click("#run-analyze")
    page.wait_for_selector("#analyze-out img.plot", timeout=180_000)
    jit = page.locator("#analyze-out .metric b").first.inner_text()
    page.click("#wb-back")
    page.wait_for_selector("#form input[data-path]", timeout=60_000)
    assert not page.locator("#preset").is_disabled()
    print(f"selector: PM column present, handoff analyzed at {jit}, back ok")


def _synth_mod_drift_bench(page):
    open_section(page, "synth")
    run_into(page, "sy-cp-out", "sy-cp-run")
    page.select_option("#sw-preset", "sspll_19p2m_4p8g")
    page.fill("#sw-n", "4")
    run_into(page, "sw-out", "sw-run")

    open_section(page, "mod")
    page.fill("#mod-ncyc", "80000")
    run_into(page, "mod-out", "mod-run")
    evm = page.locator("#mod-out .metric b").first.inner_text()

    open_section(page, "drift")
    page.fill("#dr-ncyc", "40000")
    page.fill("#dr-start", "50000")
    run_into(page, "dr-out", "dr-run")
    lag = page.locator("#dr-out .metric b").first.inner_text()

    open_section(page, "bench")
    page.wait_for_selector("#bench-out table.rows", timeout=60_000)
    rows = page.locator("#bench-out table.rows tr").count() - 1
    # the IPN pie: its premise is that the slices are a partition, so read
    # the shares back off the rendered table rather than trusting the image
    page.select_option("#pie-preset", "bench_wu19_spll_frac_52m_6p253g")
    run_into(page, "pie-out", "pie-run")
    assert page.locator("#pie-out img.plot").count() == 1
    cells = page.locator("#pie-out table.rows td").all_inner_texts()
    shares = [float(c) for c in cells[1::3]]
    assert abs(sum(shares) - 100.0) < 0.3, shares
    dom = page.locator("#pie-out .metric b").nth(2).inner_text()
    print(f"synth/mod/drift/bench: EVM {evm}, peak lag {lag}, {rows} papers, "
          f"pie sums to {sum(shares):.1f}% with {dom} dominant")


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else None))
