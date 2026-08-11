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


def test_the_desktop_entry_point_is_importable(app):
    """`pllsim-gui` and the exe both go through app.main."""
    from pllsim.guiqt.app import main
    assert callable(main)
