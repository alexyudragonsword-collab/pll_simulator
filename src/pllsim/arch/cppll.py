"""Classic charge-pump PLL: integer-N and fractional-N (MASH + optional DTC).

Frequency domain: s-domain linear phase model (continuous approximation,
flagged when UGB > fref/10).  Time domain: reference-edge event-driven
timestamp model — one iteration per reference cycle, closed-form divider edge
times, exact loop-filter updates.  Captures lock acquisition, cycle slips,
reference/fractional spurs and DTC calibration transients.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from ..blocks.chargepump import (
    CP_DEAD,
    CP_I2,
    CP_ICP,
    CP_LEAK,
    CP_LEAK_SLOPE,
    CP_MM,
    CP_MM_SLOPE,
    CP_TRESET,
    CP_VREF,
    CP_WRAP,
    ChargePump,
    CPConfig,
    cp_charge_det,
    cp_noise_sigma,
    cp_segments,
    pfd_error,
)
from ..blocks.dtc import DTCConfig, dtc_code, dtc_inl_s, dtc_time
from ..blocks.lockdetect import lockdet_step
from ..blocks.loopfilter import FilterDesign, LoopFilter, lf_drive_fine, lf_pulse
from ..blocks.oscillator import OscConfig, Oscillator, osc_freq
from ..calibration.lms import lms_step, lut_bin, lut_step
from ..core.colored import synth_from_psd
from ..core.deltasigma import Efm1, Mash11, Mash111, mash_residual, mash_step
from ..core.dtcspurs import frac_spur_offsets
from ..core.engine import detect_lock, postprocess
from ..core.freqresp import FreqResponse, default_grid, loop_metrics
from ..core.jit import kernel, sgn
from ..core.jitter import ipn_dbc, rms_jitter_fs
from ..core.noise import (
    FlickerFloorPhase,
    NoisePath,
    NoiseSource,
    ResistorNoise,
    ShapedQuantization,
    output_psd,
)
from ..core.results import AnalysisResult, SimResult
from .base import (
    PLLBase,
    add_pull_offset,
    attach_fine,
    cal_kernel_args,
    dtc_kernel_args,
    dtc_t_target_of,
    flicker_corner_hz,
    lockdet_kernel_args,
    lut_kernel_args,
    mash_kernel_args,
    no_fine_note,
    osc_law_args,
    pull_hz,
    pull_notes,
    pull_spur,
    run_band_select,
    supply_ripple_v,
    tuning_notes,
    tuning_sim_notes,
)

TWOPI = 2.0 * np.pi


@dataclass
class FracConfig:
    """Fractional-N configuration."""

    frac: float                       # fractional part of N, [0, 1)
    mash_order: int = 3               # 1, 2 or 3
    bits: int = 24
    dtc: DTCConfig | None = None      # wired by blocks.dtc
    dtc_cal: object | None = None   # gain calibrator (LMSGainCal/SignSignLMS)
    dtc_lut_cal: object | None = None   # INL calibrator (LUTCal, seconds)

    def __post_init__(self):
        if not 0.0 <= self.frac < 1.0:
            raise ValueError(f"FracConfig frac must be in [0, 1), got {self.frac}")
        if self.mash_order not in (1, 2, 3):
            raise ValueError(f"FracConfig mash_order must be 1, 2 or 3, got {self.mash_order}")
        if not 1 <= int(self.bits) <= 32:
            raise ValueError(f"FracConfig bits must be in 1..32, got {self.bits}")

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
    # A retiming flip-flop re-clocks the divider output on a VCO edge, so the
    # divider chain's own jitter never reaches the PFD -- only the retiming
    # flop's does.  This is why a ripple divider's noise usually does not show
    # up in a measured spectrum, and why the divider_pn number quoted in a
    # datasheet often does not matter.  The flop is not free: it adds its own
    # aperture jitter, and it costs a full VCO period of latency.
    divider_retimed: bool = False
    retime_jitter_rms_s: float = 0.0
    lock_detect: object | None = None    # blocks.lockdetect.LockDetectConfig
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
            if abs((self.fout / self.fref) % 1.0 - self.frac.frac) > 1e-6:
                raise ValueError(
                    f"fout/fref fractional part {(self.fout / self.fref) % 1.0:.6f} "
                    f"does not match FracConfig.frac {self.frac.frac}: the divider "
                    f"locks at (n_int + frac)*fref, not at fout -- change fout or "
                    f"frac together with fref")


@kernel
def cppll_kernel(n_cycles: int, tref: float, fout: float, f_floor: float,
                 n_nom: float, n_int: int,
                 band: int, f0: float, gain: float, nl1: float, nl2: float,
                 band_step: float, n_bands: int, v_lo: float, v_hi: float,
                 pushing: float, v_sup: np.ndarray, f_pull: np.ndarray,
                 osc_noise: np.ndarray, jit_ref: np.ndarray, jit_div: np.ndarray,
                 noise_on: bool, zn: np.ndarray,
                 has_mash: bool, mash_order: int, mash_bits: int, mash_st: np.ndarray,
                 frac_word: int,
                 has_dtc: bool, dtc_range_s: float, dtc_t_res: float, dtc_code_max: int,
                 dtc_inl_poly: np.ndarray, dtc_has_sin: bool, dtc_sin_amp: float,
                 dtc_sin_cyc: float, dtc_sin_ph: float, dtc_jitter: float,
                 dtc_gain_error: float, has_drift: bool, dtc_gain_drift: np.ndarray,
                 has_cal: bool, cal_kind: int, cal_st: np.ndarray, cal_mu: float,
                 cal_mu_final: float, cal_gear: float, cal_ema: float, cal_center: bool,
                 cal_trace: np.ndarray,
                 has_lut: bool, lut: np.ndarray, lut_counts: np.ndarray, lut_xs: np.ndarray,
                 lut_st: np.ndarray, lut_lo: float, lut_hi: float, lut_k: int,
                 lut_mu: float, lut_ema: float, lut_ortho: int, lut_snaps: np.ndarray,
                 cp_p: np.ndarray, has_flicker: bool, cp_flicker: np.ndarray,
                 lf_x: np.ndarray, lf_ad: np.ndarray, lf_b: np.ndarray, lf_w: np.ndarray,
                 lf_v: np.ndarray, lf_vinv: np.ndarray, lf_vinv_b: np.ndarray,
                 lf_tmp: np.ndarray, lf_xe: np.ndarray, lf_xe0: np.ndarray,
                 has_det: bool, det_st: np.ndarray, det_window: float, det_count: int,
                 det_down: int, det_trace: np.ndarray,
                 m_os: int, fine: np.ndarray, f_sub: np.ndarray, seg_amp: np.ndarray,
                 seg_dur: np.ndarray, vs: np.ndarray,
                 phase_err: np.ndarray, freq_out: np.ndarray, vctrl_rec: np.ndarray
                 ) -> tuple[int, int, int, int]:
    """The reference-edge loop, one iteration per cycle: MASH residue and DTC,
    PFD, charge pump into the filter, VCO, divider edge.  Returns (cycle
    slips, PFD out-of-range cycles, LUT snapshots taken, normal draws
    consumed).  Block state lives in the arrays passed in; the caller copies
    it back into the block objects."""
    icp = cp_p[CP_ICP]
    mm_pct = cp_p[CP_MM]
    mm_slope = cp_p[CP_MM_SLOPE]
    v_ref = cp_p[CP_VREF]
    t_reset = cp_p[CP_TRESET]
    dead_zone = cp_p[CP_DEAD]
    leak_a = cp_p[CP_LEAK]
    leak_slope = cp_p[CP_LEAK_SLOPE]
    i2 = cp_p[CP_I2]
    wrap = cp_p[CP_WRAP] != 0.0
    nlf = lf_x.shape[0]
    sub = tref / m_os

    t_div = 0.0
    phi_out = 0.0        # true output phase deviation vs ideal fout timebase
    prev_osc_phi = 0.0
    gain_corr = 1.0
    gain_err = dtc_gain_error
    n_next = n_nom if not has_mash else float(n_int)
    n_slips = 0
    n_oor = 0
    n_snap = 0
    zi = 0
    fv = osc_freq(lf_x[nlf - 1], band, v_sup[0], 0.0, pushing, f0, gain, nl1, nl2,
                  band_step, n_bands, v_lo, v_hi)

    for n in range(n_cycles):
        t_ref = n * tref + jit_ref[n]
        residual_ui = 0.0
        if has_mash:
            residual_ui = mash_residual(mash_bits, mash_st)
        if has_dtc:
            if has_drift:
                gain_err = dtc_gain_drift[n]
            # positive residual = divider has counted extra cycles = its edge
            # is late by residual*Tvco; delay the reference edge to match
            # (DTC adds a static mid-range offset, absorbed as phase offset)
            t_target = residual_ui / fout
            if has_lut:
                t_target += lut[lut_bin(residual_ui, lut_lo, lut_hi, lut_k)]
            code = dtc_code(t_target, dtc_range_s, gain_corr, dtc_t_res, dtc_code_max)
            inl = dtc_inl_s(code, dtc_code_max, dtc_inl_poly, dtc_has_sin, dtc_sin_amp,
                            dtc_sin_cyc, dtc_sin_ph)
            d = dtc_time(code, dtc_t_res, gain_err, inl)
            if noise_on and dtc_jitter > 0:
                d += dtc_jitter * zn[zi]
                zi += 1
            t_ref += d
        dt = t_div + jit_div[n] - t_ref
        dt_eff, out_of_range = pfd_error(dt, tref, wrap)
        if out_of_range:
            n_oor += 1
            # a saturating detector cannot slip by construction; only the
            # wrapping one reverses its own error signal
            if wrap:
                n_slips += 1
        if has_det:
            det_trace[n] = 1.0 if lockdet_step(det_st, dt, det_window, det_count,
                                               det_down) else 0.0
        v = lf_x[nlf - 1]
        # the stochastic charge of this cycle: one thermal draw and one
        # sample of the primed 1/f sequence, whichever level of detail follows
        dq_noise = 0.0
        if noise_on:
            dq_noise = cp_noise_sigma(dt_eff, t_reset, i2) * zn[zi]
            zi += 1
            dq_noise += cp_flicker[n] if has_flicker else 0.0
        if m_os == 1:
            dq = cp_charge_det(dt_eff, v, icp, mm_pct, mm_slope, v_ref, t_reset,
                               dead_zone, leak_a, leak_slope, tref) + dq_noise
            t_on = min(abs(dt_eff) + t_reset, 0.9 * tref)
            lf_pulse(lf_x, lf_ad, lf_b, lf_w, lf_v, lf_vinv, lf_vinv_b, dq / t_on, t_on,
                     tref, lf_tmp, lf_xe)
            fv = max(osc_freq(lf_x[nlf - 1], band, v_sup[n], f_pull[n], pushing, f0,
                              gain, nl1, nl2, band_step, n_bands, v_lo, v_hi), f_floor)
        else:
            # drive the filter with the actual CP current waveform instead
            # of one net pulse: the up/down segments cancel in area but not
            # in time, and that residue IS the reference spur
            nseg = cp_segments(dt_eff, v, icp, mm_pct, mm_slope, v_ref, t_reset,
                               dead_zone, seg_amp, seg_dur)
            i_bias = leak_a + leak_slope * (v - v_ref)
            lf_drive_fine(lf_x, lf_w, lf_v, lf_vinv, lf_vinv_b, tref, seg_amp, seg_dur,
                          nseg, m_os, i_bias, dq_noise, vs, lf_xe0, lf_xe)
            for k in range(m_os):
                f_sub[k] = max(osc_freq(vs[k], band, v_sup[n], f_pull[n], pushing, f0,
                                        gain, nl1, nl2, band_step, n_bands, v_lo, v_hi),
                               f_floor)
            fv = f_sub[m_os - 1]

        if has_cal and has_dtc:
            # under-delayed reference (gain_corr low) makes dt correlate
            # positively with the requested delay -> positive-sign update
            gain_corr = lms_step(cal_kind, cal_st, sgn(dt), residual_ui, cal_mu,
                                 cal_mu_final, cal_gear, cal_ema, cal_center)
            cal_trace[n] = gain_corr
        if has_lut:
            n_snap = lut_step(lut, lut_counts, lut_xs, lut_st, dt, residual_ui, lut_lo,
                              lut_hi, lut_k, lut_mu, lut_ema, lut_ortho, lut_snaps,
                              n_snap)

        if has_mash:
            n_next = float(n_int + mash_step(mash_order, mash_bits, mash_st, frac_word))
        # divider edge advance: N cycles of the VCO at current freq,
        # oscillator accumulated phase noise shifts the edge
        d_osc = osc_noise[n] - prev_osc_phi
        prev_osc_phi = osc_noise[n]
        t_div += n_next / fv - d_osc / (TWOPI * fv)

        # output phase deviation = integrated frequency error + osc noise
        # (the divider-edge wobble from the DSM is NOT output phase — the
        # loop lowpasses it; the VCO only sees it through vctrl)
        if m_os == 1:
            phi_out += TWOPI * (fv - fout) * tref + d_osc
        else:
            # integrate the sub-samples instead of holding the end-of-
            # period frequency across the whole period; the oscillator's
            # own phase step is spread evenly over the M sub-intervals
            cs = 0.0
            for k in range(m_os):
                cs += TWOPI * (f_sub[k] - fout) * sub + d_osc / m_os
                fine[n * m_os + k] = phi_out + cs
            phi_out = fine[(n + 1) * m_os - 1]
        phase_err[n] = phi_out
        freq_out[n] = fv
        vctrl_rec[n] = lf_x[nlf - 1]
    return n_slips, n_oor, n_snap, zi


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
            NoisePath(cp_blk.noise_source(), h_lp * (TWOPI * n / c.cp.icp)),
            NoisePath(ResistorNoise(name="lf_r2", unit="V^2/Hz", r_ohm=c.filt.r2),
                      FreqResponse(f, self._r2_vnode_tf(f)) * vco_int * err),
            NoisePath(c.osc.leeson("vco"), err),
        ]
        notes = []
        if c.divider_retimed:
            # the retiming flop replaces the divider chain's accumulated jitter
            # with its own aperture jitter, referred to the PFD as a sampled
            # timing error (2*sigma^2/fref into the one-sided PSD)
            if c.retime_jitter_rms_s > 0:
                paths.append(NoisePath(
                    NoiseSource(name="retime_ff", unit="rad^2/Hz",
                                level=2.0 * (TWOPI * c.fref
                                             * c.retime_jitter_rms_s) ** 2
                                / c.fref), h_lp * n))
            notes.append("divider retimed on a VCO edge: the divider chain's "
                         "own phase noise never reaches the PFD")
        else:
            paths.append(NoisePath(
                FlickerFloorPhase.from_spot("divider", c.div_pn_dbchz,
                                            c.div_pn_fc), h_lp * n))
        if c.filt.order == 3:
            h_r3 = 1.0 / (1.0 + 2j * np.pi * f * c.filt.r3 * c.filt.c3)
            paths.append(NoisePath(ResistorNoise(name="lf_r3", unit="V^2/Hz",
                                                 r_ohm=c.filt.r3),
                                   FreqResponse(f, h_r3) * vco_int * err))
        if c.cp.dead_zone_s > 0:
            notes.append(
                f"PFD dead zone {c.cp.dead_zone_s * 1e12:.1f} ps: the loop has "
                "NO gain inside it, so this linear model overstates in-band "
                "rejection — run simulate() to see the resulting wander")
        if c.cp.pfd_mode == "wrap":
            notes.append("tri-state PFD (wrap): linear only over +/-2pi, so "
                         "acquisition from a large frequency error slips "
                         "cycles; the linear model above assumes no slipping")
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

        m = loop_metrics(gol, f_limit=c.fref / 2)
        from ..core.boundaries import CT_UGB_RATIO, ct_approx_exceeded
        if ct_approx_exceeded(m.f_ugb, c.fref):
            notes.append(f"UGB {m.f_ugb / 1e6:.1f} MHz > fref/"
                         f"{CT_UGB_RATIO:.0f}: continuous-time "
                         "approximation degrading")
        from ..core.boundaries import conditionally_stable
        if conditionally_stable(m.n_crossings):
            notes.append(
                f"open loop crosses unity gain {m.n_crossings}x below "
                "fref/2: conditionally stable — phase margin at the first "
                "crossing does not describe the loop")
        if kvco != c.osc.gain:
            notes.append(f"Kvco at v_op={v_op:.3f} V: {kvco / 1e6:.1f} MHz/V "
                         f"(nominal {c.osc.gain / 1e6:.1f})")
            if kvco < 0.2 * c.osc.gain:
                notes.append("WARNING: Kvco collapsed >5x at this operating "
                             "point — target near the edge of the tuning "
                             "range; loop gain and stability unreliable")
        notes.extend(tuning_notes(c.osc, v_op))
        bd = output_psd(paths, f)
        jit = rms_jitter_fs(f, bd["total"], c.fout, *c.int_band)
        ref_spur = self._ref_spur_dbc(z)
        spurs = {} if ref_spur == float("-inf") else {"ref_spur": ref_spur}
        spurs.update(pull_spur(c.osc, err))
        notes.extend(pull_notes(c.osc))
        if c.frac is not None:
            fo = min(c.frac.frac, 1 - c.frac.frac) * c.fref
            spurs["frac_offset_hz"] = fo
            if c.frac.dtc is not None:
                from ..core.dtcspurs import dtc_spur_table
                eps = getattr(c.frac.dtc, "gain_error_residual", 0.01)
                for off, dbc in dtc_spur_table(
                        c.frac, dtc_t_target_of(self), c.fref, c.fout,
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

    def _ref_spur_dbc(self, z: FreqResponse, vctrl: float | None = None) -> float:
        """Reference spur from CP mismatch + leakage ripple (narrowband FM).

        Evaluated at the control voltage the loop actually parks at, so a
        mismatch that varies across the tuning range gives the spur that
        channel really has rather than one number for the whole band.
        """
        c = self.cfg
        v = c.osc.v_for(c.fout) if vctrl is None else vctrl
        cp = ChargePump(c.cp, 1.0 / c.fref, np.random.default_rng(0), noise=False)
        zf = np.interp(np.log10(c.fref), np.log10(z.f), np.abs(z.h))
        v1 = cp.ripple_fundamental_a(v) * zf      # peak control ripple [V]
        if v1 <= 0.0:
            # no mismatch and no leakage means no ripple and so no spur; a
            # made-up floor like -600 dBc reads as a measurement, not an absence
            return float("-inf")
        beta = c.osc.kvco_at(v) * v1 / c.fref     # FM modulation index
        return float(20.0 * np.log10(beta / 2.0))

    def ref_spur_vs_channel(self, fouts) -> dict[float, float]:
        """Reference spur [dBc] across output frequencies, keyed by channel.

        The measurement a constant mismatch cannot reproduce: with a
        control-voltage-dependent mismatch this traces the V-shape, lowest near
        the crossing voltage and rising toward both ends of the tuning range.

        Requested frequencies are snapped to reachable channels -- integer
        multiples of fref for an integer-N config -- and the keys are the
        channels actually evaluated, so a caller can hand it a linspace.
        """
        from dataclasses import replace
        lf = LoopFilter(self.cfg.filt, 1.0 / self.cfg.fref)
        fgrid = default_grid(1e2, 1e9)
        z = FreqResponse(fgrid, lf.transimpedance(fgrid))
        out = {}
        for fo in fouts:
            fo = float(fo)
            if self.cfg.frac is None:
                fo = round(fo / self.cfg.fref) * self.cfg.fref
            sub = CPPLL(replace(self.cfg, fout=fo))
            out[fo] = sub._ref_spur_dbc(z)
        return out

    # ----------------------------------------------------------- simulation
    def simulate(self, n_cycles: int, *, noise: bool = True, calibration: bool = True,
                 seed: int = 0, f_start_offset: float = 0.0,
                 dtc_gain_init_error: float = 0.0,
                 supply_ripple: tuple[float, float] | None = None,
                 band_select: bool = True,
                 fine_oversample: int = 1,
                 dtc_gain_drift: np.ndarray | None = None) -> SimResult:
        """supply_ripple: (amplitude_v, freq_hz) sine on the VCO supply,
        converted to frequency via osc.pushing_hz_v.
        band_select: run the coarse binary band search before closing the
        loop when the oscillator has multiple bands.
        fine_oversample: record M control-voltage samples per reference period
        instead of one.  The control ripple that makes the reference spur lives
        entirely inside one period, so at M=1 the spur sits exactly at the
        record's own sampling rate and aliases to DC -- analyze() has always
        predicted a reference spur that the time domain could not show.  M>=8
        makes it observable, at M times the phase-record memory."""
        c = self.cfg
        rng = np.random.default_rng(seed)
        tref = 1.0 / c.fref
        n_nom = c.n_div

        lf = LoopFilter(c.filt, tref)
        osc = Oscillator(c.osc, c.fref, rng, noise=noise)
        band_trace = run_band_select(osc, c, rng, noise, band_select)
        if band_trace is not None:
            lf.reset(f_start_offset / c.osc.gain)   # vctrl starts mid-band
        else:
            lf.reset(c.osc.v_for(c.fout) + f_start_offset / c.osc.gain)
        cp = ChargePump(c.cp, tref, rng, noise=noise)
        cp.prime_flicker(n_cycles)      # 1/f charge sequence for this run

        v_sup = supply_ripple_v(supply_ripple, n_cycles, tref)
        f_pull = pull_hz(c.osc, n_cycles, tref)

        # pre-synthesized reference + divider phase-noise time jitter [s]
        if noise:
            ref_src = FlickerFloorPhase.from_spot("ref", c.ref_pn_dbchz, c.ref_pn_fc)
            div_src = FlickerFloorPhase.from_spot("div", c.div_pn_dbchz, c.div_pn_fc)
            jit_ref = synth_from_psd(ref_src.psd, c.fref, n_cycles, rng) / (TWOPI * c.fref)
            if c.divider_retimed:
                # a VCO-clocked flop re-issues the edge, so the chain's own
                # accumulated jitter is discarded and only the flop's aperture
                # jitter survives
                jit_div = (rng.normal(0.0, c.retime_jitter_rms_s, n_cycles)
                           if c.retime_jitter_rms_s > 0 else np.zeros(n_cycles))
            else:
                jit_div = synth_from_psd(div_src.psd, c.fref, n_cycles,
                                         rng) / (TWOPI * c.fref)
        else:
            jit_ref = np.zeros(n_cycles)
            jit_div = np.zeros(n_cycles)
        if c.ref_doubler_duty_err != 0.0:
            # alternating edge displacement: (duty-0.5)*T_xtal = err*2*tref,
            # split +/- around the mean -> square wave at fref/2
            jit_ref = jit_ref + c.ref_doubler_duty_err * tref \
                * np.where(np.arange(n_cycles) % 2 == 0, 1.0, -1.0)

        mash = c.frac.make_mash() if c.frac is not None else None

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

        det = None
        if c.lock_detect is not None:
            from ..blocks.lockdetect import LockDetector
            det = LockDetector(c.lock_detect)

        phase_err = np.empty(n_cycles)
        freq_out = np.empty(n_cycles)
        vctrl_rec = np.empty(n_cycles)
        cal_trace = np.empty(n_cycles if dtc_cal is not None else 0)
        osc_noise = osc.noise_steps(n_cycles) if noise else np.zeros(n_cycles)
        m_os = max(int(fine_oversample), 1)
        fine_rec = np.empty(n_cycles * m_os) if m_os > 1 else np.empty(0)
        # at most two draws per cycle (DTC jitter, charge-pump thermal
        # charge), from a pool in the order the loop consumes them
        zn = rng.standard_normal(2 * n_cycles) if noise else np.zeros(0)
        dtc_args = dtc_kernel_args(c.frac.dtc if c.frac is not None else None)
        mash_args = mash_kernel_args(mash, c.frac)
        cal_args = cal_kernel_args(dtc_cal)
        cal_st = cal_args[2]
        lut_args = lut_kernel_args(lut_cal, n_cycles)
        lut_st, lut_snaps = lut_args[4], lut_args[11]
        det_trace = np.empty(n_cycles if det is not None else 0)
        args: tuple[Any, ...] = (
            n_cycles, tref, float(c.fout), 0.05 * c.osc.f0, float(n_nom),
            int(c.fout // c.fref), int(osc.band), *osc_law_args(c.osc),
            float(c.osc.pushing_hz_v), v_sup, f_pull, osc_noise, jit_ref, jit_div,
            bool(noise), zn,
            *mash_args, dtc is not None, *dtc_args,
            float(dtc_gain_init_error), dtc_gain_drift is not None,
            (np.asarray(dtc_gain_drift, dtype=float) if dtc_gain_drift is not None
             else np.zeros(0)),
            *cal_args, cal_trace,
            *lut_args,
            c.cp.params(), cp._flicker is not None,
            cp._flicker if cp._flicker is not None else np.zeros(0),
            lf.x, lf.ad, lf.b, lf._w, lf._v, lf._vinv, lf._vinv_b, lf._tmp, lf._xe,
            lf._xe0,
            *lockdet_kernel_args(det), det_trace,
            m_os, fine_rec, np.empty(m_os), np.empty(2), np.empty(2), np.empty(m_os),
            phase_err, freq_out, vctrl_rec)
        n_slips, n_oor, n_snap, _ = cppll_kernel(*args)
        if dtc_cal is not None:
            dtc_cal.load_state(cal_st)
            dtc_cal.trace.extend(cal_trace.tolist())
        if lut_cal is not None:
            lut_cal.load_state(lut_st)
            lut_cal.trace.extend(lut_snaps[i].copy() for i in range(n_snap))
        if det is not None:
            det.trace.extend(det_trace.tolist())
        fine: np.ndarray | None = fine_rec if m_os > 1 else None

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
        sim.extra["cycle_slips"] = n_slips
        sim.extra["pfd_out_of_range_cycles"] = n_oor
        if n_slips:
            sim.notes.append(
                f"{n_slips} cycle slips: the wrapping PFD reversed its own "
                "error signal, so acquisition here is nothing like what the "
                "linear model predicts")
        elif n_oor:
            sim.notes.append(
                f"PFD saturated on {n_oor} cycles: the clamping detector held "
                "at its limit instead of slipping — set cp.pfd_mode='wrap' for "
                "a tri-state PFD, which slips instead")
        if det is not None:
            from ..blocks.lockdetect import LockStats
            sim.cal_traces["lock_detect"] = det.trace_array
            st = LockStats.from_trace(det.trace_array, tref, det.first_lock_cycle)
            sim.extra["lock_detect"] = st
            # what the chip's own detector says, as opposed to what a
            # frequency-error threshold concludes with hindsight
            sim.extra["lock_detect_time_s"] = st.lock_time_s
        spur_offsets = None
        if c.frac is not None:
            spur_offsets = frac_spur_offsets(c.frac.frac, c.fref,
                                             fmin=8.0 * c.fref / n_cycles)
        if supply_ripple is not None and supply_ripple[1] < 0.45 * c.fref:
            spur_offsets = (spur_offsets or []) + [supply_ripple[1]]
        spur_offsets = add_pull_offset(spur_offsets, c.osc, c.fref)
        if c.ref_doubler_duty_err != 0.0:
            spur_offsets = (spur_offsets or []) + [c.fref / 2.0]
        sim = postprocess(sim, settle_frac=0.25, int_band=c.int_band,
                          spur_offsets=spur_offsets,
                          flicker_corner_hz=flicker_corner_hz(c))
        sim = tuning_sim_notes(sim, c.osc)
        if fine is not None:
            sim = attach_fine(sim, fine, m_os, c.fref, c.int_band, spur_offsets)
            sub = tref / m_os
            if c.cp.t_reset > 0 and sub > c.cp.t_reset:
                # the mismatch ripple is a notch t_reset wide; sampling coarser
                # than that under-reads the reference spur, converging from
                # below as M rises
                sim.notes.append(
                    f"fine_oversample={m_os} gives {sub * 1e12:.0f} ps between "
                    f"samples but the CP reset pulse is {c.cp.t_reset * 1e12:.0f} "
                    "ps: the reference spur here is UNDER-read — raise it to "
                    f"{int(np.ceil(tref / c.cp.t_reset))} to resolve the pulse")
            return sim
        return no_fine_note(sim)
