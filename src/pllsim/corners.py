"""Named process/voltage/temperature corners.

The Monte Carlo framework draws continuous distributions, which answers "what
is the yield".  It does not answer the question a design review actually asks
first -- "does it still work at SS/125C/0.9*VDD" -- because that is a small set
of named, reproducible points, not a sample.  Both matter and they are not
substitutes: MC finds the tail, corners find the systematic worst case, and a
loop can pass one and fail the other.

A corner here is a set of multiplicative deviations on the physical quantities
a PDK corner actually moves.  Applying one rebuilds the config; it does NOT
retune the loop, which is the whole point -- the bandwidth and phase margin
move, and seeing how far is the result.

Fields absent from a given architecture are skipped, so the same corner applies
to all six without a per-architecture table.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, fields, replace

T0_C = 27.0


@dataclass(frozen=True)
class Corner:
    """Multiplicative deviations from the nominal (typical) configuration."""

    name: str
    kvco: float = 1.0          # oscillator gain (Hz/V or Hz/LSB)
    f0: float = 1.0            # oscillator free-running / centre frequency
    icp: float = 1.0           # charge-pump current
    res: float = 1.0           # loop-filter resistors
    cap: float = 1.0           # loop-filter and sampling capacitors
    gm: float = 1.0            # sampler transconductance
    tdelay: float = 1.0        # digital delay cells: TDC/DTC LSB and PFD reset
    # Oscillator phase noise in dB, added to the spot and the floor.  This is
    # the axis a purely component-scaling corner misses, and for an
    # injection-locked multiplier it is the ONLY one that moves anything: its
    # bandwidth is fref/pi by construction, so scaling resistors and currents
    # leaves it identical at every corner, which reads as "immune" rather than
    # "not modelled".  Hot and slow silicon is noisier; kT/f alone is +1.4 dB
    # from 27C to 125C before any mobility degradation.
    pn_db: float = 0.0
    ref_pn_db: float = 0.0     # reference/crystal floor, same convention
    temp_c: float = T0_C
    # Supply relative to nominal, acting through OscConfig.pushing_hz_v.  It
    # needs a nominal in volts to become a deviation in volts, and there is no
    # supply voltage anywhere in the configs -- an oscillator only ever
    # declares how many Hz it moves per volt.
    vdd: float = 1.0
    vdd_nominal_v: float = 1.0

    @property
    def temp_k(self) -> float:
        return self.temp_c + 273.15


# The usual corner box.  Digital delay tracks the process the same way the
# transistors do (fast silicon = short delay), and capacitors are a separate
# module from the transistors, which is why cap moves on its own axis.
TT = Corner("TT_27C", temp_c=27.0)
SS_HOT = Corner("SS_125C_0.9V", kvco=0.75, f0=0.97, icp=0.7, res=1.2, cap=1.1,
                gm=0.75, tdelay=1.35, pn_db=3.0, ref_pn_db=1.5,
                temp_c=125.0, vdd=0.9)
FF_COLD = Corner("FF_-40C_1.1V", kvco=1.3, f0=1.03, icp=1.35, res=0.82,
                 cap=0.9, gm=1.3, tdelay=0.72, pn_db=-2.0, ref_pn_db=-1.0,
                 temp_c=-40.0, vdd=1.1)
SF_HOT = Corner("SF_125C", kvco=0.9, f0=0.99, icp=1.15, res=1.1, cap=1.05,
                gm=0.9, tdelay=1.1, pn_db=2.0, ref_pn_db=1.5, temp_c=125.0)
FS_COLD = Corner("FS_-40C", kvco=1.15, f0=1.01, icp=0.85, res=0.9, cap=0.95,
                 gm=1.15, tdelay=0.9, pn_db=-1.0, ref_pn_db=-1.0, temp_c=-40.0)

STANDARD_CORNERS = (TT, SS_HOT, FF_COLD, SF_HOT, FS_COLD)

# which corner axis scales which config field, by the field's owner
_MAP = {
    "osc": {"gain": "kvco", "f0": "f0", "band_step_hz": "f0"},
    "cp": {"icp": "icp", "t_reset": "tdelay", "dead_zone_s": "tdelay"},
    "filt": {"r2": "res", "r3": "res", "c1": "cap", "c2": "cap", "c3": "cap"},
    "sampler": {"gm": "gm", "c_samp": "cap", "pulse_width": "tdelay"},
    "tdc": {"t_res": "tdelay"},
}


# dB offsets, which add rather than scale
_DB = {"osc": {"pn_dbchz": "pn_db", "pn_floor_dbchz": "pn_db"}}


def _scaled(sub, axes: dict, corner: Corner, owner: str = ""):
    changes = {}
    have = {f.name for f in fields(sub)}
    for field_name, axis in axes.items():
        if field_name in have:
            k = getattr(corner, axis)
            if k != 1.0:
                changes[field_name] = getattr(sub, field_name) * k
    for field_name, axis in _DB.get(owner, {}).items():
        d = getattr(corner, axis)
        if field_name in have and d != 0.0:
            changes[field_name] = getattr(sub, field_name) + d
    if "temp_k" in have and corner.temp_k != TT.temp_k:
        changes["temp_k"] = corner.temp_k
    return replace(sub, **changes) if changes else sub


def apply_corner(pll, corner: Corner):
    """A copy of `pll` with the corner applied.  The original is untouched.

    The loop is deliberately NOT retuned: a corner analysis asks what the
    nominal design does at that corner, and retuning would answer a different
    question (what a design centred there would do).

    The copy is deep.  ``dataclasses.replace`` only rebuilds the level it is
    handed, so a config whose sub-blocks this corner does not touch would keep
    sharing them with the nominal -- and at TT, which scales nothing, the
    returned PLL would share the whole config.  Since corner_report runs TT
    first, anything downstream that edited a returned config would corrupt the
    baseline for every later corner.
    """
    cfg = deepcopy(pll.cfg)
    changes = {}
    for owner, axes in _MAP.items():
        sub = getattr(cfg, owner, None)
        if sub is not None and hasattr(sub, "__dataclass_fields__"):
            new = _scaled(sub, axes, corner, owner)
            if new is not sub:
                changes[owner] = new
    # Static supply deviation, through the oscillator's own pushing figure.
    # Without this the vdd axis is a decoration: every standard corner names a
    # supply (SS_125C_0.9V) that nothing in the model would ever read.
    osc = changes.get("osc", getattr(cfg, "osc", None))
    if osc is not None and corner.vdd != 1.0 \
            and getattr(osc, "pushing_hz_v", 0.0) != 0.0:
        dv = (corner.vdd - 1.0) * corner.vdd_nominal_v
        changes["osc"] = replace(osc, f0=osc.f0 + osc.pushing_hz_v * dv)
    for name in ("ref_pn_dbchz",):
        if hasattr(cfg, name) and corner.ref_pn_db != 0.0:
            changes[name] = getattr(cfg, name) + corner.ref_pn_db
    frac = getattr(cfg, "frac", None)
    if frac is not None and getattr(frac, "dtc", None) is not None:
        dtc = frac.dtc
        d_changes = {}
        for name in ("t_res", "range_s"):
            if name in {f.name for f in fields(dtc)} and corner.tdelay != 1.0:
                d_changes[name] = getattr(dtc, name) * corner.tdelay
        if d_changes:
            changes["frac"] = replace(frac, dtc=replace(dtc, **d_changes))
    return type(pll)(replace(cfg, **changes) if changes else cfg)


@dataclass
class CornerRow:
    corner: str
    jitter_fs: float
    f_ugb_hz: float
    pm_deg: float
    peaking_db: float
    notes: list[str]
    error: str | None = None


def corner_report(pll, corners=STANDARD_CORNERS) -> list[CornerRow]:
    """analyze() at every corner.  A corner that will not build is a row.

    A config that raises at a corner is a real finding -- a control voltage
    that cannot reach the target, a band bank with a gap -- so it is reported
    rather than allowed to abort the sweep.
    """
    rows = []
    for cn in corners:
        try:
            ar = apply_corner(pll, cn).analyze()
        except Exception as exc:
            rows.append(CornerRow(cn.name, float("nan"), float("nan"),
                                  float("nan"), float("nan"), [], repr(exc)))
            continue
        rows.append(CornerRow(cn.name, ar.jitter_fs, ar.loop.f_ugb,
                              ar.loop.pm_deg, ar.loop.peaking_db, list(ar.notes)))
    return rows


def corner_table(rows) -> str:
    head = (f"{'corner':16s} {'jitter[fs]':>11s} {'UGB[kHz]':>10s} "
            f"{'PM[deg]':>8s} {'peak[dB]':>9s}")
    out = [head, "-" * len(head)]
    for r in rows:
        if r.error:
            out.append(f"{r.corner:16s}  FAILED: {r.error[:60]}")
            continue
        out.append(f"{r.corner:16s} {r.jitter_fs:11.1f} {r.f_ugb_hz / 1e3:10.1f} "
                   f"{r.pm_deg:8.1f} {r.peaking_db:9.2f}")
    return "\n".join(out)


def worst_case(rows, key: str = "jitter_fs") -> CornerRow | None:
    """The corner with the largest value of `key`, ignoring failed rows."""
    ok = [r for r in rows if r.error is None and getattr(r, key) == getattr(r, key)]
    return max(ok, key=lambda r: getattr(r, key)) if ok else None
