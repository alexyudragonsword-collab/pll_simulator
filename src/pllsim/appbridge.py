"""JSON bridge for embedded hosts: the Android app, or any future WebView shell.

Every function takes and returns *strings* (JSON), because that is the one
type every FFI marshals without surprises -- Chaquopy hands a Kotlin String
across the JNI boundary losslessly, where a dict would arrive as an opaque
PyObject the host must navigate call by call.

This module lives in the package rather than in the Android project for the
same reason both GUIs' shared logic lives in ``guiutil``: code outside
pytest's reach rots.  The two GUIs drifted apart for several releases because
their tests silently skipped; this layer is pure Python, so the plain test
suite drives it with no Android SDK anywhere near.

Two conventions the host side relies on:

- Non-finite floats (an unmeasured lock time, a spur below the noise) become
  JSON ``null``.  ``JSON.parse`` rejects ``NaN``/``Infinity``, so they cannot
  be passed through.
- Plots are PNG bytes, base64-encoded, ready for a ``data:`` URI.  The Agg
  backend is already forced by ``pllsim.plotting`` at import time; the host
  only needs ``MPLCONFIGDIR`` pointed at a writable directory *before* Python
  starts, because matplotlib writes its font cache on first import.
"""
from __future__ import annotations

import base64
import copy
import io
import json
import math
import traceback
from typing import Any, Callable

import matplotlib.pyplot as plt
import numpy as np

from . import presets
from .core.dtcspurs import dtc_spur_table
from .guiutil import (
    GROUP_LABELS,
    apply_overrides,
    arch_kind,
    enumerate_fields,
    fine_oversample_note,
    fine_record_mb,
    fmt_value,
    frac_presets,
    make_pll,
    osc_bank_report,
    ref_spur_comparison,
    simulate_kwargs,
    supports_fine,
)
from .modulation import evm, gmsk_trajectory, prbs, two_point_presets
from .plotting import plot_pn_breakdown, plot_spur_spectrum
from .selector import Requirement, select
from .settling import fll_stability, hop_settling, hop_statistics
from .synth import (
    cppll_kdet,
    design_adpll_dlf,
    design_cp_filter,
    design_spll_filter,
    design_sspll_filter,
    retune_loop,
    sweep_bandwidth,
    sweepable_presets,
)


def _clean(x: Any) -> Any:
    """JSON-safe copy: numpy scalars unboxed, non-finite floats to None."""
    if isinstance(x, dict):
        return {str(k): _clean(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_clean(v) for v in x]
    if isinstance(x, np.generic):
        x = x.item()
    if isinstance(x, float) and not math.isfinite(x):
        return None
    return x


def _png(fig: Any) -> str:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=130, bbox_inches="tight")
    plt.close(fig)
    return base64.b64encode(buf.getvalue()).decode("ascii")


# Feasible candidates from the last select() call, keyed by architecture
# name.  Module state is the handoff channel: the app process is long-lived,
# and every consumer deep-copies before touching the stored instance.
_CANDIDATES: dict[str, Any] = {}


def _build(preset: str = "", overrides: dict[str, str] | None = None,
           candidate: str = "") -> Any:
    """A fresh PLL: from a preset, or from a stored selector candidate.

    The candidate path mirrors the web GUI's selector -> workbench handoff:
    the instance is already sized for the stated requirement, so it crosses
    as-is instead of sending the user to retype fref/fout into the nearest
    preset.
    """
    if candidate:
        base = _CANDIDATES.get(candidate)
        if base is None:
            raise KeyError(f"no stored selector candidate {candidate!r}; "
                           "run select first")
        pll = copy.deepcopy(base)
        if overrides:
            apply_overrides(pll.cfg, overrides)
        return pll
    return make_pll(preset, overrides or {})


def _list_presets() -> list[dict]:
    frac = set(frac_presets())
    sweep = set(sweepable_presets())
    two_pt = set(two_point_presets())
    out = []
    for name, factory in presets.ALL_PRESETS.items():
        cfg = factory().cfg
        out.append({"name": name, "arch": arch_kind(presets.ALL_PRESETS[name]()),
                    "fref_mhz": cfg.fref / 1e6, "fout_ghz": cfg.fout / 1e9,
                    "frac": name in frac, "sweepable": name in sweep,
                    "two_point": name in two_pt})
    return out


def _fields(preset: str = "", overrides: dict[str, str] | None = None,
            candidate: str = "") -> dict:
    pll = _build(preset, overrides, candidate)
    fields = [{
        "path": s.path,
        "value": "" if s.value is None else fmt_value(s.value),
        "kind": s.kind,
        "unit": s.unit,
        "label_zh": s.label_zh,
        "label_en": s.label_en,
        "optional": s.optional,
        "group": s.path.split(".")[0] if "." in s.path else "",
    } for s in enumerate_fields(pll.cfg)]
    return {
        "arch": type(pll).__name__,
        "fref_mhz": pll.cfg.fref / 1e6,
        "fout_ghz": pll.cfg.fout / 1e9,
        "supports_fine": supports_fine(pll),
        "group_labels": {k: {"zh": zh, "en": en}
                         for k, (zh, en) in GROUP_LABELS.items()},
        "fields": fields,
    }


def _analyze(preset: str = "", overrides: dict[str, str] | None = None,
             candidate: str = "") -> dict:
    pll = _build(preset, overrides, candidate)
    ar = pll.analyze()
    return {
        "jitter_fs": ar.jitter_fs,
        "ipn_dbc": ar.ipn_dbc,
        "f_ugb_hz": ar.loop.f_ugb,
        "pm_deg": ar.loop.pm_deg,
        "spurs_analytic": {k: round(float(v), 1)
                           for k, v in ar.spurs_analytic.items()},
        "notes": list(ar.notes),
        "png": _png(plot_pn_breakdown(ar, None)),
    }


def _bank(preset: str = "", overrides: dict[str, str] | None = None,
          candidate: str = "") -> list[dict]:
    rows = osc_bank_report(_build(preset, overrides, candidate).cfg)
    return [{"label_en": en, "label_zh": zh, "value": val}
            for en, zh, val in rows]


def _fine_info(preset: str = "", overrides: dict[str, str] | None = None,
               n_cycles: int = 150_000, m: int = 0,
               candidate: str = "") -> dict:
    pll = _build(preset, overrides, candidate)
    return {
        "supported": supports_fine(pll),
        "note": fine_oversample_note(pll, m),
        "record_mb": fine_record_mb(n_cycles, m),
    }


def _simulate(preset: str = "", overrides: dict[str, str] | None = None,
              n_cycles: int = 50_000, seed: int = 1, noise: bool = True,
              calibration: bool = True, f_start_offset_mhz: float = 0.0,
              dtc_gain_init_error: float = 0.0,
              fine_oversample: int = 0, candidate: str = "") -> dict:
    pll = _build(preset, overrides, candidate)
    kw = simulate_kwargs(pll, noise=noise, calibration=calibration, seed=seed,
                         f_start_offset=f_start_offset_mhz * 1e6,
                         dtc_gain_init_error=dtc_gain_init_error,
                         fine_oversample=fine_oversample)
    sim = pll.simulate(int(n_cycles), **kw)
    # overlay against a fresh analyze() of the same config, as the workbench
    # pages do -- the sim object holds no linear model to plot against
    ar = _build(preset, overrides, candidate).analyze()

    pngs = [{"title": "phase noise", "png": _png(plot_pn_breakdown(ar, sim))}]
    fig, (a1, a2) = plt.subplots(2, 1, figsize=(8, 5), sharex=True)
    a1.plot(sim.t * 1e6, (sim.freq_out - sim.f0) / 1e6, lw=0.7)
    a1.set_ylabel("f err [MHz]")
    a1.grid(alpha=0.3)
    a2.plot(sim.t * 1e6, sim.ctrl, lw=0.7, color="C1")
    a2.set_ylabel("vctrl / OTW")
    a2.set_xlabel("t [us]")
    a2.grid(alpha=0.3)
    pngs.append({"title": "transient", "png": _png(fig)})
    for k, tr in sim.cal_traces.items():
        fig, ax = plt.subplots(figsize=(8, 2.2))
        ax.plot(sim.t * 1e6, tr, lw=0.8)
        ax.set_ylabel(k)
        ax.set_xlabel("t [us]")
        ax.grid(alpha=0.3)
        pngs.append({"title": k, "png": _png(fig)})

    return {
        "jitter_fs": sim.jitter_fs,
        "lock_time_us": None if sim.lock_time_s is None
                        else sim.lock_time_s * 1e6,
        "f_end_ghz": float(sim.freq_out[-1]) / 1e9,
        "notes": list(sim.notes),
        "spurs_fft": [{"offset_hz": float(f), "dbc": float(v)}
                      for f, v in sim.spurs_fft.items()],
        "pngs": pngs,
    }


def _frac_pll(preset: str, inl_amp_s: float, inl_cycles: float,
              gain_residual: float) -> Any:
    """A fresh fractional preset with the spur-page knobs applied.

    The knobs mirror webgui's Spurs page: they poke cfg.frac.dtc directly
    rather than going through overrides, because inl_sin is a tuple field
    with a fixed third element (0.3 rad phase) the page never exposed.
    """
    pll = make_pll(preset, {})
    if getattr(pll.cfg, "frac", None) is None:
        raise TypeError(f"{preset} is integer-N: no DTC, no fractional spurs")
    pll.cfg.frac.dtc.inl_sin = (inl_amp_s, inl_cycles, 0.3) if inl_amp_s else ()
    pll.cfg.frac.dtc.gain_error_residual = gain_residual
    return pll


def _spur_predict(preset: str, inl_amp_s: float = 50e-15,
                  inl_cycles: float = 1.0,
                  gain_residual: float = 0.002) -> dict:
    ar = _frac_pll(preset, inl_amp_s, inl_cycles, gain_residual).analyze()
    tab = sorted(((k.split("@")[1], float(v))
                  for k, v in ar.spurs_analytic.items()
                  if k.startswith("frac_spur")), key=lambda kv: -kv[1])
    return {"rows": [{"offset": o, "dbc": round(v, 1)} for o, v in tab],
            "notes": list(ar.notes)}


def _spur_spectrum(preset: str, inl_amp_s: float = 50e-15,
                   inl_cycles: float = 1.0, gain_residual: float = 0.002,
                   n_cycles: int = 150_000, seed: int = 2) -> dict:
    pll = _frac_pll(preset, inl_amp_s, inl_cycles, gain_residual)
    sim = pll.simulate(int(n_cycles), seed=seed)
    fig = plot_spur_spectrum(sim, ar=make_pll(preset, {}).analyze())
    return {"notes": list(sim.notes), "png": _png(fig)}


def _ref_spur(preset: str, m: int = 128, n_cycles: int = 40_000) -> dict:
    rows, notes = ref_spur_comparison(make_pll(preset, {}), m=int(m),
                                      n_cycles=int(n_cycles))
    return {"rows": rows, "notes": notes}


def _spur_sweep(preset: str, inl_amp_s: float = 50e-15,
                inl_cycles: float = 1.0,
                gain_residual: float = 0.002) -> dict:
    """Worst fractional spur vs channel: near-integer channels are worst,
    because the beat lands inside the loop bandwidth where |NTF| ~ 1."""
    fracs = [0.0013, 0.0053, 0.0161, 0.0503, 0.1253, 0.2503, 0.3753, 0.4703]
    fref = make_pll(preset, {}).cfg.fref
    worst = []
    for fr in fracs:
        pll = _frac_pll(preset, inl_amp_s, inl_cycles, gain_residual)
        pll.cfg.fout = (int(pll.cfg.fout / fref) + fr) * fref
        pll.cfg.frac.frac = fr
        t = [float(v) for k, v in pll.analyze().spurs_analytic.items()
             if k.startswith("frac_spur")]
        worst.append(max(t) if t else None)
    f_ugb = make_pll(preset, {}).analyze().loop.f_ugb
    beats = [fr * fref for fr in fracs]
    fig, ax = plt.subplots(figsize=(7, 4))
    ax.semilogx(beats, [w if w is not None else float("nan") for w in worst],
                "o-")
    if math.isfinite(f_ugb):
        ax.axvline(f_ugb, color="gray", ls=":", label="UGB")
        ax.legend()
    ax.set_xlabel("fractional beat frac*fref [Hz]")
    ax.set_ylabel("worst spur [dBc]")
    ax.grid(alpha=0.3, which="both")
    ax.set_title(f"{preset}: worst fractional spur vs channel")
    return {"beats_hz": beats, "worst_dbc": worst, "f_ugb_hz": f_ugb,
            "png": _png(fig)}


def _hop_check(preset: str) -> dict | None:
    """FLL hand-off bound, or None for loops that have no FLL."""
    pll = make_pll(preset, {})
    if not hasattr(pll.cfg, "fll_i"):
        return None
    st = fll_stability(pll)
    return {"slew_khz_per_window": st["slew_per_window_hz"] / 1e3,
            "i_fll_max_ua": st["i_fll_max_a"] * 1e6,
            "margin": st["margin"], "ok": bool(st["margin"] > 1.0)}


def _hop_fig(r: Any) -> str:
    sim = r.sim
    fig, ax = plt.subplots(figsize=(9, 4))
    ax.plot(sim.t * 1e6, (sim.freq_out - r.f_to) / 1e6, lw=0.7)
    if "fll_engaged" in sim.cal_traces:
        eng = sim.cal_traces["fll_engaged"] > 0.5
        ax.fill_between(sim.t * 1e6, *ax.get_ylim(), where=eng, alpha=0.15,
                        color="C1", label="FLL engaged")
    if math.isfinite(r.t_phase_s):
        ax.axvline(r.t_phase_s * 1e6, color="r", ls="--", lw=1,
                   label=f"phase settled {r.t_phase_s * 1e6:.0f} us")
    ax.set_xlabel("t [us]")
    ax.set_ylabel("freq error [MHz]")
    ax.legend(fontsize=8)
    ax.grid(alpha=0.3)
    return _png(fig)


def _hop(preset: str, hop_hz: float = -100e6, n_cycles: int = 100_000,
         seed: int = 1) -> dict:
    pll = make_pll(preset, {})
    r = hop_settling(pll, pll.cfg.fout + hop_hz, n_cycles=int(n_cycles),
                     seed=int(seed))
    return {
        "t_freq_us": r.t_freq_s * 1e6,          # non-finite -> null (_clean)
        "t_phase_us": r.t_phase_s * 1e6,
        "fll_us": None if r.fll_engaged_s is None else r.fll_engaged_s * 1e6,
        "jitter_fs": r.jitter_fs,
        "png": _hop_fig(r),
    }


def _hop_stats(preset: str, hop_hz: float = -100e6, n_cycles: int = 100_000,
               n_seeds: int = 8) -> dict:
    stats = hop_statistics(lambda: make_pll(preset, {}),
                           make_pll(preset, {}).cfg.fout + hop_hz,
                           seeds=range(int(n_seeds)), n_cycles=int(n_cycles))
    tp = stats["t_phase_s"]
    fig, ax = plt.subplots(figsize=(7, 3.5))
    ax.hist(tp[np.isfinite(tp)] * 1e6, bins=12, alpha=0.8)
    ax.set_xlabel("t_phase [us]")
    ax.set_ylabel("hops")
    ax.grid(alpha=0.3)
    return {
        "p50_us": stats["p50_s"] * 1e6,
        "p95_us": stats["p95_s"] * 1e6,
        "worst_us": stats["worst_s"] * 1e6,
        "fail_pct": stats["fail_frac"] * 100.0,
        "png": _png(fig),
    }


def _benchmarks() -> dict:
    """The literature anchor, linear column computed live (same table both
    desktop GUIs render)."""
    return {"rows": presets.benchmark_table()}


def _select(fref_hz: float, fout_hz: float, jitter_fs_max: float,
            band_lo_hz: float = 10e3, band_hi_hz: float = 40e6,
            modulation: bool = False) -> dict:
    rep = select(Requirement(fref=fref_hz, fout=fout_hz,
                             jitter_fs_max=jitter_fs_max,
                             int_band=(band_lo_hz, band_hi_hz),
                             modulation=modulation))
    _CANDIDATES.clear()
    rows = []
    for cand in sorted(rep.candidates, key=lambda c: c.key):
        rows.append({
            "arch": cand.arch,
            "jitter_fs": cand.jitter_fs,
            "verdict": ("PASS" if cand.feasible
                        and cand.jitter_fs <= rep.req.jitter_fs_max
                        else ("fail" if cand.feasible else "excluded")),
            "f_ugb_khz": cand.f_ugb / 1e3,
            "pm_deg": cand.pm_deg,
            "notes": "; ".join(cand.notes),
        })
        if cand.feasible and cand.pll is not None:
            _CANDIDATES[cand.arch] = cand.pll
    return {
        "rows": rows,
        "best": None if rep.best is None else rep.best.arch,
        "best_jitter_fs": None if rep.best is None else rep.best.jitter_fs,
        "target_fs": rep.req.jitter_fs_max,
        "handoff": sorted(_CANDIDATES),
    }


def _filt_dict(filt: Any) -> dict:
    return {"c1_f": filt.c1, "r2_ohm": filt.r2, "c2_f": filt.c2,
            "r3_ohm": filt.r3, "c3_f": filt.c3}


def _synth_cp(icp_a: float, n: float, kvco_hz_v: float, ugb_hz: float,
              pm_deg: float, fref_hz: float) -> dict:
    return _filt_dict(design_cp_filter(cppll_kdet(icp_a, n), kvco_hz_v,
                                       ugb_hz, pm_deg, fref_hz))


def _synth_sspll(amp_v: float, gm_s: float, pulse_s: float,
                 kvco_hz_v: float, ugb_hz: float, pm_deg: float,
                 fref_hz: float) -> dict:
    return _filt_dict(design_sspll_filter(amp_v * gm_s * pulse_s, kvco_hz_v,
                                          ugb_hz, pm_deg, fref_hz))


def _synth_spll(amp_v: float, gm_s: float, pulse_s: float, n: float,
                kvco_hz_v: float, ugb_hz: float, pm_deg: float,
                fref_hz: float) -> dict:
    return _filt_dict(design_spll_filter(amp_v, gm_s, pulse_s, n,
                                         kvco_hz_v, ugb_hz, pm_deg, fref_hz))


def _synth_dlf(fref_hz: float, ugb_hz: float, pm_deg: float) -> dict:
    alpha, rho = design_adpll_dlf(fref_hz, ugb_hz, pm_deg)
    return {"alpha": alpha, "rho": rho}


def _bw_sweep(preset: str, lo_hz: float = 2e5, hi_hz: float = 3e6,
              n_points: int = 8, pm_deg: float | None = None) -> dict:
    if preset not in sweepable_presets():
        raise TypeError(f"{preset} has no loop retune_loop() can "
                        "re-synthesize (ILCM/MDLL have no loop filter)")
    ugbs = np.geomspace(lo_hz, hi_hz, int(n_points))
    res = sweep_bandwidth(
        lambda bw: retune_loop(presets.ALL_PRESETS[preset](), bw, pm_deg),
        ugbs)
    fig, ax = plt.subplots(figsize=(7, 4))
    ax.semilogx(res["f_ugb"], res["jitter_fs"], "o-")
    ax.set_xlabel("UGB [Hz]")
    ax.set_ylabel("jitter [fs]")
    ax.grid(alpha=0.3, which="both")
    ax.set_title(f"{preset}: jitter vs loop bandwidth")
    # sweep_bandwidth silently skips UGB targets the synthesizer cannot
    # reach; the caller must be able to see that 5-asked-3-answered happened
    return {"f_ugb_hz": list(res["f_ugb"]),
            "jitter_fs": list(res["jitter_fs"]),
            "n_requested": int(n_points),
            "png": _png(fig)}


def _modulate(preset: str, bit_rate_hz: float = 2.5e6, dp_err: float = 0.0,
              n_cycles: int = 100_000, seed: int = 2) -> dict:
    """Two-point GMSK modulation and EVM, mirroring the web GUI's page."""
    pll = make_pll(preset, {})
    fref = pll.cfg.fref
    sps = fref / bit_rate_hz
    n_cyc = int(n_cycles)
    settle = max(50_000, n_cyc // 3)
    if n_cyc - settle < 8_000:
        raise ValueError(f"{n_cyc} cycles leaves only {n_cyc - settle} after "
                         f"the {settle}-cycle settling window; raise cycles")
    bits = prbs(max(64, int((n_cyc - settle) * bit_rate_hz / fref) - 20),
                seed=7)
    fdev, _ = gmsk_trajectory(bits, fref, bit_rate_hz)
    mod = np.zeros(n_cyc)
    mod[settle:settle + min(fdev.size, n_cyc - settle)] = \
        fdev[: n_cyc - settle]
    ideal = 2 * np.pi * np.cumsum(mod) / fref
    mod_kw: dict[str, Any] = {"mod_freq": mod, "mod_dp_gain": 1.0 + dp_err}
    sim = pll.simulate(n_cyc, seed=int(seed), **mod_kw)
    e = evm(sim.phase_err_out[settle + 4000:], ideal[settle + 4000:])

    fig, (a1, a2) = plt.subplots(2, 1, figsize=(8, 6))
    sl = slice(settle + 4000, settle + 4000 + int(40 * sps))
    a1.plot(sim.t[sl] * 1e6, mod[sl] / 1e6)
    a1.set_xlabel("t [us]")
    a1.set_ylabel("dev [MHz]")
    a1.grid(alpha=0.3)
    d = sim.phase_err_out[settle + 4000:] - ideal[settle + 4000:]
    x = np.arange(d.size)
    d = d - np.polyval(np.polyfit(x, d, 1), x)
    a2.plot(sim.t[settle + 4000:] * 1e3, np.degrees(d), lw=0.5)
    a2.set_xlabel("t [ms]")
    a2.set_ylabel("phase error [deg]")
    a2.grid(alpha=0.3)
    fig.tight_layout()
    return {
        "evm_pct": e["evm_pct"],
        "evm_db": e["evm_db"],
        "phase_err_rms_deg": e["phase_err_rms_deg"],
        "sps": sps,
        # < 8 samples/symbol: the per-ref-cycle grid floors the comparison
        # against the continuous ideal; only the mismatch trend is real then
        "sps_ok": bool(sps >= 8),
        "png": _png(fig),
    }


def _drift_info(preset: str, eps_total: float = 0.03,
                ramp_cycles: int = 60_000) -> dict:
    """The rate-vs-mu precheck the page shows before anything runs."""
    frac = getattr(make_pll(preset, {}).cfg, "frac", None)
    if frac is None or frac.dtc_cal is None:
        raise TypeError(f"{preset} has no DTC gain calibrator to drift")
    mu_final = frac.dtc_cal.mu_final or frac.dtc_cal.mu
    rate = eps_total / int(ramp_cycles)
    return {"rate_per_cycle": rate, "mu_final": mu_final,
            # the sign-sign slew wall is rate == mu_final
            "rate_over_mu": rate / mu_final}


def _drift(preset: str, eps_total: float = 0.03, ramp_cycles: int = 60_000,
           ramp_start: int = 80_000, seed: int = 3) -> dict:
    """Background-calibration tracking under an accelerated gain ramp."""
    info = _drift_info(preset, eps_total, ramp_cycles)
    n_ramp, start = int(ramp_cycles), int(ramp_start)
    n = start + n_ramp
    pll = make_pll(preset, {})
    cal = pll.cfg.frac.dtc_cal
    cal.gear_shift_n = min(cal.gear_shift_n or 40_000, start // 2)
    drift = np.zeros(n)
    drift[start:] = eps_total * np.arange(n_ramp) / n_ramp
    drift_kw: dict[str, Any] = {"dtc_gain_drift": drift}
    sim = pll.simulate(n, seed=int(seed), **drift_kw)
    g = sim.cal_traces["dtc_gain"]
    lag = np.abs(g * (1.0 + drift) - 1.0)
    c = pll.cfg
    if type(pll).__name__ == "SPLL":
        def tof(r: float) -> float:
            return -r / c.fout - c.frac.dtc.range_s / 2.0
    elif type(pll).__name__ == "SSPLL":
        def tof(r: float) -> float:
            return (1.0 + r) / c.fout - c.frac.dtc.range_s / 2.0
    else:
        def tof(r: float) -> float:
            return r / c.fout
    tab = dtc_spur_table(c.frac, tof, c.fref, c.fout,
                         gain_eps=float(lag[-1]))

    fig, ax = plt.subplots(figsize=(9, 4))
    t_ms = (np.arange(n) - start) / c.fref * 1e3
    ax.plot(t_ms, lag * 100, lw=0.9, label="tracking lag")
    ax.plot(t_ms, drift * 100, "--", lw=0.9, label="true drift")
    ax.set_xlabel("time from ramp start [ms]")
    ax.set_ylabel("[%]")
    ax.legend()
    ax.grid(alpha=0.3)
    return {
        **info,
        "peak_lag_pct": float(lag[-1]) * 100.0,
        "jitter_fs": sim.jitter_fs,
        "lag_spur_dbc": max(tab.values()) if tab else None,
        "notes": list(sim.notes),
        "png": _png(fig),
    }


_METHODS: dict[str, Callable[..., Any]] = {
    "list_presets": _list_presets,
    "fields": _fields,
    "analyze": _analyze,
    "bank": _bank,
    "fine_info": _fine_info,
    "simulate": _simulate,
    "spur_predict": _spur_predict,
    "spur_spectrum": _spur_spectrum,
    "spur_sweep": _spur_sweep,
    "ref_spur": _ref_spur,
    "benchmarks": _benchmarks,
    "select": _select,
    "synth_cp": _synth_cp,
    "synth_sspll": _synth_sspll,
    "synth_spll": _synth_spll,
    "synth_dlf": _synth_dlf,
    "bw_sweep": _bw_sweep,
    "modulate": _modulate,
    "drift_info": _drift_info,
    "drift": _drift,
    "hop_check": _hop_check,
    "hop": _hop,
    "hop_stats": _hop_stats,
}


def call(method: str, args_json: str = "{}") -> str:
    """Single host entry point: dispatch, and never raise across the FFI.

    A Python exception crossing into Kotlin arrives as a PyException whose
    message the WebView cannot render usefully, so errors come back in-band:
    ``{"ok": false, "error": ..., "traceback": ...}``.  The traceback is for
    an engineer reading logcat, not for the UI.
    """
    try:
        fn = _METHODS[method]
        args = json.loads(args_json) if args_json else {}
        result = fn(**args)
        return json.dumps({"ok": True, "result": _clean(result)})
    except Exception as e:                          # noqa: BLE001 -- FFI boundary
        return json.dumps({"ok": False, "error": f"{type(e).__name__}: {e}",
                           "traceback": traceback.format_exc()})
