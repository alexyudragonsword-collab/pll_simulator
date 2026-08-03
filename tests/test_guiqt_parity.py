"""Qt/Streamlit feature parity, and the selector -> workbench handoff.

The two GUIs are meant to expose the same library.  Where they drifted, the
Qt side was the one missing things -- a language toggle, the Monte Carlo
calibration-yield metric, the benchmarks re-run button, zip export -- and
nothing failed when they did, because nothing compared them.
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


@pytest.fixture(autouse=True)
def _english():
    """Every test starts in English and leaves the module in English."""
    from pllsim.guiqt import i18n
    i18n.set_lang("en")
    yield
    i18n.set_lang("en")


# --------------------------------------------------------------------- i18n
def test_tr_sets_the_current_language_and_registers(app):
    from pllsim.guiqt.i18n import registered_count, set_lang, tr
    before = registered_count()
    lab = QtWidgets.QLabel()
    tr(lab, "参考频率", "reference frequency")
    assert lab.text() == "reference frequency"
    assert registered_count() == before + 1
    set_lang("zh")
    assert lab.text() == "参考频率"
    set_lang("en")
    assert lab.text() == "reference frequency"


def test_tr_returns_the_widget_for_inline_use(app):
    from pllsim.guiqt.i18n import tr
    b = tr(QtWidgets.QPushButton(), "运行", "Run")
    assert isinstance(b, QtWidgets.QPushButton) and b.text() == "Run"


def test_unknown_language_is_refused(app):
    from pllsim.guiqt.i18n import set_lang
    with pytest.raises(ValueError, match="zh.*en"):
        set_lang("fr")


def test_a_widget_without_a_text_setter_is_refused(app):
    from pllsim.guiqt.i18n import tr
    with pytest.raises(TypeError, match="text setter"):
        tr(object(), "甲", "a")


def test_dead_widgets_are_dropped_not_written_to(app):
    """Pages are torn down; the registry must not keep them alive or push
    text into a deleted C++ object."""
    import gc

    from pllsim.guiqt.i18n import registered_count, set_lang, tr
    lab = QtWidgets.QLabel()
    tr(lab, "甲", "a")
    n = registered_count()
    del lab
    gc.collect()
    set_lang("zh")
    assert registered_count() < n


def test_every_page_translates_its_own_labels(app):
    """Switching language must change visible text on every page, not just
    the ones that happened to get wrapped."""
    from pllsim.guiqt.app import PAGES
    from pllsim.guiqt.i18n import set_lang

    def texts(page):
        return [w.text() for w in page.findChildren(QtWidgets.QLabel)
                if w.text()] + \
               [b.text() for b in page.findChildren(QtWidgets.QPushButton)
                if b.text()]

    for cls in PAGES:
        page = cls()
        en = texts(page)
        set_lang("zh")
        zh = texts(page)
        set_lang("en")
        assert en != zh, f"{cls.__name__} has no translated label"
        assert texts(page) == en, f"{cls.__name__} did not switch back"
        page.deleteLater()


def test_the_sidebar_follows_the_language(app):
    from pllsim.guiqt.app import MainWindow
    from pllsim.guiqt.i18n import set_lang
    win = MainWindow()
    en = [win.nav.item(i).text() for i in range(win.nav.count())]
    set_lang("zh")
    zh = [win.nav.item(i).text() for i in range(win.nav.count())]
    assert en != zh
    assert len(en) == len(zh) == win.stack.count()
    win.deleteLater()


def test_the_language_box_changes_the_language(app):
    from pllsim.guiqt import i18n
    from pllsim.guiqt.app import MainWindow
    win = MainWindow()
    win.lang_box.setCurrentIndex(1)
    assert i18n.lang() == "zh"
    win.lang_box.setCurrentIndex(0)
    assert i18n.lang() == "en"
    win.deleteLater()


# ------------------------------------------------ Monte Carlo cal yield
def test_monte_carlo_reports_a_calibration_yield(app):
    """The web GUI has always shown it; a chip can pass the jitter limit on
    a channel that barely exercises the DTC and still ship miscalibrated."""
    import numpy as np

    from pllsim.guiqt.page_tools import MonteCarloPage
    from pllsim.montecarlo import MCResult
    page = MonteCarloPage()
    res = MCResult(
        metrics={"cal_dtc_gain_final": np.array([1.0 / 1.10, 1.0 / 1.30])},
        params={"dtc_gain_err": np.array([0.10, 0.10])},
        n_runs=2)
    # first chip's calibration landed, second did not
    assert page._cal_yield(res, 0.02) == pytest.approx(0.5)
    page.deleteLater()


def test_calibration_yield_is_none_without_a_trace(app):
    from pllsim.guiqt.page_tools import MonteCarloPage
    from pllsim.montecarlo import MCResult
    page = MonteCarloPage()
    assert page._cal_yield(MCResult(metrics={}, params={}, n_runs=0), 0.02) is None
    page.deleteLater()


# ------------------------------------------------------------- export zip
def test_export_page_offers_both_a_folder_and_a_zip(app):
    from pllsim.guiqt.page_tools import ExportPage
    page = ExportPage()
    assert page.btn.text() and page.btn_zip.text()
    page.deleteLater()


def test_export_writes_a_readable_zip(app, tmp_path, monkeypatch):
    """A fractional preset, so all three layers are present.

    An integer-N CPPLL legitimately emits no RTL -- it has no MASH, DLF or
    LMS to generate -- so picking one would test the zip against the wrong
    expectation.
    """
    from PySide6.QtWidgets import QFileDialog

    from pllsim import presets
    from pllsim.guiqt.page_tools import ExportPage
    page = ExportPage()
    page.list.setCurrentRow(list(presets.ALL_PRESETS).index("cppll_frac_38p4m_6g"))
    out = tmp_path / "bundle.zip"
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: (str(out), "")))
    page.n_golden.setText("64")
    captured = {}
    monkeypatch.setattr(page, "run_async",
                        lambda fn, done, *b: captured.setdefault("logs", fn()))
    page._go_zip()
    import zipfile
    assert out.exists()
    with zipfile.ZipFile(out) as zf:
        names = zf.namelist()
        assert zf.testzip() is None
    assert any(n.endswith(".vams") for n in names)     # RNM + electrical AMS
    assert any(n.endswith(".v") for n in names)        # bit-true RTL
    assert any(n.endswith("README.md") for n in names)
    assert captured["logs"]
    page.deleteLater()


# ------------------------------------------------------- benchmarks re-run
def test_benchmarks_page_can_re_run_the_linear_models(app):
    from pllsim import presets
    from pllsim.guiqt.page_analysis import BenchmarksPage
    page = BenchmarksPage()
    assert page.btn.text()
    rows = [{"benchmark": lab, "published [fs]": pub,
             "linear model [fs]": round(
                 float(getattr(presets, mk)().analyze().jitter_fs), 1)}
            for lab, mk, pub in page.LIVE]
    assert len(rows) == 4
    assert all(r["linear model [fs]"] > 0 for r in rows)
    page.deleteLater()


def test_benchmark_rerun_targets_presets_that_exist(app):
    """It used to import from tests/, which a packaged build does not ship."""
    from pllsim import presets
    from pllsim.guiqt.page_analysis import BenchmarksPage
    for _, mk, _ in BenchmarksPage.LIVE:
        assert hasattr(presets, mk), mk


# --------------------------------------------- selector -> workbench handoff
def test_workbench_accepts_a_handed_over_config(app):
    from pllsim import presets
    from pllsim.guiqt.page_workbench import WorkbenchPage
    page = WorkbenchPage()
    pll = presets.spll_100m_8g()
    pll.cfg.fout = 8.4e9                      # not any stock preset's value
    page.load_config(pll, "from selector: SPLL")
    assert "from selector" in page.info.text()
    assert page._pll().cfg.fout == pytest.approx(8.4e9), \
        "the workbench must run the handed-over config, not the dropdown"
    page.deleteLater()


def test_choosing_a_preset_drops_the_handoff(app):
    from pllsim import presets
    from pllsim.guiqt.page_workbench import WorkbenchPage
    page = WorkbenchPage()
    pll = presets.spll_100m_8g()
    pll.cfg.fout = 8.4e9
    page.load_config(pll, "x")
    page.load_preset("cppll_19p2m_4p8g")
    got = page._pll()
    assert got.cfg.fout == pytest.approx(presets.cppll_19p2m_4p8g().cfg.fout)
    page.deleteLater()


def test_main_window_routes_a_preset_to_the_workbench(app):
    from pllsim.guiqt.app import MainWindow
    win = MainWindow()
    win.nav.setCurrentRow(3)
    win.open_in_workbench("mdll_150m_2p4g")
    assert win.nav.currentRow() == 0
    assert win.pages[0].preset.currentText() == "mdll_150m_2p4g"
    win.deleteLater()


def test_selector_offers_a_handoff_button_per_feasible_candidate(app):
    from pllsim.guiqt.app import MainWindow
    from pllsim.selector import Requirement, select
    win = MainWindow()
    page = win.pages[2]
    rep = select(Requirement(fref=100e6, fout=8e9, jitter_fs_max=400))
    feasible = [c for c in rep.candidates if c.feasible and c.pll is not None]
    assert feasible, "this requirement should have candidates"
    page._add_handoff(rep)
    host = page._body.itemAt(page._body.count() - 1).widget()
    labels = {b.text() for b in host.findChildren(QtWidgets.QPushButton)}
    assert labels == {c.arch for c in feasible}
    win.deleteLater()


def test_a_standalone_page_adds_no_handoff(app):
    """Pages are built directly by tests, so nothing may assume a window."""
    from pllsim.guiqt.page_design import SelectorPage
    from pllsim.selector import Requirement, select
    page = SelectorPage()
    assert page.main_window() is None
    page._add_handoff(select(Requirement(fref=100e6, fout=8e9,
                                         jitter_fs_max=400)))
    assert page._body.count() == 0
    page.deleteLater()


def test_the_handoff_opens_the_candidate_not_a_preset(app):
    from pllsim.guiqt.app import MainWindow
    from pllsim.guiqt.page_design import SelectorPage
    from pllsim.selector import Requirement, select
    win = MainWindow()
    rep = select(Requirement(fref=100e6, fout=8e9, jitter_fs_max=400))
    cand = next(c for c in sorted(rep.candidates, key=lambda c: c.key)
                if c.feasible and c.pll is not None)
    SelectorPage._open(win, cand)
    assert win.nav.currentRow() == 0
    wb = win.pages[0]
    assert wb._pll().cfg.fout == pytest.approx(8e9), \
        "the requirement's fout, not the dropdown preset's"
    win.deleteLater()


# ------------------------------------------------------- the drift itself
def test_both_guis_expose_the_same_page_set(app):
    """What was never checked, and so never failed while the two drifted.

    Names differ (the Streamlit pages are files, the Qt pages are classes),
    so the comparison is on the feature each one covers.
    """
    from pllsim.guiqt.app import PAGES
    from pllsim.webgui import package_dir
    web = {p.stem.split("_", 1)[1].lower()
           for p in (package_dir() / "pages").glob("*.py")}
    qt = {c.title.lower() for c in PAGES}
    alias = {"workbench": "workbench", "synthesis": "loop synthesis",
             "selector": "architecture selector", "spurs": "spur prediction",
             "fit": "measured-pn fitting", "modulation": "two-point modulation",
             "hopsettling": "hop settling", "drifttracking": "drift tracking",
             "montecarlo": "monte carlo", "export": "vams export",
             "benchmarks": "benchmarks"}
    assert web == set(alias), f"a Streamlit page has no entry here: {web}"
    missing = {alias[w] for w in web} - qt
    assert not missing, f"the Qt GUI is missing: {missing}"
