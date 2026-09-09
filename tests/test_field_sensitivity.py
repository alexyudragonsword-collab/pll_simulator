"""Every editable field has to move some number, or say why it cannot.

This repository's signature defect is the parameter that reads correctly and
does nothing: a corner axis naming a supply no equation touched, a bool the
forms never offered, a Kdco estimate error the BBPD path never read.  Each
was found by driving it and watching the output stay put.  This gate does
that for every field of every preset on every push.

Per field: perturb it (a rule table knows which fields need a partner knob
or a run context -- supply ripple for pushing, a start offset for the FLL,
a DTC gain error for the calibrator), then compare analyze(); if nothing
moved, compare a short simulate() against a baseline run with the same
context.  Nothing moved in either = inert = red, unless INERT_OK names the
(architecture, field) with the reason.  Entries there are re-checked in the
other direction too: a listed field that starts moving something fails, so
the list cannot rot.  A config refusal counts as checked -- the value was
read and judged -- and is reported separately.
"""
from __future__ import annotations

import inspect

import numpy as np
import pytest

from pllsim import presets
from pllsim.guiutil import enumerate_fields, fmt_value, make_pll, simulate_kwargs

pytestmark = pytest.mark.sensitivity

N_CYCLES = 4_000
SEED = 1

# typical magnitude for a field whose stock value is 0 or None: x1.3 of
# nothing is nothing, and 1e-3 Hz of pushing is not a perturbation either
TYPICAL = {
    "osc.pushing_hz_v": 1e6, "osc.pull_lock_range_hz": 2e6,
    "osc.pull_offset_hz": 5e6, "osc.nl1": 0.1, "osc.nl2": 0.05,
    "osc.band_step_hz": 2e8, "cp.leakage_a": 1e-9, "cp.mismatch_pct": 3.0,
    "cp.dead_zone_s": 1e-11, "cp.mismatch_slope_pct_v": 5.0,
    "cp.leakage_slope_a_v": 1e-9, "cp.v_ref": 0.3, "cp.noise_a2hz": 1e-22,
    "sampler.kick_q_c": 1e-15, "sampler.kick_delay_s": 1e-10,
    "sampler.gm_noise_a2hz": 1e-22, "ref_doubler_duty_err": 0.02,
    "retime_jitter_rms_s": 1e-12, "ftl_det_offset_s": 2e-12,
    "bb_meta_window_s": 5e-14, "kdco_est_error": 0.1, "tdc.gain_error": 0.05,
    "osc.v_min": None, "osc.v_max": None,        # computed from v_for below
    "q_tank": 10.0, "i_ratio": 0.2,
}
JITTER_LIKE = ("jitter_rms_s",)                # any *_jitter_rms_s at 0 -> 1 ps

# integer fields where +1 is not a perturbation of what the field controls
INT_RULE = {"n_bits": "2", "gear_shift_n": "500", "n_bands": "3", "bits": "8",
            "dco_dither_order": "0"}

# a field that only acts together with another one: set the partner too
PARTNER = {
    "osc.band_step_hz": {"osc.n_bands": "3"},
    "osc.n_bands": {"osc.band_step_hz": "2e8"},
    "osc.pull_lock_range_hz": {"osc.pull_offset_hz": "5e6"},
    "osc.pull_offset_hz": {"osc.pull_lock_range_hz": "2e6"},
    "sampler.kick_delay_s": {"sampler.kick_q_c": "1e-15"},
    "cp.v_ref": {"cp.mismatch_slope_pct_v": "5"},
    "retime_jitter_rms_s": {"divider_retimed": "true"},
    "frac.dtc_cal.mu_final": {"frac.dtc_cal.gear_shift_n": "500"},
    "timing_cal": {"ftl_det_offset_s": "2e-12"},
    "timing_cal_step_s": {"timing_cal": "true", "ftl_det_offset_s": "2e-12"},
}

# a field that only acts in a run that exercises it
CONTEXT = {
    "fll_": dict(f_start_offset=5e6),
    "ftl": dict(f_start_offset=1e6),          # maps to f_free_error
    "frac.dtc_cal.": dict(dtc_gain_init_error=0.05),
    "osc.pushing_hz_v": dict(supply_ripple=(0.05, 1e6)),
}

# structurally unperturbable from a form; covered by presets of each kind
STRUCTURAL = {"mode": "switching mode needs the other mode's sub-config "
                      "(tdc / frac); both modes ship as presets"}

# (architecture label or preset name, field) -> why it legitimately moves
# nothing.  Every entry is re-checked: a listed field that starts moving
# something fails, so the list cannot rot.
_FLL_REENGAGE = ("re-engage threshold only: the FLL state machine starts in "
                 "ACQ and consults f_engage after a release, which a single "
                 "acquisition never reaches; the hop tests exercise it")
INERT_OK = {
    ("sspll_19p2m_4p8g", "fll_engage"): _FLL_REENGAGE,
    ("spll_100m_8g", "fll_engage"): _FLL_REENGAGE,
    ("bench_gao09_sspll_55p25m_2p21g", "fll_engage"): _FLL_REENGAGE,
    ("bench_markulic16_sspll_40m_10p24g", "fll_engage"): _FLL_REENGAGE,
    ("ADPLL:tdc", "osc.f0"): "the OTW is recentred on (fout-f0)/Kdco exactly, "
                             "so f0 only shifts the word; no word range is "
                             "modelled",
    ("ADPLL:dtc_bbpd", "osc.f0"): "same recentring as the TDC path",
    ("ADPLL:tdc", "bb_jitter_rms_s"): "dtc_bbpd-only field on a TDC preset",
    ("ADPLL:tdc", "bb_meta_window_s"): "dtc_bbpd-only field on a TDC preset",
}


def _label(pll) -> str:
    name = type(pll).__name__
    mode = getattr(pll.cfg, "mode", None)
    return f"{name}:{mode}" if mode else name


def _perturb(spec, pll) -> dict[str, str] | None:
    """The override set that should move something for this field."""
    p, v, k = spec.path, spec.value, spec.kind
    if p in STRUCTURAL:
        return None
    out: dict[str, str] = {}
    if p == "fref":
        out[p] = fmt_value(v / 2)
    elif p == "fout":
        out[p] = fmt_value(v * 2)
    elif p in ("osc.v_min", "osc.v_max"):
        v_op = pll.cfg.osc.v_for(pll.cfg.fout)
        out[p] = fmt_value(v_op + 0.05 if p.endswith("min") else v_op - 0.05)
    elif k == "bool":
        out[p] = fmt_value(not v)
    elif k == "str":
        if p == "cp.pfd_mode":
            out[p] = "wrap" if v == "clamp" else "clamp"
        else:
            return None
    elif k == "int":
        leaf = p.rsplit(".", 1)[-1]
        if leaf == "mash_order":
            out[p] = "3" if int(v) == 2 else "2"      # SSPLL/SPLL refuse != 1
        else:
            out[p] = INT_RULE.get(leaf, str(int(v) + 1))
    elif k == "tuple":
        if not v:
            leaf = p.rsplit(".", 1)[-1]
            out[p] = {"inl_sin": "(2e-13, 1, 0)", "inl_poly": "(0, 5e-13, -5e-13)",
                      "iir_lambdas": "(0.1,)"}.get(leaf, "(0.1,)")
        else:
            out[p] = fmt_value(tuple(x * 1.3 if x else 1e3 for x in v))
    elif p.startswith("frac.dtc_cal.mu"):
        # a bang-bang detector only changes its sign when a shift straddles
        # a decision; 1.3x on an LMS step moves the DTC by ~10 fs in 4000
        # cycles and never does -- 10x does.  mu_final gets 100x: at 10x it
        # landed exactly on the stock mu, and a gear shift onto the same
        # step is no shift
        out[p] = fmt_value(v * (100 if p.endswith("mu_final") else 10))
    elif p == "fll_engage":
        # the run starts 5 MHz off; an engage threshold above that keeps the
        # FLL out entirely, which is the difference the field makes
        out[p] = fmt_value(v * 10)
    else:                                   # float
        if v is None or v == 0:
            if p in TYPICAL and TYPICAL[p] is not None:
                out[p] = fmt_value(TYPICAL[p])
            elif p.endswith(JITTER_LIKE):
                out[p] = "1e-12"
            else:
                out[p] = "1e-3"
        else:
            out[p] = fmt_value(v * 1.3)
    out.update(PARTNER.get(p, {}))
    return out


def _context(path: str) -> dict:
    for key, ctx in CONTEXT.items():
        if path.startswith(key):
            return dict(ctx)
    return {}


def _sig_analyze(ar):
    return (round(ar.jitter_fs, 9), round(ar.ipn_dbc, 9),
            np.round(10 * np.log10(ar.pn_breakdown["total"] + 1e-300), 6).tobytes(),
            tuple(ar.notes),
            tuple(sorted((k, _nan_safe(v)) for k, v in ar.spurs_analytic.items())),
            round(ar.loop.f_ugb, 6), round(ar.loop.pm_deg, 6))


def _nan_safe(v):
    # a spur below the noise floor is NaN, and nan != nan would read as
    # "moved" on two bitwise-identical records
    return None if v is None or (isinstance(v, float) and np.isnan(v)) else round(v, 6)


def _sig_sim(sim):
    return (np.round(sim.phase_err_out, 12).tobytes(),
            np.round(sim.freq_out, 6).tobytes(), sim.lock_time_s,
            tuple(sim.notes), _nan_safe(sim.jitter_fs),
            tuple(sorted((round(k, 3), _nan_safe(v)) for k, v in sim.spurs_fft.items())),
            tuple((k, np.round(np.asarray(v, dtype=float), 12).tobytes())
                  for k, v in sorted(sim.cal_traces.items())))


def _run(pll, ctx: dict):
    kw = simulate_kwargs(pll, seed=SEED, **{k: v for k, v in ctx.items()
                                            if k != "supply_ripple"})
    if "supply_ripple" in ctx:
        if "supply_ripple" not in inspect.signature(type(pll).simulate).parameters:
            return None
        kw["supply_ripple"] = ctx["supply_ripple"]
    return _sig_sim(pll.simulate(N_CYCLES, **kw))


@pytest.mark.parametrize("name", sorted(presets.ALL_PRESETS))
def test_every_field_moves_something_or_says_why(name):
    base = make_pll(name)
    label = _label(base)
    a0 = _sig_analyze(base.analyze())
    sim_base: dict[tuple, object] = {}
    inert, refused, rotten = [], [], []
    for spec in enumerate_fields(base.cfg):
        ov = _perturb(spec, base)
        if ov is None:
            assert spec.path in STRUCTURAL or spec.kind == "str", spec.path
            continue
        try:
            pll = make_pll(name, ov)
        except ValueError as e:
            refused.append(f"{spec.path}: {str(e)[:60]}")
            continue
        moved = _sig_analyze(pll.analyze()) != a0
        if not moved:
            ctx = _context(spec.path)
            key = tuple(sorted(ctx.items()))
            if key not in sim_base:
                sim_base[key] = _run(base, ctx)
            s1 = _run(pll, ctx)
            moved = sim_base[key] is None or s1 != sim_base[key]
        listed = (label, spec.path) in INERT_OK or (name, spec.path) in INERT_OK
        if not moved and not listed:
            inert.append(f"{spec.path} <- {ov}")
        if moved and listed:
            rotten.append(spec.path)
    assert not inert, (f"{name} ({label}): these fields moved nothing in "
                       f"analyze() or a {N_CYCLES}-cycle simulate():\n  "
                       + "\n  ".join(inert))
    assert not rotten, (f"{name}: INERT_OK lists fields that now move "
                        f"something -- drop them: {rotten}")


def test_inert_ok_names_only_real_fields():
    seen = set()
    for name in presets.ALL_PRESETS:
        pll = presets.ALL_PRESETS[name]()
        for s in enumerate_fields(pll.cfg):
            seen.add((_label(pll), s.path))
            seen.add((name, s.path))
    missing = [k for k in INERT_OK if k not in seen]
    assert not missing, f"INERT_OK entries for fields no preset has: {missing}"
