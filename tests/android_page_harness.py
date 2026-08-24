"""Drive the Android app's page in a real browser, against the real bridge.

Not collected by pytest (no `test_` prefix) and not part of CI: it needs
Playwright and a Chromium build, and the pages it drives run real
simulations.  It is the *only* way to check the Android front end short of
sideloading an APK, which is why `AGENTS.md` names it as the required check
for `android/app/src/main/assets/www/`.

    pip install playwright
    python tests/android_page_harness.py [screenshot.png] [--nav tabs|drawer]

Both navigation shells are driven by default.  That is deliberate: the
horizontal bar is kept only so it can be compared against the drawer on a
real phone, and a shell nobody exercises is a shell that rots -- which is
exactly how the two desktop GUIs drifted apart.

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
    """Reach a section the way a user would, in whichever shell is loaded.

    In the bar the entry is always on screen; in the drawer it has to be
    opened first, and the drawer must close again afterwards -- an entry that
    leaves the drawer covering the content is the bug this checks for.
    """
    nav = page.evaluate("document.documentElement.dataset.nav")
    if nav == "drawer" and not page.locator("#drawer.open").count():
        # only when closed: an open drawer covers the hamburger, and
        # clicking through it lands on whatever entry sits there
        page.click("#menu-btn")
        page.wait_for_selector("#drawer.open", timeout=10_000)
    page.click(f'#tabs button[data-tab="{name}"]')
    if nav == "drawer":
        page.wait_for_selector("#drawer:not(.open)", timeout=10_000)
        # state="hidden", not a `[hidden]` selector: wait_for_selector defaults
        # to state="visible", so waiting for `#scrim[hidden]` waits for a
        # display:none element to become visible -- which never happens, and
        # cost a 10 s timeout before it was read carefully
        page.wait_for_selector("#scrim", state="hidden", timeout=10_000)


def _nav_shell(page, nav: str):
    """Whatever the shell, the same eight sections must be reachable, and
    nothing invisible may be sitting on top of the content."""
    assert page.evaluate("document.documentElement.dataset.nav") == nav
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

    if nav == "tabs":
        assert page.locator("#menu-btn").is_hidden()
        assert page.locator("#scrim").is_hidden()
        print("nav[tabs]: bar visible, no hamburger, scrim inert")
        return

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
    print("nav[drawer]: hamburger, scrim, edge-drag open and drag-close all work")


def drive(browser, nav: str, shot: str | None) -> None:
    # has_touch: the plot viewer's pinch and double-tap are touch
    # gestures, and a mouse-only context never dispatches them
    page = browser.new_page(viewport={"width": 412, "height": 915},
                            has_touch=True)
    errors: list[str] = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.add_init_script(SHIM)
    page.goto(f"http://127.0.0.1:{PORT}/index.html?nav={nav}")
    page.wait_for_selector("#app:not([hidden])", timeout=60_000)
    page.wait_for_selector("#form input[data-path]", timeout=60_000)
    # the page boots in Chinese; one toggle so assertions below can
    # quote the English string rather than a translation of it
    page.click("#lang")
    page.wait_for_selector("#form input[data-path]", timeout=60_000)

    _nav_shell(page, nav)
    _workbench(page)
    _plot_viewer(page)
    _spurs(page)
    _hop(page)
    _selector_and_handoff(page)
    _synth_mod_drift_bench(page)

    if shot:
        page.screenshot(path=shot, full_page=True)
    assert not errors, errors
    print(f"OK [{nav}] — every section driven, no page errors")
    page.close()


def main(shot: str | None = None, navs=("tabs", "drawer")) -> int:
    from playwright.sync_api import sync_playwright

    srv = serve()
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                executable_path="/opt/pw-browsers/chromium")
            for nav in navs:
                out = None if shot is None else (
                    shot if len(navs) == 1
                    else shot.replace(".png", f"-{nav}.png"))
                drive(browser, nav, out)
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
        "getComputedStyle(document.getElementById('lightbox-img')).transform")
    page.mouse.move(206, 450)
    page.mouse.down()
    page.mouse.move(120, 380, steps=10)
    page.mouse.up()
    after = page.evaluate(
        "getComputedStyle(document.getElementById('lightbox-img')).transform")
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
    args = sys.argv[1:]
    navs = ("tabs", "drawer")
    if "--nav" in args:
        i = args.index("--nav")
        navs = (args[i + 1],)
        args = args[:i] + args[i + 2:]
    sys.exit(main(args[0] if args else None, navs))
