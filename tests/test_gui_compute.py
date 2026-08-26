"""Every Streamlit page's COMPUTE path, not just its render path.

test_gui_smoke covers "the page imports and lays out".  That passes for a page
whose button raises the moment it is pressed, which is the failure the ILCM
time-domain bug actually was: both GUIs rendered fine and only the button was
broken.  These press the buttons.
"""
from pathlib import Path

import pytest

st = pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402

from pllsim.webgui import package_dir  # noqa: E402

GUI = package_dir()


def _run(page: str, timeout: float = 300, minimal: bool = True) -> AppTest:
    at = AppTest.from_file(str(Path(GUI) / "pages" / page), default_timeout=timeout)
    at.run()
    assert not at.exception, f"{page} failed to render: {at.exception}"
    return _turn_workload_down(at) if minimal else at


def _turn_workload_down(at: AppTest) -> AppTest:
    """Set every numeric control to its minimum before pressing anything.

    These tests ask "does the button work", not "is the answer accurate", and
    the pages default to production run lengths -- 40 chips of 150k cycles on
    the Monte Carlo page alone.  Left at the defaults this file costs three
    minutes per CI job, twice per push, out of a metered budget.  Minimum
    settings exercise exactly the same code path.
    """
    for _ in range(len(at.number_input)):
        changed = False
        for ni in at.number_input:
            lo = getattr(ni, "min", None)
            if lo is not None and ni.value != lo:
                at = ni.set_value(lo).run()
                changed = True
                break
        if not changed:
            break
    return at


def _press(at: AppTest, label_part: str) -> AppTest:
    for b in at.button:
        if label_part.lower() in str(b.label).lower():
            out = b.click().run()
            assert not out.exception, f"'{b.label}' raised: {out.exception}"
            return out
    raise AssertionError(f"no button matching {label_part!r}; "
                         f"have {[str(b.label) for b in at.button]}")


def _press_key(at: AppTest, key: str) -> AppTest:
    """Press by widget key, for pages whose labels are localized.

    The Spurs page defaults to Chinese, so matching on English text there
    would silently skip the very buttons this file exists to exercise -- but
    pressing by *position* is worse: adding the reference-spur button shifted
    every later index, and the channel-sweep test went on passing while
    pressing something else entirely.  A key is stable against both.
    """
    found = [b for b in at.button if b.key == key]
    assert found, f"no button keyed {key!r}; have {[b.key for b in at.button]}"
    out = found[0].click().run()
    assert not out.exception, f"'{found[0].label}' raised: {out.exception}"
    return out


def _produced_output(at: AppTest) -> bool:
    """Something computed landed on the page.

    AppTest exposes no accessor for st.pyplot, so a chart-only page is checked
    through the text that accompanies it rather than the figure itself.
    """
    return bool(at.dataframe or at.metric or at.table or at.caption
                or at.markdown or at.text or at.success or at.info)


def test_workbench_simulate_runs():
    """The button that was broken for ILCM/MDLL for three releases."""
    at = _run("1_Workbench.py")
    out = _press(at, "Run simulate")
    assert out.metric or out.dataframe


def test_workbench_analyze_shows_the_ipn_breakdown():
    at = _run("1_Workbench.py")
    out = _press(at, "Run analyze")
    rows = [r for df in out.dataframe for r in _rows_of(df)]
    shares = [r["share [%]"] for r in rows if "share [%]" in r]
    assert shares, f"no IPN breakdown table: {rows[:2]}"
    assert sum(shares) == pytest.approx(100.0, abs=0.3)


@pytest.mark.parametrize("arch", ["ilcm_250m_12g", "mdll_150m_2p4g"])
def test_workbench_simulates_the_injection_locked_pair(arch):
    """These name their start-offset keyword differently from the rest, which
    is exactly how they came to be un-runnable from both GUIs."""
    at = _run("1_Workbench.py")
    at.selectbox[0].select(arch).run()
    out = _press(at, "Run simulate")
    assert not out.exception


def test_synthesis_solves_every_family():
    at = _run("2_Synthesis.py")
    for key in ("cp", "ss", "sp"):
        found = [b for b in at.button if b.key == key]
        assert found, f"no synthesis button for {key}"
        out = found[0].click().run()
        assert not out.exception, f"{key}: {out.exception}"


def test_spurs_predicts_and_simulates():
    at = _run("4_Spurs.py")
    a = _press_key(at, "predict")       # via the analyze() NTF
    assert a.dataframe or a.table
    b = _press_key(a, "measure")        # simulate and plot
    assert _produced_output(b)


def test_spurs_measured_spectrum_survives_an_adpll_preset():
    """This page's dropdown carries two ADPLL fractional presets, whose
    simulate() takes no fine_oversample.  The measured spectrum now offers
    an M box, so it has to route through simulate_kwargs or pressing the
    button on either preset raises TypeError.
    """
    at = _run("4_Spurs.py")
    names = list(at.selectbox[0].options)
    adpll = next(n for n in names if "adpll" in n)
    at = at.selectbox[0].select(adpll).run()
    # by key, never by index: a widget inserted above would silently
    # re-point an index-based lookup at the wrong box
    at.number_input(key="m_meas").set_value(128).run()
    out = _press_key(at, "measure")
    assert not out.exception, out.exception
    assert _produced_output(out)


def test_spurs_page_compares_the_reference_spur():
    """The reference spur needs an intra-period record, so this page could
    not show it at all until the M control existed."""
    at = _run("4_Spurs.py")
    names = list(at.selectbox[0].options)
    cp = next(n for n in names if n.startswith("cppll"))
    at = at.selectbox[0].select(cp).run()
    out = _press_key(at, "ref_spur")
    rows = [r for df in out.dataframe for r in _rows_of(df)]
    assert rows, "no comparison table"
    hit = [r for r in rows if "analytic [dBc]" in r and r["analytic [dBc]"] != "-"]
    assert hit, f"the charge-pump preset must have an analytic value: {rows}"


def _rows_of(df):
    v = df.value
    try:
        return v.to_dict("records")
    except AttributeError:
        return list(v)


def test_spurs_channel_sweep_follows_the_selected_preset():
    """The Streamlit sweep used to ignore the selection and always scan the
    first fractional preset, while the Qt one honoured it."""
    at = _run("4_Spurs.py")
    names = list(at.selectbox[0].options)
    assert len(names) > 1
    at = at.selectbox[0].select(names[-1]).run()
    out = _press_key(at, "sweep")
    blob = " ".join(str(m.value) for m in out.markdown) \
        + " ".join(str(c.value) for c in out.caption) \
        + " ".join(str(h.value) for h in out.subheader)
    # naming the swept preset is the assertion; "or out.dataframe" used to be
    # an escape hatch wide enough that pressing the wrong button still passed
    assert names[-1] in blob, \
        "the sweep must name the preset that is selected"


def test_modulation_runs_and_reports_evm():
    at = _run("6_Modulation.py")
    out = _press(at, "run")
    assert out.metric, "two-point modulation should report EVM"
    assert _produced_output(out)


def test_hop_settling_runs_both_buttons():
    at = _run("7_HopSettling.py")
    a = _press(at, "run hop")
    assert _produced_output(a)
    b = _press(a, "run statistics")
    assert _produced_output(b)


def test_drift_tracking_runs():
    at = _run("8_DriftTracking.py")
    out = _press(at, "run ramp")
    assert _produced_output(out)


def test_benchmarks_page_plots_an_ipn_pie():
    at = _run("11_Benchmarks.py")
    out = _press_key(at, "pie")
    rows = [r for df in out.dataframe for r in _rows_of(df)]
    shares = [r["share [%]"] for r in rows if "share [%]" in r]
    assert shares, f"no breakdown table: {rows[:2]}"
    assert sum(shares) == pytest.approx(100.0, abs=0.3)   # rounded to 0.1


def test_monte_carlo_runs():
    at = _run("9_MonteCarlo.py")
    out = _press(at, "monte carlo")
    assert _produced_output(out)


def test_export_writes_files():
    at = _run("10_Export.py")
    for ms in at.multiselect:
        if ms.options:
            ms.select(ms.options[0]).run()
            break
    out = _press(at, "export")
    assert not out.exception


def test_benchmarks_rerun_uses_presets_not_the_test_suite():
    """The packaged exe ships no tests/ directory, so this button used to be
    a guaranteed ModuleNotFoundError for anyone running the build."""
    at = _run("11_Benchmarks.py")
    out = _press(at, "re-run")
    assert out.dataframe


def test_fit_page_fits_a_synthetic_measurement(tmp_path):
    """Fit needs an upload, which AppTest cannot drive; check instead that
    the page's own model round-trips through the library it calls."""
    import numpy as np

    from pllsim.core.jitter import ldbc_from_sphi
    from pllsim.core.noise import LeesonOscillator
    from pllsim.fit import fit_leeson
    truth = LeesonOscillator.from_spot("vco", -120.0, 1e6, f_1f3=2e5,
                                       floor_dbchz=-158.0)
    f = np.logspace(3, 8, 200)
    got = fit_leeson(f, ldbc_from_sphi(truth.psd(f)))
    assert got is not None


def test_pn_units_page_converts_and_shows_both_conventions():
    """The page has no button: it converts on render, so a broken compute
    path shows up as an exception or as an empty metric row, not as a button
    that does nothing."""
    from pllsim.core.jitter import HALF_POWER_DB, convert_phase_noise

    at = _run("12_PNUnits.py", timeout=60)
    want = convert_phase_noise(10e9, deg=0.5)          # the page defaults
    shown = " ".join(m.value for m in at.metric)
    assert shown, "the page rendered no metrics"
    assert f"{want.jitter_fs:.6g}" in shown, shown
    assert f"{want.ipn_dbc_dsb:.4f}" in shown, shown
    # both conventions, side by side -- the page's entire reason to exist
    assert f"{want.ipn_dbc_ssb:.4f}" in shown, shown
    assert want.ipn_dbc_dsb - want.ipn_dbc_ssb == pytest.approx(HALF_POWER_DB)


def test_pn_units_page_switches_which_quantity_is_supplied():
    from pllsim.core.jitter import convert_phase_noise

    at = _run("12_PNUnits.py", timeout=60)
    at.selectbox[0].set_value("ipn_dbc_dsb").run()
    at.text_input[-1].set_value("-40").run()
    assert not at.exception, at.exception
    want = convert_phase_noise(10e9, ipn_dbc_dsb=-40.0)
    shown = " ".join(m.value for m in at.metric)
    assert f"{want.deg:.6g}" in shown, shown
    assert f"{want.jitter_fs:.6g}" in shown, shown


def test_pn_units_page_reports_bad_input_instead_of_crashing():
    at = _run("12_PNUnits.py", timeout=60)
    at.text_input[0].set_value("0").run()              # f0 = 0
    assert not at.exception, at.exception
    assert at.error, "a zero carrier produced no visible error"


def test_fom_page_computes_both_figures():
    """No button on this page either: it computes on render."""
    at = _run("13_FoM.py", timeout=60)
    shown = " ".join(m.value for m in at.metric)
    assert shown, "the page rendered no metrics"
    # defaults are 100 fs / 10 mW and -120 dBc/Hz at 1 MHz off 10 GHz / 10 mW
    assert "-250.00" in shown, shown          # 10*log10((1e-13)^2 * 10)
    assert "-190.00" in shown, shown


def test_fom_page_warns_that_l_is_single_sideband():
    """This package stores S_phi; the formula wants L. Saying nothing here
    would hand the reader a silent 3 dB."""
    at = _run("13_FoM.py", timeout=60)
    warned = " ".join(w.value for w in at.warning)
    assert "3.0103" in warned, warned


def test_fom_page_reports_bad_power_instead_of_crashing():
    at = _run("13_FoM.py", timeout=60)
    at.text_input[1].set_value("0").run()      # PLL power
    assert not at.exception, at.exception
    assert at.error, "zero power produced no visible error"
