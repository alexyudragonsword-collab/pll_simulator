"""Plot helpers consuming AnalysisResult / SimResult."""
from __future__ import annotations

import math

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from .core.jitter import ldbc_from_sphi
from .core.results import AnalysisResult, SimResult


def plot_pn_breakdown(ar: AnalysisResult, sim: SimResult | None = None,
                      save: str | None = None, fmax: float | None = None):
    """Per-source L(f) breakdown; overlays the time-domain periodogram if given."""
    fig, ax = plt.subplots(figsize=(9, 6))
    order = sorted((k for k in ar.pn_breakdown if k != "total"),
                   key=lambda k: -np.max(ar.pn_breakdown[k]))
    for k in order:
        ax.semilogx(ar.f, ldbc_from_sphi(ar.pn_breakdown[k]), lw=1.0, label=k)
    ax.semilogx(ar.f, ldbc_from_sphi(ar.pn_breakdown["total"]), "k", lw=2.2,
                label="total (linear model)")
    if sim is not None and sim.f_psd is not None:
        ax.semilogx(sim.f_psd, ldbc_from_sphi(sim.s_phi_psd), color="0.55",
                    alpha=0.6, lw=0.8, label="time-domain sim")
    ax.set_xlim(ar.f[0], fmax or ar.f[-1])
    ax.set_ylim(-180, None)
    ax.set_xlabel("offset frequency [Hz]")
    ax.set_ylabel("L(f) [dBc/Hz]")
    ax.set_title(f"Phase noise @ {ar.f0 / 1e9:.4g} GHz — "
                 f"σ = {ar.jitter_fs:.0f} fs ({ar.int_band[0]:.0f} Hz…"
                 f"{ar.int_band[1] / 1e6:.0f} MHz)")
    ax.grid(True, which="both", alpha=0.3)
    ax.legend(fontsize=8, loc="lower left")
    fig.tight_layout()
    if save:
        fig.savefig(save, dpi=140)
    return fig


def plot_ipn_pie(ar: AnalysisResult, save: str | None = None,
                 title: str | None = None, min_share: float = 0.015):
    """Where the integrated phase noise actually comes from, as a pie.

    The slices are shares of integrated phase *power*, which is the quantity
    that adds: the sources are uncorrelated and `pn_breakdown["total"]` is
    their sum, so the shares total 1 exactly (verified on every benchmark
    preset).  The curve plot answers "what shape"; this answers "what do I
    fix first", which is a different question and the one a budget review
    starts from.

    Each label carries the source's own RMS jitter as well as its percentage,
    because the two do not rank the same way to the eye: halving the power of
    a 50% contributor buys 1 - 1/sqrt(2) ~ 29% of the total jitter, not 25%.
    Slices below `min_share` are pooled into one "other" wedge, named so that
    a reader can see how much was pooled rather than wondering.
    """
    rows = ar.ipn_shares()
    big = [(k, s, j) for k, s, j in rows if s >= min_share]
    small = [(k, s, j) for k, s, j in rows if s < min_share]
    if small:
        pooled = sum(s for _k, s, _j in small)
        pooled_fs = math.sqrt(sum(j * j for _k, _s, j in small))
        big.append((f"other ({len(small)})", pooled, pooled_fs))

    fig, ax = plt.subplots(figsize=(7.5, 5.5))
    labels = [f"{k}  {s * 100:.1f}%  ({j:.0f} fs)" for k, s, j in big]
    wedges, _texts = ax.pie(
        [s for _k, s, _j in big], startangle=90, counterclock=False,
        wedgeprops={"linewidth": 0.6, "edgecolor": "white"})
    ax.axis("equal")
    ax.legend(wedges, labels, fontsize=8, loc="center left",
              bbox_to_anchor=(1.0, 0.5))
    ax.set_title(title or
                 f"IPN breakdown @ {ar.f0 / 1e9:.4g} GHz — "
                 f"σ = {ar.jitter_fs:.0f} fs, IPN = {ar.ipn_dbc:.1f} dBc "
                 f"({ar.int_band[0]:.0f} Hz…{ar.int_band[1] / 1e6:.0f} MHz)",
                 fontsize=10)
    fig.tight_layout()
    # Centre the title on the *figure*, not on the axes.  The legend is
    # anchored outside the pie, so tight_layout leaves the axes occupying
    # roughly the left 70% -- and a title centred on that ran off the left
    # edge of the canvas whenever the figure was drawn narrower than the
    # 7.5 in it is laid out for.  In the Qt workbench, at a 666 px canvas,
    # it started at x = -77 px and the reader saw "kdown @ 4.8 GHz".
    # Must come after tight_layout, which is what fixes the axes position.
    p = ax.get_position()
    ax.title.set_x((0.5 - p.x0) / p.width)
    if save:
        fig.savefig(save, dpi=140)
    return fig


def plot_transient(sim: SimResult, save: str | None = None, tmax: float | None = None):
    fig, axes = plt.subplots(3, 1, figsize=(9, 8), sharex=True)
    t = sim.t * 1e6
    axes[0].plot(t, (sim.freq_out - sim.f0) / 1e6, lw=0.7)
    axes[0].set_ylabel("freq error [MHz]")
    if sim.lock_time_s is not None:
        axes[0].axvline(sim.lock_time_s * 1e6, color="r", ls="--", lw=0.8,
                        label=f"lock @ {sim.lock_time_s * 1e6:.2f} µs")
        axes[0].legend(fontsize=8)
    axes[1].plot(t, sim.ctrl, lw=0.7)
    axes[1].set_ylabel("ctrl [V or LSB]")
    axes[2].plot(t, sim.phase_err_out, lw=0.7)
    axes[2].set_ylabel("output phase err [rad]")
    axes[2].set_xlabel("time [µs]")
    if tmax:
        axes[2].set_xlim(0, tmax * 1e6)
    for ax in axes:
        ax.grid(alpha=0.3)
    fig.suptitle("Transient")
    fig.tight_layout()
    if save:
        fig.savefig(save, dpi=140)
    return fig


def plot_spur_spectrum(sim: SimResult, save: str | None = None,
                       ar: AnalysisResult | None = None):
    """Periodogram of the settled phase sequence with detected spurs marked."""
    from .core.spectrum import periodogram_psd
    n0 = sim.phase_err_out.size // 4
    f, s = periodogram_psd(sim.phase_err_out[n0:], sim.fs)
    fig, ax = plt.subplots(figsize=(9, 5.5))
    ax.semilogx(f, ldbc_from_sphi(s), lw=0.6, color="0.4")
    if ar is not None:
        ax.semilogx(ar.f, ldbc_from_sphi(ar.pn_breakdown["total"]), "k", lw=1.8,
                    label="linear model")
    for fo, dbc in sim.spurs_fft.items():
        ax.axvline(fo, color="r", ls=":", lw=0.8)
        ax.annotate(f"{dbc:.1f} dBc", (fo, ax.get_ylim()[1] - 8), color="r",
                    fontsize=8, rotation=90, va="top")
    ax.set_xlim(f[1], sim.fs / 2)
    ax.set_xlabel("offset frequency [Hz]")
    ax.set_ylabel("L(f) [dBc/Hz]")
    ax.set_title("Output phase spectrum (spur view)")
    ax.grid(True, which="both", alpha=0.3)
    if ar is not None:
        ax.legend(fontsize=8)
    fig.tight_layout()
    if save:
        fig.savefig(save, dpi=140)
    return fig


#: A trace longer than this is not shipped to a remote cursor.  20 000-point
#: transients are 481 KiB of JSON against a 131 KiB PNG, and decimating them
#: would make the cursor read numbers the drawn curve does not show -- the
#: exact class of quiet disagreement this project keeps paying for.  Better to
#: have no cursor and say so.
#:
#: 8192 rather than something rounder because the measured periodogram of a
#: 20 000-cycle run is 7500 points, and the spur plot is precisely where a
#: cursor earns its keep -- reading the spur level at f_ref off a log axis by
#: eye is how people misread it by several dB.
CURSOR_MAX_POINTS = 8192


def figure_cursor_data(fig, dpi: float,
                       max_points: int = CURSOR_MAX_POINTS) -> dict:
    """Where each data axes lands in a ``savefig(dpi=…)`` PNG, plus its curves.

    This is what lets a cursor exist on a surface that only receives a
    picture.  Two properties make it trustworthy:

    * The curves come out of the **rendered figure** (``Line2D.get_xdata``),
      not out of the model a second time.  A cursor fed from a re-computation
      can disagree with the line the reader is pointing at; one fed from the
      artist cannot.
    * The pixel box is exact only for a *full* save.  ``bbox_inches="tight"``
      crops and rounds to whole pixels, which measured a constant 3.2 px of
      x error — enough to read the wrong decade edge on a log axis.  Callers
      that want this map must save without it; every ``plot_*`` here already
      calls ``tight_layout()``, so the cost is about 1.5% more image.

    Axes with no labelled ``Line2D`` (a pie, for instance) are skipped: a
    cursor needs a coordinate system, and a wedge has none.
    """
    fig.canvas.draw()
    w_px, h_px = (fig.get_size_inches() * dpi)
    out: list[dict] = []
    dropped: list[str] = []
    for ax in fig.axes:
        traces = []
        for i, ln in enumerate(data_lines(ax)):
            x = np.asarray(ln.get_xdata(), dtype=float)
            y = np.asarray(ln.get_ydata(), dtype=float)
            label = ln.get_label()
            if label.startswith("_"):
                # an unlabelled curve is not an internal one: the measured
                # periodogram carries the whole point of the spur plot and
                # has no legend entry.  Name it after the quantity instead.
                label = ax.get_ylabel() or f"trace {i + 1}"
            if x.size > max_points:
                dropped.append(label)
                continue
            ok = np.isfinite(x) & np.isfinite(y)
            traces.append({
                "label": label,
                "color": matplotlib.colors.to_hex(ln.get_color()),
                "_x": x[ok],                     # raw, dropped before return
                # 5 significant digits, not 4: the readouts print two
                # decimals, and at 4 digits a -107.45 dBc/Hz sample arrived as
                # -107.4 and was displayed as "-107.40" -- a claim of
                # precision the transfer had already destroyed.  Five digits
                # cost about 1 byte per sample and make the second decimal
                # true across the whole dBc/Hz range these plots use.
                "y": [float(f"{v:.5g}") for v in y[ok]],
            })
        if not traces:
            continue
        # Two compressions, and both matter: the seven breakdown curves share
        # one frequency grid (repeating it was most of that payload), and a
        # periodogram's grid is arithmetic, so start/step/n says exactly what
        # 7500 numbers say.  They are independent -- the spur plot has two
        # curves on *different* grids, one of which is uniform, so hoisting
        # alone left it larger than the PNG it accompanies.
        #
        # Both decisions are made on the raw abscissa.  Testing them on the
        # rounded one is not a smaller version of the same test: 6 significant
        # digits at 100 MHz is +/-100 Hz of slop against a 1 kHz step, so the
        # periodogram's grid stopped looking arithmetic and shipped as 7500
        # numbers instead of three.
        first = traces[0]["_x"]
        shared = all(t["_x"].shape == first.shape and np.array_equal(t["_x"], first)
                     for t in traces)
        if shared:
            axis_x = _encode_grid(first)
            for t in traces:
                del t["_x"]
        else:
            axis_x = None
            for t in traces:
                t.update(_encode_grid(t.pop("_x")))
        p = ax.get_position()
        entry = {
            # PNG pixels, y measured downwards from the top like an image
            "box": [p.x0 * w_px, (1.0 - p.y1) * h_px,
                    p.x1 * w_px, (1.0 - p.y0) * h_px],
            "xlim": [float(v) for v in ax.get_xlim()],
            "ylim": [float(v) for v in ax.get_ylim()],
            "xlog": ax.get_xscale() == "log",
            "ylog": ax.get_yscale() == "log",
            "xlabel": ax.get_xlabel(),
            "ylabel": ax.get_ylabel(),
            "traces": traces,
        }
        if axis_x is not None:
            entry.update(axis_x)
        out.append(entry)
    return {"w": float(w_px), "h": float(h_px), "axes": out,
            "dropped": sorted(set(dropped))}


def _encode_grid(x: np.ndarray) -> dict:
    """``{"x_uniform": {start, step, n}}`` for an arithmetic abscissa, else
    ``{"x": [...]}``.

    The tolerance is tight on purpose: a grid that is only *nearly* uniform
    has to be sent verbatim, because a cursor that reconstructs the wrong
    abscissa reads a real value at the wrong frequency — which looks entirely
    plausible and is the worst kind of wrong this codebase produces.
    """
    if x.size >= 3:
        step = (x[-1] - x[0]) / (x.size - 1)
        if step > 0:
            rebuilt = np.arange(x.size) * step + x[0]
            if np.allclose(rebuilt, x, rtol=0.0, atol=abs(step) * 1e-9):
                return {"x_uniform": {"start": float(x[0]),
                                      "step": float(step), "n": int(x.size)}}
    return {"x": [float(f"{v:.6g}") for v in x]}


def data_lines(ax):
    """The ``Line2D``s that carry data, not decoration.

    Public because the Qt cursor selects curves with it too: the desktop reads
    the artists directly (no transfer, so no rounding and no length cap) but
    it must agree with the remote surfaces about *which* artists are curves.
    Two selectors would be two answers to that question.

    Not "the label does not start with an underscore": that dropped the
    measured periodogram, which is the main curve of the spur plot and simply
    has no legend entry.  What separates a curve from an ``axvline`` marker is
    the transform — a real trace lives in data coordinates on both axes, a
    span marker uses a blended one.
    """
    return [ln for ln in ax.get_lines()
            if ln.get_visible() and ln.get_transform() is ax.transData]


def plot_cal_convergence(sim: SimResult, save: str | None = None):
    fig, axes = plt.subplots(len(sim.cal_traces), 1, figsize=(9, 2.6 * len(sim.cal_traces)),
                             squeeze=False, sharex=True)
    for ax, (name, tr) in zip(axes[:, 0], sim.cal_traces.items()):
        tr = np.asarray(tr)
        if tr.ndim == 1:
            ax.plot(sim.t[:tr.size] * 1e6, tr, lw=0.9)
        else:
            ax.plot(sim.t[:tr.shape[0]] * 1e6, tr, lw=0.7)
        ax.set_ylabel(name)
        ax.grid(alpha=0.3)
    axes[-1, 0].set_xlabel("time [µs]")
    fig.suptitle("Calibration convergence")
    fig.tight_layout()
    if save:
        fig.savefig(save, dpi=140)
    return fig
