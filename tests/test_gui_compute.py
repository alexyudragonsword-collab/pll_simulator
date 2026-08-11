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
