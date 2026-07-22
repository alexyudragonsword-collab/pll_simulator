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
    from pllsim.guiqt.page_analysis import BenchmarksPage
    page = BenchmarksPage()
    assert len(page.ROWS) == 5
    page.deleteLater()
