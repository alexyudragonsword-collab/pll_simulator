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
                 f"({ar.int_band[0]:.0f} Hz…{ar.int_band[1] / 1e6:.0f} MHz)")
    fig.tight_layout()
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
