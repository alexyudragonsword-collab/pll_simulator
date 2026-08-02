"""Classic charge-pump PLL: integer-N and fractional-N (MASH + optional DTC).

Frequency domain: s-domain linear phase model (continuous approximation,
flagged when UGB > fref/10).  Time domain: reference-edge event-driven
timestamp model — one iteration per reference cycle, closed-form divider edge
times, exact loop-filter updates.  Captures lock acquisition, cycle slips,
reference/fractional spurs and DTC calibration transients.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from ..blocks.chargepump import ChargePump, CPConfig
from ..blocks.loopfilter import FilterDesign, LoopFilter
from ..blocks.oscillator import OscConfig, Oscillator
from ..core.colored import synth_from_psd
from ..core.deltasigma import Mash11, Mash111, Efm1
from ..core.engine import detect_lock, postprocess
from ..core.freqresp import FreqResponse, default_grid, loop_metrics
from ..core.jitter import integrate_pn, ipn_dbc, rms_jitter_fs
from ..core.noise import (CurrentNoise, FlickerFloorPhase, NoisePath,
                          NoiseSource, ResistorNoise, ShapedQuantization,
                          output_psd)
from ..core.results import AnalysisResult, SimResult
from .base import PLLBase

TWOPI = 2.0 * np.pi


def frac_spur_offsets(frac: float, fref: float, kmax: int = 6,
                      fmin: float = 1e3) -> list[float]:
    """Expected fractional-spur offsets: k*frac folded into [0, fref/2]."""
    offs = set()
    for k in range(1, kmax + 1):
        x = (k * frac) % 1.0
        fo = min(x, 1.0 - x) * fref
        if fmin < fo < 0.45 * fref:
            offs.add(round(fo, 3))
    return sorted(offs)


@dataclass
class FracConfig:
    """Fractional-N configuration."""

    frac: float                       # fractional part of N, [0, 1)
    mash_order: int = 3               # 1, 2 or 3
    bits: int = 24
    dtc: "object | None" = None       # DTCConfig, wired by blocks.dtc
    dtc_cal: "object | None" = None   # gain calibrator (LMSGainCal/SignSignLMS)
    dtc_lut_cal: "object | None" = None   # INL calibrator (LUTCal, seconds)

    def make_mash(self):
        return {1: Efm1, 2: Mash11, 3: Mash111}[self.mash_order](self.bits)

    @property
    def frac_word(self) -> int:
        return int(round(self.frac * (1 << self.bits)))


@dataclass
class CPPLLConfig:
    fref: float
    fout: float
    osc: OscConfig
    cp: CPConfig
    filt: FilterDesign
    ref_pn_dbchz: float = -155.0      # reference floor
    ref_pn_fc: float = 20e3           # reference flicker corner
    div_pn_dbchz: float = -160.0      # divider floor (at divider output)
    div_pn_fc: float = 100e3
    frac: FracConfig | None = None
    # reference doubler: fref is the DOUBLED rate; duty-cycle error of the
    # crystal (duty-0.5) makes every other edge early/late -> fref/2 spur
    ref_doubler_duty_err: float = 0.0
    int_band: tuple[float, float] = (1e3, 100e6)

    @property
    def n_div(self) -> float:
        return self.fout / self.fref

    def __post_init__(self):
        n = self.n_div
        if self.frac is None:
            if abs(n - round(n)) > 1e-9:
                raise ValueError(f"fout/fref = {n} is not integer; provide FracConfig")
        else:
            if not (0.0 <= self.frac.frac < 1.0):
                raise ValueError("frac must be in [0,1)")


class CPPLL(PLLBase):
    def __init__(self, cfg: CPPLLConfig):
        self.cfg = cfg

    # ------------------------------------------------------------ analysis
    def analyze(self, f: np.ndarray | None = None) -> AnalysisResult:
        c = self.cfg
        if f is None:
            f = default_grid(1e2, 1e9)
        n = c.n_div
        lf = LoopFilter(c.filt, 1.0 / c.fref)
        z = FreqResponse(f, lf.transimpedance(f))
        # small-signal Kvco at the actual operating point (nonlinearity-aware)
        v_op = c.osc.v_for(c.fout)
        kvco = c.osc.kvco_at(v_op)
        vco_int = FreqResponse.integrator(f, TWOPI * kvco)         # rad/V
        gol = z * vco_int * (c.cp.icp / TWOPI) * (1.0 / n)
        h_lp = gol.feedback()             # phi_ref -> phi_div closed loop
        err = 1.0 / (1.0 + gol)

        cp_blk = ChargePump(c.cp, 1.0 / c.fref, np.random.default_rng(0))

        paths = [
            NoisePath(FlickerFloorPhase.from_spot("ref", c.ref_pn_dbchz, c.ref_pn_fc),
                      h_lp * n),
            NoisePath(FlickerFloorPhase.from_spot("divider", c.div_pn_dbchz, c.div_pn_fc),
                      h_lp * n),
            NoisePath(cp_blk.noise_source(), h_lp * (TWOPI * n / c.cp.icp)),
            NoisePath(ResistorNoise(name="lf_r2", unit="V^2/Hz", r_ohm=c.filt.r2),
                      FreqResponse(f, self._r2_vnode_tf(f)) * vco_int * err),
            NoisePath(c.osc.leeson("vco"), err),
        ]
        if c.filt.order == 3:
            h_r3 = 1.0 / (1.0 + 2j * np.pi * f * c.filt.r3 * c.filt.c3)
            paths.append(NoisePath(ResistorNoise(name="lf_r3", unit="V^2/Hz",
                                                 r_ohm=c.filt.r3),
                                   FreqResponse(f, h_r3) * vco_int * err))
        notes = []
        if c.frac is not None:
            m = c.frac.mash_order
            dsm_src = ShapedQuantization(name="dsm_quant", unit="rad^2/Hz",
                                         q=TWOPI, fs=c.fref, order=m - 1)
            ntf_dsm = h_lp
            if c.frac.dtc is not None:
                eps = getattr(c.frac.dtc, "gain_error_residual", 0.01)
                ntf_dsm = h_lp * eps
                notes.append(f"DSM noise after DTC cancellation, residual gain error {eps * 100:.1f}%")
                q_dtc = getattr(c.frac.dtc, "t_res", 0.0)
                if q_dtc > 0:
                    paths.append(NoisePath(
                        ShapedQuantization(name="dtc_quant", unit="rad^2/Hz",
                                           q=TWOPI * q_dtc * c.fout, fs=c.fref, order=0),
                        h_lp))
                # DTC.delay adds this in the time domain every cycle, so the
                # budget has to carry it too (sampled -> 2*sigma^2/fref)
                j_dtc = getattr(c.frac.dtc, "jitter_rms_s", 0.0)
                if j_dtc > 0:
                    paths.append(NoisePath(
                        NoiseSource(name="dtc_jitter", unit="rad^2/Hz",
                                    level=2.0 * (TWOPI * c.fout * j_dtc) ** 2
                                    / c.fref), h_lp))
            paths.append(NoisePath(dsm_src, ntf_dsm))

        m = loop_metrics(gol)
        if m.f_ugb > c.fref / 10:
            notes.append(f"UGB {m.f_ugb / 1e6:.1f} MHz > fref/10: continuous-time "
                         "approximation degrading")
        if kvco != c.osc.gain:
            notes.append(f"Kvco at v_op={v_op:.3f} V: {kvco / 1e6:.1f} MHz/V "
                         f"(nominal {c.osc.gain / 1e6:.1f})")
            if kvco < 0.2 * c.osc.gain:
                notes.append("WARNING: Kvco collapsed >5x at this operating "
                             "point — target near the edge of the tuning "
                             "range; loop gain and stability unreliable")
        bd = output_psd(paths, f)
        jit = rms_jitter_fs(f, bd["total"], c.fout, *c.int_band)
        spurs = {"ref_spur": self._ref_spur_dbc(z)}
        if c.frac is not None:
            fo = min(c.frac.frac, 1 - c.frac.frac) * c.fref
            spurs["frac_offset_hz"] = fo
            if c.frac.dtc is not None:
                from ..core.dtcspurs import dtc_spur_table
                eps = getattr(c.frac.dtc, "gain_error_residual", 0.01)
                for off, dbc in dtc_spur_table(
                        c.frac, lambda r: r / c.fout, c.fref, c.fout,
                        ntf=h_lp, gain_eps=eps).items():
                    spurs[f"frac_spur@{off:.0f}Hz"] = dbc
        return AnalysisResult(
            f=f, f0=c.fout, pn_breakdown=bd, loop=m,
            jitter_fs=jit, ipn_dbc=ipn_dbc(f, bd["total"], *c.int_band),
            int_band=c.int_band, spurs_analytic=spurs,
            ntfs={"gol": gol, "h_lp": h_lp, "err": err}, notes=notes)

    def _r2_vnode_tf(self, f: np.ndarray) -> np.ndarray:
        """R2 thermal voltage -> control-node voltage (series R2-C1 loop with C2)."""
        c = self.cfg.filt
        s = 2j * np.pi * f
        zc1 = 1.0 / (s * c.c1)
        zc2 = 1.0 / (s * c.c2)
        return zc2 / (c.r2 + zc1 + zc2)

    def _ref_spur_dbc(self, z: FreqResponse) -> float:
        """Reference spur from CP mismatch + leakage ripple (narrowband FM)."""
        c = self.cfg
        dq = abs(c.cp.icp * 0.01 * c.cp.mismatch_pct * c.cp.t_reset) \
            + abs(c.cp.leakage_a / c.fref)
        zf = np.interp(np.log10(c.fref), np.log10(z.f), np.abs(z.h))
        # dq once per period -> fundamental of PEAK current 2*dq*fref
        v1 = 2.0 * dq * c.fref * zf               # peak control ripple [V]
        beta = c.osc.gain * v1 / c.fref           # FM modulation index
        return float(20.0 * np.log10(max(beta / 2.0, 1e-30)))

    # ----------------------------------------------------------- simulation
    def simulate(self, n_cycles: int, *, noise: bool = True, calibration: bool = True,
                 seed: int = 0, f_start_offset: float = 0.0,
                 dtc_gain_init_error: float = 0.0,
                 supply_ripple: tuple[float, float] | None = None,
                 band_select: bool = True,
                 dtc_gain_drift: np.ndarray | None = None) -> SimResult:
        """supply_ripple: (amplitude_v, freq_hz) sine on the VCO supply,
        converted to frequency via osc.pushing_hz_v.
        band_select: run the coarse binary band search before closing the
        loop when the oscillator has multiple bands."""
        c = self.cfg
        rng = np.random.default_rng(seed)
        tref = 1.0 / c.fref
        n_nom = c.n_div

        lf = LoopFilter(c.filt, tref)
        osc = Oscillator(c.osc, c.fref, rng, noise=noise)
        band_trace = None
        if c.osc.n_bands > 1 and band_select:
            from ..calibration.gain_cal import BandSelect
            bs = BandSelect(c.osc.n_bands, c.fout)
            while not bs.done:
                osc.band = bs.band
                f_meas = osc.freq(0.0)
                if noise:   # counter accuracy over meas_n reference cycles
                    f_meas += rng.normal(0.0, c.fref / (bs.meas_n * np.sqrt(12)))
                bs.observe(f_meas)
            osc.band = bs.band
            band_trace = np.asarray(bs.trace, dtype=float)
            lf.reset(f_start_offset / c.osc.gain)   # vctrl starts mid-band
        else:
            lf.reset(c.osc.v_for(c.fout) + f_start_offset / c.osc.gain)
        cp = ChargePump(c.cp, tref, rng, noise=noise)

        if supply_ripple is not None:
            amp_sup, f_sup = supply_ripple
            v_sup = amp_sup * np.sin(TWOPI * f_sup * np.arange(n_cycles) * tref)
        else:
            v_sup = np.zeros(n_cycles)

        # pre-synthesized reference + divider phase-noise time jitter [s]
        if noise:
            ref_src = FlickerFloorPhase.from_spot("ref", c.ref_pn_dbchz, c.ref_pn_fc)
            div_src = FlickerFloorPhase.from_spot("div", c.div_pn_dbchz, c.div_pn_fc)
            jit_ref = synth_from_psd(ref_src.psd, c.fref, n_cycles, rng) / (TWOPI * c.fref)
            jit_div = synth_from_psd(div_src.psd, c.fref, n_cycles, rng) / (TWOPI * c.fref)
        else:
            jit_ref = np.zeros(n_cycles)
            jit_div = np.zeros(n_cycles)
        if c.ref_doubler_duty_err != 0.0:
            # alternating edge displacement: (duty-0.5)*T_xtal = err*2*tref,
            # split +/- around the mean -> square wave at fref/2
            jit_ref = jit_ref + c.ref_doubler_duty_err * tref \
                * np.where(np.arange(n_cycles) % 2 == 0, 1.0, -1.0)

        mash = c.frac.make_mash() if c.frac is not None else None
        frac_word = c.frac.frac_word if c.frac is not None else 0

        # optional DTC (wired when blocks.dtc present in config)
        dtc = None
        dtc_cal = None
        lut_cal = None
        if c.frac is not None and c.frac.dtc is not None:
            from ..blocks.dtc import DTC
            dtc = DTC(c.frac.dtc, rng, noise=noise,
                      gain_error=dtc_gain_init_error)
            if calibration:
                dtc_cal = c.frac.dtc_cal
                lut_cal = c.frac.dtc_lut_cal

        t_div = 0.0
        phi_out = 0.0        # true output phase deviation vs ideal fout timebase
        phase_err = np.empty(n_cycles)
        freq_out = np.empty(n_cycles)
        vctrl_rec = np.empty(n_cycles)
        cal_trace = np.empty(n_cycles) if dtc_cal is not None else None
        osc_noise = osc.noise_steps(n_cycles) if noise else np.zeros(n_cycles)
        prev_osc_phi = 0.0
        fv = osc.freq(lf.vctrl, v_sup[0])
        n_next = n_nom if mash is None else int(c.fout // c.fref)

        for n in range(n_cycles):
            t_ref = n * tref + jit_ref[n]
            residual_ui = 0.0
            if mash is not None:
                residual_ui = mash.residual_ui()
            if dtc is not None:
                if dtc_gain_drift is not None:
                    dtc.gain_error = dtc_gain_drift[n]
                # positive residual = divider has counted extra cycles = its edge
                # is late by residual*Tvco; delay the reference edge to match
                # (DTC adds a static mid-range offset, absorbed as phase offset)
                t_target = residual_ui / c.fout
                if lut_cal is not None:
                    t_target += lut_cal.correction(residual_ui)
                t_ref += dtc.delay(t_target)
            dt = t_div + jit_div[n] - t_ref
            dt_eff = min(max(dt, -0.45 * tref), 0.45 * tref)   # PFD slip clamp
            dq = cp.charge(dt_eff)
            t_on = min(abs(dt_eff) + c.cp.t_reset, 0.9 * tref)
            lf.update_pulse(dq / t_on, t_on)
            fv = osc.freq(lf.vctrl, v_sup[n])
            fv = max(fv, 0.05 * c.osc.f0)

            if dtc_cal is not None:
                # under-delayed reference (gain_corr low) makes dt correlate
                # positively with the requested delay -> positive-sign update
                dtc_cal.step(np.sign(dt), residual_ui)
                dtc.gain_corr = dtc_cal.value
                cal_trace[n] = dtc_cal.value
            if lut_cal is not None:
                lut_cal.step(dt, residual_ui)

            if mash is not None:
                n_next = int(c.fout // c.fref) + mash.step(frac_word)
            # divider edge advance: N cycles of the VCO at current freq,
            # oscillator accumulated phase noise shifts the edge
            d_osc = osc_noise[n] - prev_osc_phi
            prev_osc_phi = osc_noise[n]
            t_div += n_next / fv - d_osc / (TWOPI * fv)

            # output phase deviation = integrated frequency error + osc noise
            # (the divider-edge wobble from the DSM is NOT output phase — the
            # loop lowpasses it; the VCO only sees it through vctrl)
            phi_out += TWOPI * (fv - c.fout) * tref + d_osc
            phase_err[n] = phi_out
            freq_out[n] = fv
            vctrl_rec[n] = lf.vctrl

        t = np.arange(n_cycles) * tref
        lock = detect_lock(t, freq_out - c.fout, tol_hz=c.fout * 1e-5)
        sim = SimResult(fs=c.fref, f0=c.fout, t=t,
                        phase_err_out=phase_err, freq_out=freq_out, ctrl=vctrl_rec,
                        lock_time_s=lock)
        if dtc_cal is not None:
            sim.cal_traces["dtc_gain"] = cal_trace
        if band_trace is not None:
            sim.cal_traces["band_select"] = band_trace
            sim.extra["band"] = osc.band
        spur_offsets = None
        if c.frac is not None:
            spur_offsets = frac_spur_offsets(c.frac.frac, c.fref,
                                             fmin=8.0 * c.fref / n_cycles)
        if supply_ripple is not None and supply_ripple[1] < 0.45 * c.fref:
            spur_offsets = (spur_offsets or []) + [supply_ripple[1]]
        if c.ref_doubler_duty_err != 0.0:
            spur_offsets = (spur_offsets or []) + [c.fref / 2.0]
        return postprocess(sim, settle_frac=0.25, int_band=c.int_band,
                           spur_offsets=spur_offsets)
