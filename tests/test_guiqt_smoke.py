"""Desktop GUI smoke: instantiate every page offscreen, run computations.

Skipped automatically when PySide6 is absent (pip install pllsim[guiqt]).
QT_QPA_PLATFORM=offscreen renders without a display server; the compute
half of each page is exercised synchronously (the same functions the
worker threads call).
"""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtWidgets = pytest.importorskip(
    "PySide6.QtWidgets", exc_type=ImportError,
    reason="PySide6 not installed or system GL libraries missing")
QApplication = QtWidgets.QApplication


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def test_main_window_builds_all_pages(app):
    from pllsim.guiqt.app import PAGES, MainWindow
    win = MainWindow()
    assert win.stack.count() == len(PAGES) == 11
    for i in range(win.stack.count()):
        win.nav.setCurrentRow(i)
        assert win.stack.currentIndex() == i
    win.deleteLater()


def test_workbench_analyze_and_render(app):
    from pllsim.guiqt.page_workbench import WorkbenchPage
    page = WorkbenchPage()
    page.preset.setCurrentText("spll_frac_52m_6p253g")
    ar = page.compute_analyze()               # same fn the worker runs
    assert 100 < ar.jitter_fs < 400
    page.render_analyze(ar)                   # renders without raising
    assert page._a_lay.count() > 0
    page.deleteLater()


def test_workbench_analyze_shows_the_ipn_breakdown(app):
    """Every preset's linear model gets the pie, not only the benchmarks."""
    from pllsim.guiqt.page_workbench import WorkbenchPage
    page = WorkbenchPage()
    page.preset.setCurrentText("ilcm_250m_12g")   # only three sources
    ar = page.compute_analyze()
    page.render_analyze(ar)
    assert sum(s for _k, s, _j in ar.ipn_shares()) == pytest.approx(1.0)
    assert page._a_lay.count() >= 2, "curve, pie and share table expected"
    page.deleteLater()


def test_workbench_form_overrides_flow(app):
    from pllsim.guiqt.page_workbench import WorkbenchPage
    page = WorkbenchPage()
    page.preset.setCurrentText("cppll_19p2m_4p8g")
    edit = page.form._edits["osc.pn_dbchz"]
    edit.setText("-116")
    ar = page.compute_analyze()
    ar0_jit = ar.jitter_fs
    edit.setText(page.form._initial["osc.pn_dbchz"])   # restore
    ar0 = page.compute_analyze()
    assert ar0_jit > ar0.jitter_fs            # worse VCO -> more jitter
    page.deleteLater()


def test_workbench_fine_oversample_reaches_the_engine(app):
    """The spinbox has to change what the run measures, not just exist.

    With M = 1 the record has one control-voltage sample per reference edge
    and the reference spur is invisible; raising M is the whole reason the
    knob is there, so the test is that the spur table appears.
    """
    from pllsim.guiqt.page_workbench import WorkbenchPage
    page = WorkbenchPage()
    page.preset.setCurrentText("cppll_19p2m_4p8g")
    page.n_cycles.setValue(10_000)
    page.cb_noise.setChecked(False)
    page.form._edits["cp.mismatch_pct"].setText("5")

    page.fine_os.setValue(1)
    assert page.compute_sim()[1].spurs_fft == {}
    page.fine_os.setValue(128)
    assert page.compute_sim()[1].spurs_fft, "M > 1 must expose the ripple"
    page.deleteLater()


def test_workbench_says_what_a_coarse_m_costs_and_hides_what_it_misses(app):
    from pllsim.guiqt.page_workbench import WorkbenchPage
    page = WorkbenchPage()
    page.preset.setCurrentText("cppll_19p2m_4p8g")
    page.fine_os.setValue(0)
    assert page.fine_note.text() == ""
    page.fine_os.setValue(4)                  # far coarser than t_reset
    assert "MB" in page.fine_note.text()
    assert "under-resolved" in page.fine_note.text()
    # and an architecture with no analog control node says so instead
    page.preset.setCurrentText("adpll_100m_10g")
    page.fine_os.setValue(64)
    assert "no intra-period record" in page.fine_note.text()
    page.deleteLater()


def test_spurs_page_compares_the_reference_spur(app):
    """The Spurs page could only ever show *fractional* spurs.

    The reference one lives inside a single reference period, so it needs the
    intra-period record that only the workbench could ask for.
    """
    from pllsim.guiqt.page_analysis import SpursPage
    page = SpursPage()
    page.preset.setCurrentText(
        next(n for n in [page.preset.itemText(i)
                         for i in range(page.preset.count())]
             if n.startswith("cppll")))
    page.fine_os.setValue(128)
    table, notes = page.compute_ref()          # same fn the worker runs
    assert table, "no comparison rows"
    assert any(r["analytic [dBc]"] != "-" for r in table), table
    assert any(r["measured [dBc]"] != "-" for r in table), table
    page.render_ref((table, notes))            # renders without raising
    assert page._body.count() > 0
    page.deleteLater()


def test_spurs_page_says_why_a_sampling_loop_has_no_reference_spur(app):
    """"-" with a reason beside it is the answer, not a missing number."""
    from pllsim.guiqt.page_analysis import SpursPage
    page = SpursPage()
    page.preset.setCurrentText(
        next(n for n in [page.preset.itemText(i)
                         for i in range(page.preset.count())]
             if n.startswith("sspll")))
    page.fine_os.setValue(64)
    page._fine_hint()
    assert "MB" in page.fine_note.text()
    table, notes = page.compute_ref()
    assert all(r["analytic [dBc]"] == "-" for r in table), table
    assert any("pedestal" in n or "no charge" in n or "no analytic" in n
               for n in notes), notes
    page.deleteLater()


def test_spurs_measured_spectrum_survives_an_adpll_preset(app):
    """Two of this page's own seven fractional presets are ADPLLs, whose
    simulate() takes no fine_oversample -- and the page passed M straight in,
    so pressing "Simulate + plot spectrum" on either raised
    "ADPLL.simulate() got an unexpected keyword argument 'fine_oversample'".
    Mutation: drop simulate_kwargs from compute_measure and this goes red.
    """
    from pllsim.guiqt.page_analysis import SpursPage
    page = SpursPage()
    page.MEASURE_CYCLES = 4_000
    names = [page.preset.itemText(i) for i in range(page.preset.count())]
    page.preset.setCurrentText(next(n for n in names if "adpll" in n))
    page.fine_os.setValue(128)
    page._fine_hint()
    assert "no intra-period record" in page.fine_note.text()
    sim, ar = page.compute_measure()            # used to raise TypeError
    page.render_measure((sim, ar))
    assert ar.jitter_fs > 0
    page.deleteLater()


def test_spurs_measured_spectrum_reaches_past_the_reference_edge(app):
    """M is what puts the reference spur in this plot: without it the record
    is one sample per reference edge and nothing at fref can appear."""
    from pllsim.guiqt.page_analysis import SpursPage
    page = SpursPage()
    page.MEASURE_CYCLES = 20_000
    names = [page.preset.itemText(i) for i in range(page.preset.count())]
    page.preset.setCurrentText(next(n for n in names if n.startswith("cppll")))
    page.fine_os.setValue(64)
    sim, _ = page.compute_measure()
    from pllsim import presets
    fref = presets.ALL_PRESETS[page.preset.currentText()]().cfg.fref
    assert any(abs(f - fref) < 1e3 for f in sim.spurs_fft), sim.spurs_fft
    page.deleteLater()


def test_selector_page_flow(app):
    from pllsim.guiqt.page_design import SelectorPage
    page = SelectorPage()
    page.fref.setText("100e6")
    page.fout.setText("8e9")
    page.jmax.setText("120")
    # run the worker synchronously through the same code path
    from pllsim.selector import Requirement, select
    rep = select(Requirement(fref=100e6, fout=8e9, jitter_fs_max=120))
    assert rep.best is not None
    page.deleteLater()


def test_benchmarks_page_static(app):
    from PySide6.QtWidgets import QTableWidget

    from pllsim import presets
    from pllsim.guiqt.page_analysis import BenchmarksPage
    page = BenchmarksPage()
    # the table is built from the single source in presets, not a GUI-local
    # copy: a stale duplicate is how the published-vs-model numbers drifted
    rows = presets.benchmark_table()
    assert len(rows) == 5
    table = page.findChild(QTableWidget)
    assert table is not None
    assert table.rowCount() == len(rows)
    page.deleteLater()


# ---------------------------------------------------------------- dynamics
# These three pages hid their whole computation in a closure inside _go, so a
# test could reach the layout but never the code that runs when the button is
# pressed -- which is the failure this GUI has actually had.  Each now has a
# named compute()/render() pair, and these call exactly what the worker calls.
def test_modulation_page_computes_an_evm(app):
    from pllsim.guiqt.page_dynamics import ModulationPage
    page = ModulationPage()
    page.n_cyc.setText("60000")
    res = page.compute()
    e = res[0]
    assert 0.0 < e["evm_pct"] < 100.0
    page.render(res)
    page.deleteLater()


def test_hop_settling_page_computes_and_renders(app):
    from pllsim.guiqt.page_dynamics import HopSettlingPage
    page = HopSettlingPage()
    page.n_cyc.setText("60000")
    page.hop.setText("-40e6")
    r = page.compute()
    assert r.f_to != 0.0
    page.render(r)
    page.deleteLater()


def test_hop_settling_page_computes_a_seed_population(app):
    """Settling is a yield quantity, so the page has a second button."""
    from pllsim.guiqt.page_dynamics import HopSettlingPage
    page = HopSettlingPage()
    page.n_cyc.setText("40000")
    page.n_seeds.setText("3")
    stats = page.compute_stats()
    assert stats["t_phase_s"].size == 3
    assert stats["p95_s"] >= stats["p50_s"]
    page.render_stats(stats)
    page.deleteLater()


def test_drift_page_computes_a_tracking_lag(app):
    from pllsim.guiqt.page_dynamics import DriftPage
    page = DriftPage()
    page.n_ramp.setText("20000")
    page.start.setText("30000")
    res = page.compute()
    lag = res[2]
    assert lag.size == 50_000
    assert lag[-1] > 0.0, "a drifting gain must leave a tracking lag"
    page.render(res)
    page.deleteLater()


def test_benchmarks_page_plots_an_ipn_pie(app):
    """The table says whether the model matches the paper; the pie says
    which source to attack first.  Both live on this page now."""
    from pllsim.guiqt.page_analysis import BenchmarksPage
    page = BenchmarksPage()
    names = [page.pie_preset.itemText(i)
             for i in range(page.pie_preset.count())]
    assert len(names) == 5, names
    page.pie_preset.setCurrentText("bench_wu19_spll_frac_52m_6p253g")
    name, ar = page.compute_pie()             # same fn the worker runs
    assert name == "bench_wu19_spll_frac_52m_6p253g"
    assert sum(s for _k, s, _j in ar.ipn_shares()) == pytest.approx(1.0)
    page.render_pie((name, ar))               # renders without raising
    page.deleteLater()


def test_the_desktop_entry_point_is_importable(app):
    """`pllsim-gui` and the exe both go through app.main."""
    from pllsim.guiqt.app import main
    assert callable(main)


def test_every_figure_gets_its_own_navigation_toolbar(app):
    """Zoom is the feature; a toolbar bound to the wrong canvas is the bug.

    These stacks routinely hold two unrelated figures (the PN breakdown and
    its IPN pie), so "a toolbar exists" is not the property worth checking --
    "toolbar i drives canvas i, and only canvas i" is.  Mutation: parent both
    toolbars to the first canvas and the second assertion goes red.
    """
    import matplotlib.pyplot as plt

    from pllsim.guiqt.widgets import FigList

    fl = FigList()
    figs = []
    for xmax in (10.0, 20.0):
        fig, ax = plt.subplots()
        ax.plot([0, xmax], [0, 1])
        figs.append(fig)
    fl.set_figs(figs)

    assert len(fl.canvases()) == 2
    assert len(fl.toolbars()) == 2
    # constructed is not the same as shown: NavigationToolbar2QT parents
    # itself to the widget passed in, so findChildren finds a toolbar that
    # was never added to a layout and that the user cannot see.  Membership
    # in the parent's layout is what puts it on screen.
    for bar in fl.toolbars():
        lay = bar.parentWidget().layout()
        assert lay is not None and lay.indexOf(bar) >= 0, \
            "the toolbar exists but is in no layout -- invisible to the user"

    axes = [c.figure.axes[0] for c in fl.canvases()]
    original = [ax.get_xlim() for ax in axes]
    # record the home view the way the toolbar does on first interaction
    for bar in fl.toolbars():
        bar.push_current()

    # a zoom on the second figure only
    axes[1].set_xlim(1.0, 2.0)
    fl.toolbars()[1].home()
    assert axes[1].get_xlim() == pytest.approx(original[1]), \
        "toolbar 1 did not restore its own canvas -- it is bound elsewhere"

    # and the first figure must not have been touched by it
    axes[0].set_xlim(3.0, 4.0)
    fl.toolbars()[1].home()
    assert axes[0].get_xlim() == pytest.approx((3.0, 4.0)), \
        "toolbar 1 reached into canvas 0 -- the toolbars share a canvas"

    fl.deleteLater()


def test_the_toolbar_offers_the_controls_zooming_actually_needs(app):
    """`mode` is what matplotlib's own code reads to decide how a drag is
    interpreted, so entering the modes is the honest check -- an icon that
    exists but sets no mode zooms nothing.
    """
    import matplotlib.pyplot as plt

    from pllsim.guiqt.widgets import FigList

    fig, ax = plt.subplots()
    ax.plot([0, 1], [0, 1])
    fl = FigList()
    fl.set_figs([fig])
    bar = fl.toolbars()[0]

    bar.zoom()
    assert str(bar.mode) == "zoom rect", str(bar.mode)
    bar.zoom()                                  # toggles back off
    assert str(bar.mode) == ""
    bar.pan()
    assert str(bar.mode) == "pan/zoom", str(bar.mode)
    bar.pan()
    assert str(bar.mode) == ""
    fl.deleteLater()


def _drive(fl, fx, click=False):
    """Move (and optionally click) the real mouse-event path at abscissa fx."""
    import numpy as np
    from matplotlib.backend_bases import MouseButton, MouseEvent
    cur = fl.cursors()[0]
    line = max(cur.lines, key=lambda ln: len(ln.get_xdata()))
    x = np.asarray(line.get_xdata(), float)
    y = np.asarray(line.get_ydata(), float)
    i = int(np.argmin(np.abs(x - fx)))
    px, py = cur.ax.transData.transform((x[i], y[i]))
    name = "button_press_event" if click else "motion_notify_event"
    args = (MouseButton.LEFT,) if click else ()
    MouseEvent(name, cur.canvas, px, py, *args)._process()
    return cur, float(x[i])


def _pn_figlist():
    from pllsim import presets
    from pllsim.guiqt.widgets import FigList
    from pllsim.plotting import plot_pn_breakdown
    ar = presets.cppll_19p2m_4p8g().analyze()
    fl = FigList()
    fl.set_figs([plot_pn_breakdown(ar, None)])
    fl.resize(1100, 700)
    return fl, ar


def test_the_cursor_reads_the_curves_not_a_recomputation(app):
    """Every row must be the artist's own number at the cursor's abscissa.

    A readout that recomputes can drift from the drawn line by a little, which
    is unfalsifiable by eye and exactly the failure this project keeps paying
    for.  Mutation: have _values_at interpolate instead of taking the sample,
    or offset any row, and this goes red.
    """
    import numpy as np
    fl, ar = _pn_figlist()
    assert len(fl.cursors()) == 1
    cur, xs = _drive(fl, 1e6)
    rows = cur._values_at(xs)
    assert len(rows) == len(ar.pn_breakdown), [k for k, _ in rows]
    for label, value in rows:
        line = next(ln for ln in cur.lines if ln.get_label() == label)
        x = np.asarray(line.get_xdata(), float)
        y = np.asarray(line.get_ydata(), float)
        assert value == pytest.approx(y[int(np.argmin(np.abs(x - xs)))], abs=1e-9)
    assert [v for _k, v in rows] == sorted((v for _k, v in rows), reverse=True)
    fl.deleteLater()


def test_the_cursor_snaps_to_a_real_sample(app):
    """Halfway between two samples the crosshair must sit on one of them, not
    between: a readout at an abscissa the model never evaluated is a number
    nobody can reproduce.
    """
    import numpy as np
    fl, _ar = _pn_figlist()
    cur, _xs = _drive(fl, 3.3e5)
    drawn = float(cur._vline.get_xdata()[0])
    grid = np.asarray(cur.lines[0].get_xdata(), float)
    assert np.min(np.abs(grid - drawn)) == 0.0, drawn
    fl.deleteLater()


def test_a_reference_cursor_gives_delta_and_slope(app):
    """The slope is the point of the second cursor: -20 vs -30 dB/dec is how
    a flicker region is told from a thermal one, and by eye on a squeezed log
    axis that is a coin toss.
    """
    import numpy as np
    fl, _ar = _pn_figlist()
    cur, x_ref = _drive(fl, 1e6, click=True)
    assert cur.ref is not None and cur._rline.get_visible()
    # deliberately *not* a decade apart: with log10(x_now / x_ref) == 1 the
    # division by the decade span is invisible, and dropping it passed this
    # test until the pair was changed
    cur, x_now = _drive(fl, 3e6)
    text = cur._text.get_text()
    assert abs(np.log10(x_now / x_ref) - 1.0) > 0.3, "back to a decade apart"

    total = next(ln for ln in cur.lines if ln.get_label().startswith("total"))
    x = np.asarray(total.get_xdata(), float)
    y = np.asarray(total.get_ydata(), float)
    a = y[int(np.argmin(np.abs(x - x_ref)))]
    b = y[int(np.argmin(np.abs(x - x_now)))]
    want_slope = (b - a) / np.log10(x_now / x_ref)
    assert f"{b - a:+.2f} dB" in text, text
    assert f"{want_slope:+.1f} dB/dec" in text, (text, want_slope)

    # clicking again clears it, so the reference cannot be stranded
    _drive(fl, 3e6, click=True)
    assert cur.ref is None and not cur._rline.get_visible()
    fl.deleteLater()


def test_the_cursor_yields_to_the_toolbar(app):
    """While zoom is armed the drag belongs to the rubber band.  A cursor that
    also tracked it would repaint over the selection every mouse move.
    """
    fl, _ar = _pn_figlist()
    cur, _ = _drive(fl, 1e6)
    assert cur._text.get_visible()
    cur._text.set_visible(False)
    fl.toolbars()[0].zoom()                      # arm zoom-to-rect
    _drive(fl, 1e4)
    assert not cur._text.get_visible(), "the cursor drew while zoom was armed"
    fl.toolbars()[0].zoom()
    fl.deleteLater()


def test_a_pie_gets_no_cursor_and_the_stack_still_works(app):
    """A wedge has no coordinate system.  The workbench stacks the breakdown
    and its pie in one FigList, so this is the real arrangement, not a
    contrived one.
    """
    from pllsim import presets
    from pllsim.guiqt.widgets import FigList
    from pllsim.plotting import plot_ipn_pie, plot_pn_breakdown
    ar = presets.cppll_19p2m_4p8g().analyze()
    fl = FigList()
    fl.set_figs([plot_pn_breakdown(ar, None), plot_ipn_pie(ar)])
    assert len(fl.canvases()) == 2
    assert len(fl.cursors()) == 1, "the pie was given a cursor"
    fl.deleteLater()


def test_the_cursor_survives_the_function_that_made_it(app):
    """It is referenced only by its own matplotlib callbacks otherwise, and
    those are weak: the cursor would be collected the moment set_figs moved
    on, and then silently never fire again.
    """
    import gc
    fl, _ar = _pn_figlist()
    gc.collect()
    cur, _ = _drive(fl, 1e6)
    assert cur._text.get_text(), "the cursor was collected before it drew"
    fl.deleteLater()
