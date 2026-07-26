"""GUI-support logic with no GUI dependency (unit-testable).

The Streamlit app (gui/) auto-generates parameter forms from the Config
dataclass trees.  This module provides the introspection: enumerate a
config's editable fields (flattened, dot-paths into nested dataclasses),
annotate them with units/labels, and apply string-valued overrides back
onto a fresh config.  Calibrator objects (SignSignLMS/LMSGainCal) carry
state, so they are rebuilt from their numeric parameters on every apply.
"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass

from . import presets

# fields never shown in forms (derived/rebuilt/complex)
_SKIP = {"trace", "lut", "counts"}

# field name -> (unit, zh label, en label); unlisted fields show raw names
FIELD_INFO = {
    "fref": ("Hz", "参考频率", "reference frequency"),
    "fout": ("Hz", "输出频率", "output frequency"),
    "ref_pn_dbchz": ("dBc/Hz", "参考噪声底", "reference PN floor"),
    "ref_pn_fc": ("Hz", "参考闪烁拐角", "reference flicker corner"),
    "div_pn_dbchz": ("dBc/Hz", "分频器噪声底", "divider PN floor"),
    "div_pn_fc": ("Hz", "分频器闪烁拐角", "divider flicker corner"),
    "int_band": ("Hz,Hz", "积分带", "integration band"),
    "f0": ("Hz", "自由振荡频率", "free-running frequency"),
    "gain": ("Hz/V | Hz/LSB", "调谐增益", "tuning gain"),
    "pn_dbchz": ("dBc/Hz", "相噪@偏移", "PN at spot offset"),
    "pn_foffset": ("Hz", "相噪偏移点", "PN spot offset"),
    "pn_f1f3": ("Hz", "1/f^3 拐角", "1/f^3 corner"),
    "pn_floor_dbchz": ("dBc/Hz", "相噪底", "PN floor"),
    "nl1": ("1/V", "Kvco 一阶非线性", "Kvco 1st-order nonlinearity"),
    "nl2": ("1/V^2", "Kvco 二阶非线性", "Kvco 2nd-order nonlinearity"),
    "n_bands": ("", "粗调频段数", "coarse bands"),
    "band_step_hz": ("Hz", "频段间距", "band step"),
    "v_min": ("V", "控制电压下限（空=不限）", "control-voltage min (blank = none)"),
    "v_max": ("V", "控制电压上限（空=不限）", "control-voltage max (blank = none)"),
    "noise_a2hz": ("A^2/Hz", "CP 电流噪声（空=默认）",
                   "CP current noise (blank = default)"),
    "gm_noise_a2hz": ("A^2/Hz", "gm 电流噪声（空=默认）",
                      "gm current noise (blank = default)"),
    "pushing_hz_v": ("Hz/V", "电源推频", "supply pushing"),
    "icp": ("A", "CP 电流", "charge-pump current"),
    "mismatch_pct": ("%", "上下电流失配", "up/down mismatch"),
    "leakage_a": ("A", "泄漏电流", "leakage"),
    "t_reset": ("s", "PFD 复位时间", "PFD reset time"),
    "c1": ("F", "滤波 C1", "filter C1"),
    "r2": ("Ohm", "滤波 R2", "filter R2"),
    "c2": ("F", "滤波 C2", "filter C2"),
    "r3": ("Ohm", "滤波 R3", "filter R3"),
    "c3": ("F", "滤波 C3", "filter C3"),
    "amp_v": ("V", "采样摆幅", "sampled amplitude"),
    "c_samp": ("F", "采样电容", "sampling cap"),
    "gm": ("S", "跨导", "transconductance"),
    "pulse_width": ("s", "采样脉宽", "pulse width"),
    "pedestal_v": ("V", "基座误差", "pedestal error"),
    "t_res": ("s", "分辨率 LSB", "resolution LSB"),
    "n_bits": ("bit", "位数", "bits"),
    "jitter_rms_s": ("s", "附加抖动", "additive jitter"),
    "gain_error_residual": ("", "analyze 残余增益误差", "analyze gain residual"),
    "frac": ("", "小数字", "fractional word"),
    "mash_order": ("", "MASH 阶数", "MASH order"),
    "bits": ("bit", "累加器位宽", "accumulator bits"),
    "alpha": ("", "DLF 比例", "DLF proportional"),
    "rho": ("", "DLF 积分", "DLF integral"),
    "iir_lambdas": ("", "IIR 系数", "IIR lambdas"),
    "bb_jitter_rms_s": ("s", "BBPD 输入抖动", "BBPD input jitter"),
    "kdco_est_error": ("", "KDCO 估计误差", "KDCO estimate error"),
    "dco_dither_order": ("", "DCO 抖动阶数", "DCO dither order"),
    "fll_i": ("A", "FLL 电流", "FLL current"),
    "fll_window": ("cyc", "FLL 测量窗", "FLL window"),
    "fll_engage": ("Hz", "FLL 接入阈值", "FLL engage"),
    "fll_release": ("Hz", "FLL 释放阈值", "FLL release"),
    "beta": ("", "注入强度", "injection strength"),
    "q_tank": ("", "谐振腔 Q", "tank Q"),
    "i_ratio": ("", "注入电流比", "injection current ratio"),
    "inj_jitter_rms_s": ("s", "注入沿抖动", "injection edge jitter"),
    "ftl_f_lsb": ("Hz", "FTL 频率 LSB", "FTL frequency LSB"),
    "mux_jitter_rms_s": ("s", "MUX 抖动", "mux jitter"),
    "mu": ("", "LMS 步长", "LMS mu"),
    "mu_final": ("", "换挡后步长", "post-gear-shift mu"),
    "gear_shift_n": ("cyc", "换挡时刻", "gear-shift cycle"),
    "mode": ("", "工作模式", "mode"),
}


@dataclass
class FieldSpec:
    path: str          # dot path, e.g. "osc.pn_dbchz"
    value: object
    kind: str          # "float" | "int" | "str" | "tuple"
    unit: str = ""
    label_zh: str = ""
    label_en: str = ""
    optional: bool = False   # None is a legal value (form shows it blank)


def _is_calibrator(obj) -> bool:
    return hasattr(obj, "step") and hasattr(obj, "mu")


_SCALAR_KINDS = {"float": "float", "int": "int", "str": "str",
                 "tuple": "tuple"}


def _kind_from_annotation(ann) -> str | None:
    """Kind of an ``X | None`` field that currently holds None.

    A None value carries no type, so optional scalars (OscConfig.v_min/v_max,
    the noise overrides) would otherwise be invisible to the forms — which is
    exactly the class of knob a GUI user most needs to be able to set.  Only
    plain scalar unions are accepted; ``FracConfig | None`` and friends stay
    out, since a form cannot build a sub-config from a text box.
    """
    ann = ann if isinstance(ann, str) else getattr(ann, "__name__", str(ann))
    parts = [p.strip().strip("'\"") for p in ann.split("|")]
    if "None" not in parts:
        return None
    kinds = {_SCALAR_KINDS[p] for p in parts
             if p in _SCALAR_KINDS} | {_SCALAR_KINDS["tuple"]
                                       for p in parts
                                       if p.startswith("tuple[")}
    return kinds.pop() if len(kinds) == 1 else None


def enumerate_fields(cfg, prefix: str = "") -> list[FieldSpec]:
    """Flatten a config dataclass tree into editable field specs."""
    out: list[FieldSpec] = []
    for f in dataclasses.fields(cfg):
        if f.name in _SKIP:
            continue
        v = getattr(cfg, f.name)
        path = f"{prefix}{f.name}"
        if v is None:
            kind = _kind_from_annotation(f.type)
            if kind is None:
                continue
            info = FIELD_INFO.get(f.name, ("", f.name, f.name))
            out.append(FieldSpec(path, None, kind, info[0], info[1], info[2],
                                 optional=True))
            continue
        if dataclasses.is_dataclass(v):
            out += enumerate_fields(v, prefix=f"{path}.")
            continue
        if _is_calibrator(v):
            for p in ("mu", "gear_shift_n", "mu_final"):
                pv = getattr(v, p, None)
                if pv is not None:
                    info = FIELD_INFO.get(p, ("", p, p))
                    kind = "int" if p == "gear_shift_n" else "float"
                    out.append(FieldSpec(f"{path}.{p}", pv, kind,
                                         info[0], info[1], info[2]))
            continue
        if isinstance(v, bool) or callable(v):
            continue
        if isinstance(v, int):
            kind = "int"
        elif isinstance(v, float):
            kind = "float"
        elif isinstance(v, tuple):
            kind = "tuple"
        elif isinstance(v, str):
            kind = "str"
        else:
            continue
        info = FIELD_INFO.get(f.name, ("", f.name, f.name))
        out.append(FieldSpec(path, v, kind, info[0], info[1], info[2],
                             optional=_kind_from_annotation(f.type) is not None))
    return out


def parse_value(text: str, kind: str):
    """Parse a form string back to the field's type ('1e-12', '(1e3,4e7)').

    A blank box means None — how an optional field is cleared from a form.
    """
    text = str(text).strip()
    if not text:
        return None
    if kind == "float":
        return float(text)
    if kind == "int":
        return int(float(text))
    if kind == "tuple":
        parts = [p for p in text.replace("(", "").replace(")", "")
                 .replace(",", " ").split() if p]
        return tuple(float(p) for p in parts)
    return text


def apply_overrides(cfg, overrides: dict[str, str]):
    """Apply {dot.path: string} overrides in place; calibrators rebuilt."""
    specs = {s.path: s for s in enumerate_fields(cfg)}
    for path, text in overrides.items():
        if path not in specs:
            raise KeyError(f"unknown field {path}")
        val = parse_value(text, specs[path].kind)
        if val is None and not specs[path].optional:
            raise ValueError(f"{path} cannot be blank")
        obj = cfg
        parts = path.split(".")
        for p in parts[:-1]:
            obj = getattr(obj, p)
        setattr(obj, parts[-1], val)
    # rebuild any calibrators so state never leaks between runs
    _rebuild_calibrators(cfg)
    return cfg


def _rebuild_calibrators(cfg):
    from .calibration.lms import SignSignLMS
    for f in dataclasses.fields(cfg):
        v = getattr(cfg, f.name)
        if dataclasses.is_dataclass(v) and not isinstance(v, type):
            _rebuild_calibrators(v)
        elif _is_calibrator(v):
            setattr(cfg, f.name, SignSignLMS(
                init=1.0, mu=v.mu,
                gear_shift_n=getattr(v, "gear_shift_n", None),
                mu_final=getattr(v, "mu_final", None)))


def make_pll(preset_name: str, overrides: dict[str, str] | None = None):
    """Fresh preset instance with optional field overrides applied."""
    pll = presets.ALL_PRESETS[preset_name]()
    if overrides:
        apply_overrides(pll.cfg, overrides)
    return pll


def osc_bank_report(cfg) -> list[tuple[str, str, str]]:
    """Coarse-band-bank sizing rows: (metric, zh note, value) for the forms.

    Empty when the oscillator has no control-voltage range, because without one
    every band reaches every frequency and there is nothing to report.  With a
    range the two questions worth answering before a run are whether the bank
    covers the target at all and whether adjacent bands join up — a gap reads
    as a loop that will not lock rather than as a mis-sized oscillator.
    """
    osc = getattr(cfg, "osc", None)
    if osc is None or not getattr(osc, "v_limited", False):
        return []
    lo, hi = osc.bank_range_hz()
    rows = [("bank range", "频段总覆盖",
             f"{lo / 1e9:.3f}-{hi / 1e9:.3f} GHz")]
    b_lo, b_hi = osc.band_range_hz(0)
    rows.append(("band span", "单频段跨度",
                 f"{(b_hi - b_lo) / 1e6:.1f} MHz"))
    if osc.n_bands > 1:
        ov = osc.band_overlap_hz()
        rows.append(("band overlap", "相邻频段重叠",
                     f"{ov / 1e6:+.1f} MHz"
                     + ("" if ov > 0 else "  (GAP — bank not continuous)")))
    covers = lo <= cfg.fout <= hi
    rows.append(("fout reachable", "目标频率可达",
                 "yes" if covers else "NO — target outside the bank"))
    return rows


def arch_kind(pll) -> str:
    return type(pll).__name__


def fmt_value(v) -> str:
    """Format a field value for a text input (keeps scientific notation)."""
    if v is None:
        return ""
    if isinstance(v, float):
        return f"{v:.6g}"
    if isinstance(v, tuple):
        return ", ".join(f"{x:.6g}" for x in v)
    return str(v)


def mc_build_frac_cppll(rng, s_mismatch: float = 1.5, s_leak: float = 2e-9,
                        s_gain: float = 0.05, s_inl: float = 0.7e-12,
                        s_kvco: float = 3e6, n_cycles: int = 150_000):
    """Module-level MC build (picklable for ProcessPoolExecutor) — the ex11
    fractional-N CPPLL with per-chip draws; sigmas adjustable from the GUI."""
    from .arch.cppll import CPPLL, CPPLLConfig, FracConfig
    from .blocks.chargepump import CPConfig
    from .blocks.dtc import DTCConfig
    from .blocks.loopfilter import FilterDesign
    from .blocks.oscillator import OscConfig
    from .calibration.lms import SignSignLMS
    import numpy as np

    mismatch = rng.normal(0.0, s_mismatch)
    leakage = abs(rng.normal(0.0, s_leak))
    dtc_gain_err = rng.normal(0.0, s_gain)
    inl_amp = abs(rng.normal(0.0, s_inl))
    inl_phase = rng.uniform(0, 2 * np.pi)
    kvco = rng.normal(60e6, s_kvco)
    f1f3 = max(rng.normal(3e5, 6e4), 5e4)
    frac = 0.2525
    cfg = CPPLLConfig(
        fref=38.4e6, fout=(156 + frac) * 38.4e6,
        osc=OscConfig(f0=5.95e9, gain=kvco, pn_dbchz=-120.0, pn_foffset=1e6,
                      pn_f1f3=f1f3, pn_floor_dbchz=-152.0),
        cp=CPConfig(icp=1.5e-3, mismatch_pct=mismatch, leakage_a=leakage,
                    t_reset=150e-12),
        filt=FilterDesign(c1=470e-12, r2=15e3, c2=3.3e-12, r3=1.5e3,
                          c3=2.2e-12),
        ref_pn_dbchz=-160.0,
        frac=FracConfig(
            frac=frac, mash_order=2,
            dtc=DTCConfig(t_res=250e-15, n_bits=12, jitter_rms_s=30e-15,
                          inl_sin=(inl_amp, 3.0, inl_phase)),
            dtc_cal=SignSignLMS(init=1.0, mu=5e-6, gear_shift_n=60_000,
                                mu_final=5e-7)))
    sim_kwargs = dict(n_cycles=n_cycles, dtc_gain_init_error=dtc_gain_err)
    params = dict(mismatch_pct=mismatch, leakage_na=leakage * 1e9,
                  dtc_gain_err=dtc_gain_err, inl_amp_ps=inl_amp * 1e12,
                  kvco_mhz=kvco / 1e6)
    return CPPLL(cfg), sim_kwargs, params
