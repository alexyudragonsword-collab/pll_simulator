"""The cursor's coordinate map and traces, checked against rendered pixels.

A cursor is a promise that the number under the crosshair is the number on
the curve.  Two things can break that promise quietly:

* the pixel-to-data map can be off, so the readout is a real value at the
  wrong abscissa -- which looks entirely plausible;
* the traces can come from somewhere other than the artist, so the cursor
  and the drawn line disagree by a little.

Both are checked here by rendering a marker at a known data point and
finding it in the PNG, rather than by comparing formulas with themselves.
"""
import io

import matplotlib
import numpy as np
import pytest
from PIL import Image

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from pllsim import presets  # noqa: E402
from pllsim.plotting import (  # noqa: E402
    figure_cursor_data,
    plot_ipn_pie,
    plot_pn_breakdown,
)

DPI = 130
MARK = "#ff00ff"          # a colour none of the plots use


def _marker_px(fig, dx, dy):
    """Render a marker at a data point and return its centroid in PNG pixels."""
    fig.axes[0].plot([dx], [dy], marker="o", ms=6, color=MARK, zorder=99)
    buf = io.BytesIO()
    # no bbox_inches="tight": that is what the map assumes, and the reason
    fig.savefig(buf, format="png", dpi=DPI)
    a = np.asarray(Image.open(buf).convert("RGB"))
    ys, xs = np.where((a[:, :, 0] > 200) & (a[:, :, 1] < 80) & (a[:, :, 2] > 200))
    assert xs.size, "the marker did not render -- the check would pass on nothing"
    return xs.mean(), ys.mean(), a.shape[1], a.shape[0]


def _predict_px(entry, dx, dy):
    """Where the cursor map says (dx, dy) lands."""
    x0, y0, x1, y1 = entry["box"]
    fx = np.log10 if entry["xlog"] else (lambda v: v)
    fy = np.log10 if entry["ylog"] else (lambda v: v)
    l0, l1 = fx(entry["xlim"][0]), fx(entry["xlim"][1])
    m0, m1 = fy(entry["ylim"][0]), fy(entry["ylim"][1])
    return (x0 + (fx(dx) - l0) / (l1 - l0) * (x1 - x0),
            y1 - (fy(dy) - m0) / (m1 - m0) * (y1 - y0))


def test_the_map_lands_on_the_pixel_the_figure_actually_drew():
    """The load-bearing property, on the log-x axis where it matters most.

    Mutation: keep bbox_inches="tight" in the save above and this goes red by
    about 3 px of x -- which on this axis is a visible slice of a decade.
    """
    ar = presets.cppll_19p2m_4p8g().analyze()
    fig = plot_pn_breakdown(ar, None)
    entry = figure_cursor_data(fig, DPI)["axes"][0]
    assert entry["xlog"] and not entry["ylog"]
    for dx, dy in ((1e3, -90.0), (1e6, -100.0), (5e7, -150.0)):
        px, py = _predict_px(entry, dx, dy)
        ax_, ay, _w, _h = _marker_px(plot_pn_breakdown(ar, None), dx, dy)
        assert abs(px - ax_) < 1.0 and abs(py - ay) < 1.0, (dx, dy, px, ax_, py, ay)
    plt.close("all")


def test_the_map_holds_on_a_linear_axis_too():
    fig, ax = plt.subplots(figsize=(6, 4))
    ax.plot([0.0, 10.0], [-5.0, 5.0])
    ax.set_xlim(0, 10)
    ax.set_ylim(-5, 5)
    fig.tight_layout()
    entry = figure_cursor_data(fig, DPI)["axes"][0]
    assert not entry["xlog"] and not entry["ylog"]
    px, py = _predict_px(entry, 7.5, 2.5)
    ax_, ay, _w, _h = _marker_px(fig, 7.5, 2.5)
    assert abs(px - ax_) < 1.0 and abs(py - ay) < 1.0


def test_the_traces_are_the_artists_own_numbers():
    """Read from the Line2D, not from the model a second time.

    Editing the drawn line and watching the extract follow is the only way to
    tell the two apart -- a re-computation would return the original curve and
    the cursor would disagree with what the reader is pointing at.
    """
    ar = presets.cppll_19p2m_4p8g().analyze()
    fig = plot_pn_breakdown(ar, None)
    line = fig.axes[0].get_lines()[0]
    y = np.asarray(line.get_ydata(), float).copy()
    line.set_ydata(y - 12.5)
    got = figure_cursor_data(fig, DPI)["axes"][0]["traces"][0]["y"]
    assert got[0] == pytest.approx(y[0] - 12.5, abs=0.05), (got[0], y[0])
    plt.close(fig)


def test_span_markers_are_not_mistaken_for_curves():
    """`axvline` is a Line2D too.  What separates it from a trace is its
    transform, not its label -- filtering on the label dropped the measured
    periodogram, which is the whole point of the spur plot and carries no
    legend entry.
    """
    fig, ax = plt.subplots(figsize=(6, 4))
    ax.plot([1.0, 2.0, 3.0], [1.0, 2.0, 3.0])          # unlabelled, but data
    ax.axvline(2.0)
    ax.axhline(2.0)
    fig.tight_layout()
    traces = figure_cursor_data(fig, DPI)["axes"][0]["traces"]
    assert len(traces) == 1, [t["label"] for t in traces]
    assert traces[0]["y"] == [1.0, 2.0, 3.0]


def test_a_uniform_grid_rebuilds_exactly_and_a_near_uniform_one_is_sent_whole():
    """start/step/n is a lossless statement about an arithmetic grid and a
    lie about anything else."""
    fig, ax = plt.subplots(figsize=(6, 4))
    x = np.arange(4000) * 2560.0 + 1280.0
    ax.plot(x, np.zeros_like(x))
    fig.tight_layout()
    t = figure_cursor_data(fig, DPI)["axes"][0]
    g = t["x_uniform"]
    rebuilt = np.arange(g["n"]) * g["step"] + g["start"]
    assert np.array_equal(rebuilt, x), np.abs(rebuilt - x).max()

    # one point nudged: no longer arithmetic, so it must ship verbatim
    plt.close(fig)
    fig, ax = plt.subplots(figsize=(6, 4))
    x2 = x.copy()
    x2[1000] += 300.0
    ax.plot(x2, np.zeros_like(x2))
    fig.tight_layout()
    t2 = figure_cursor_data(fig, DPI)["axes"][0]
    assert "x_uniform" not in t2, "a bent grid was encoded as arithmetic"
    assert len(t2["x"]) == x2.size
    plt.close("all")


def test_a_log_spaced_grid_is_never_called_arithmetic():
    """The dangerous mis-encoding, and the one a real plot would hit: the
    phase-noise abscissa is geometric, and describing it with start/step/n
    would put every readout at the wrong frequency while looking fine.
    """
    ar = presets.cppll_19p2m_4p8g().analyze()
    entry = figure_cursor_data(plot_pn_breakdown(ar, None), DPI)["axes"][0]
    assert "x_uniform" not in entry, "a log grid was encoded as arithmetic"
    assert len(entry["x"]) == ar.f.size
    # and it really is geometric, so the test is not passing on a linear grid
    r = np.diff(np.log10(np.asarray(entry["x"], float)))
    assert r.std() / r.mean() < 1e-3, "this grid is not log-spaced after all"
    plt.close("all")


def test_curves_sharing_a_grid_send_it_once():
    ar = presets.cppll_19p2m_4p8g().analyze()
    entry = figure_cursor_data(plot_pn_breakdown(ar, None), DPI)["axes"][0]
    assert len(entry["traces"]) == len(ar.pn_breakdown)
    assert "x" in entry or "x_uniform" in entry
    for t in entry["traces"]:
        assert "x" not in t and "x_uniform" not in t
    plt.close("all")


def test_a_pie_offers_no_cursor():
    """A wedge has no coordinate system; inventing one would put a readout on
    a plot where every number it showed would be meaningless."""
    ar = presets.cppll_19p2m_4p8g().analyze()
    assert figure_cursor_data(plot_ipn_pie(ar), DPI)["axes"] == []
    plt.close("all")


def test_an_over_long_trace_is_refused_by_name_rather_than_thinned():
    """Decimating would make the cursor read numbers the drawn curve does not
    show.  Saying "no cursor here, and here is which curve" is the honest
    failure; the caller can then say so in the UI.
    """
    fig, ax = plt.subplots(figsize=(6, 4))
    n = 20_000
    ax.plot(np.arange(n), np.zeros(n), label="freq error [MHz]")
    fig.tight_layout()
    cd = figure_cursor_data(fig, DPI, max_points=8192)
    assert cd["axes"] == []
    assert cd["dropped"] == ["freq error [MHz]"]
    plt.close("all")
