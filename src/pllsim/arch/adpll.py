"""All-digital PLL.

Two variants:
  mode="tdc":      counter-assisted (Staszewski) — FCW accumulator vs DCO
                   counter + flash TDC fractional readout; supports fractional
                   FCW natively (no MASH needed).
  mode="dtc_bbpd": divider + MASH + DTC-aligned bang-bang PD — the common
                   low-power fractional-N style; BBPD gain linearized
                   self-consistently in analyze().

Frequency domain is exact z-domain on the grid (z = e^{j2πf/fref}) including
the one-cycle update delay.  Time domain runs one step per reference cycle.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..blocks.oscillator import OscConfig, Oscillator
from ..blocks.tdc import BBPD, TDC, TDCConfig, meta_gain_penalty
from ..core.colored import synth_from_psd
from ..core.engine import detect_lock, postprocess
from ..core.freqresp import FreqResponse, default_grid, loop_metrics
from ..core.jitter import ipn_dbc, rms_jitter_fs
from ..core.noise import (
    DcoQuantPhase,
    FlickerFloorPhase,
    NoisePath,
    NoiseSource,
    ShapedQuantization,
    output_psd,
)
from ..core.results import AnalysisResult, SimResult
from .base import (
    PLLBase,
    add_pull_offset,
    pull_hz,
    pull_notes,
    pull_spur,
    supply_ripple_v,
)
from .cppll import FracConfig, frac_spur_offsets

TWOPI = 2.0 * np.pi


@dataclass
class DLFConfig:
    """Digital loop filter: L(z) = alpha + rho/(1-z^-1), then IIR stages
    lam/(1-(1-lam) z^-1) each."""

    alpha: float
    rho: float
    iir_lambdas: tuple = ()


@dataclass
class ADPLLConfig:
    fref: float
    fout: float
    osc: OscConfig                     # gain = Kdco [Hz/LSB]
    dlf: DLFConfig
    mode: str = "tdc"                  # "tdc" | "dtc_bbpd"
    tdc: TDCConfig | None = None
    dco_dither_order: int = 1          # 0 = none, 1 = EFM1 at fref
    ref_pn_dbchz: float = -155.0
    ref_pn_fc: float = 20e3
    kdco_est_error: float = 0.0        # initial Kdco estimate error (fraction)
    frac: FracConfig | None = None     # dtc_bbpd mode: MASH + DTC config
    bb_jitter_rms_s: float = 100e-15   # BBPD input-referred jitter (dtc_bbpd)
    # Sampling-flop resolution window: inside it the decision is a coin flip.
    # Costs Kbb by exp(-W^2/2 sigma^2) and therefore widens the input-referred
    # noise by the same factor -- a window equal to sigma_t is 4.34 dB.
    bb_meta_window_s: float = 0.0
    int_band: tuple[float, float] = (1e3, 100e6)

    @property
    def fcw(self) -> float:
        return self.fout / self.fref

    def __post_init__(self):
        if self.mode not in ("tdc", "dtc_bbpd"):
            raise ValueError("mode must be 'tdc' or 'dtc_bbpd'")
        if self.mode == "tdc" and self.tdc is None:
            raise ValueError("tdc mode requires TDCConfig")
        if self.mode == "dtc_bbpd" and self.frac is None:
            raise ValueError("dtc_bbpd mode requires FracConfig (MASH + DTC)")
        if self.frac is not None and self.frac.dtc_lut_cal is not None:
            raise ValueError(
                "dtc_lut_cal is wired for the CPPLL only: its update"
                " regresses a TIMING error against the MASH residue, and"
                " the bang-bang detector exposes only a sign — wiring it"
                " naively measurably made the INL spur worse.")
        if self.osc.n_bands > 1:
            raise ValueError(
                "the ADPLL engine has no coarse-band search: the DCO word is\n"
                "the only tuning control it models, so n_bands would be\n"
                "accepted and never acted on (and export would still emit a\n"
                "band-search FSM for it)")


class ADPLL(PLLBase):
    def __init__(self, cfg: ADPLLConfig):
        self.cfg = cfg

    # ------------------------------------------------------------- helpers
    def _dlf_fr(self, f: np.ndarray) -> FreqResponse:
        c = self.cfg.dlf
        zinv = np.exp(-2j * np.pi * f / self.cfg.fref)
        h = c.alpha + c.rho / (1.0 - zinv)
        for lam in c.iir_lambdas:
            h = h * lam / (1.0 - (1.0 - lam) * zinv)
        return FreqResponse(f, h)

    def _dco_phase_fr(self, f: np.ndarray) -> FreqResponse:
        """OTW [LSB] -> output phase [rad]: 2π·Kdco·Tref·z^-1/(1-z^-1)."""
        c = self.cfg
        zinv = np.exp(-2j * np.pi * f / c.fref)
        return FreqResponse(f, TWOPI * c.osc.gain * (1.0 / c.fref) * zinv / (1.0 - zinv))

    # ------------------------------------------------------------- analyze
    def analyze(self, f: np.ndarray | None = None) -> AnalysisResult:
        c = self.cfg
        if f is None:
            f = default_grid(1e2, 1e9)
        notes = []
        if c.mode == "tdc":
            gol, kdet = self._gol_tdc(f)
        else:
            gol, kdet, sigma_t = self._gol_bbpd(f)
            notes.append(f"BBPD linearized: sigma_t at PD = {sigma_t * 1e15:.0f} fs, "
                         f"Kbb = {kdet:.3g} 1/s")
        h = gol.feedback()               # lowpass, ref-referred
        err = 1.0 - h

        paths = [
            NoisePath(FlickerFloorPhase.from_spot("ref", c.ref_pn_dbchz, c.ref_pn_fc),
                      h * c.fcw),
            NoisePath(c.osc.leeson("dco"), err),
            NoisePath(DcoQuantPhase(name="dco_quant", kdco=c.osc.gain, fs=c.fref,
                                    order=max(c.dco_dither_order, 0)), err),
        ]
        if c.mode == "tdc":
            q_ui = c.tdc.t_res * c.fout
            paths.append(NoisePath(
                ShapedQuantization(name="tdc_quant", unit="rad^2/Hz",
                                   q=TWOPI * q_ui, fs=c.fref, order=0), h))
        else:
            # BBPD quantization: total power (1 - 2/pi) white, input-referred
            s_bb = 2.0 * (1.0 - 2.0 / np.pi) / c.fref / kdet**2   # s^2/Hz
            paths.append(NoisePath(
                NoiseSource(name="bbpd_quant", unit="rad^2/Hz",
                            level=s_bb * (TWOPI * c.fout) ** 2), h))
            if c.frac.dtc is not None:
                q_dtc = c.frac.dtc.t_res
                paths.append(NoisePath(
                    ShapedQuantization(name="dtc_quant", unit="rad^2/Hz",
                                       q=TWOPI * q_dtc * c.fout, fs=c.fref, order=0), h))
                j_dtc = getattr(c.frac.dtc, "jitter_rms_s", 0.0)
                if j_dtc > 0:      # DTC.delay injects it every cycle in sim
                    paths.append(NoisePath(
                        NoiseSource(name="dtc_jitter", unit="rad^2/Hz",
                                    level=2.0 * (TWOPI * c.fout * j_dtc) ** 2
                                    / c.fref), h))
                eps = getattr(c.frac.dtc, "gain_error_residual", 0.01)
                paths.append(NoisePath(
                    ShapedQuantization(name="dsm_residual", unit="rad^2/Hz",
                                       q=TWOPI * eps, fs=c.fref,
                                       order=c.frac.mash_order - 1), h))

        m = loop_metrics(gol)
        bd = output_psd(paths, f)
        jit = rms_jitter_fs(f, bd["total"], c.fout, *c.int_band)
        if m.f_ugb > c.fref / 10:
            notes.append("UGB > fref/10: discrete loop peaking significant")
        spurs = dict(pull_spur(c.osc, err))
        notes.extend(pull_notes(c.osc))
        if c.mode == "tdc" and c.fcw % 1.0 > 1e-9:
            # The TDC input sweeps its range at the fractional beat rate, so a
            # declared INL is a deterministic tone generator, not something
            # only simulate() can see.
            from ..core.tdcspurs import code_span, tdc_inl_spur_table
            for off, dbc in tdc_inl_spur_table(
                    c.tdc, c.fcw % 1.0, c.fref, c.fout, ntf=h).items():
                spurs[f"frac_spur@{off:.0f}Hz"] = dbc
            span = code_span(c.tdc, c.fout)
            if span > 1.0:
                notes.append(
                    f"TDC range is {1 / span:.2f} of an output period: it "
                    "saturates every cycle, so the loop loses phase "
                    "information rather than merely quantizing it")
            if not c.tdc.inl_sin:
                offs = frac_spur_offsets(c.fcw % 1.0, c.fref)
                where = (f"{min(offs) / 1e6:.3f} MHz and {len(offs) - 1} more"
                         if offs else "fold(k*frac)*fref")
                notes.append(
                    f"fractional FCW with an ideal TDC: the beats at {where} "
                    "come from quantization alone, which simulate() measures "
                    "— declare tdc.inl_sin to get them predicted here")
        if c.mode == "dtc_bbpd" and c.frac.dtc is not None:
            from ..core.dtcspurs import dtc_spur_table
            eps = getattr(c.frac.dtc, "gain_error_residual", 0.01)
            for off, dbc in dtc_spur_table(
                    c.frac, lambda r: r / c.fout, c.fref, c.fout,
                    ntf=h, gain_eps=eps).items():
                spurs[f"frac_spur@{off:.0f}Hz"] = dbc
        return AnalysisResult(
            f=f, f0=c.fout, pn_breakdown=bd, loop=m, jitter_fs=jit,
            ipn_dbc=ipn_dbc(f, bd["total"], *c.int_band), int_band=c.int_band,
            spurs_analytic=spurs,
            ntfs={"gol": gol, "h": h, "err": err}, notes=notes)

    def _gol_tdc(self, f):
        # loop works in UI: e_ui -> L(z) -> x fref/kdco_hat -> OTW -> DCO phase
        # Gol(z) = L(z) * (kdco_true/kdco_hat) * z^-1/(1-z^-1)
        c = self.cfg
        zinv = np.exp(-2j * np.pi * f / c.fref)
        kr = 1.0 / (1.0 + c.kdco_est_error)
        gol = self._dlf_fr(f) * FreqResponse(f, kr * zinv / (1.0 - zinv))
        return gol, None

    def _gol_bbpd(self, f):
        """Self-consistent BBPD linearization: Kbb = sqrt(2/pi)/sigma_t."""
        c = self.cfg
        q_dtc = c.frac.dtc.t_res if c.frac.dtc is not None else 0.0
        j_dtc = c.frac.dtc.jitter_rms_s if c.frac.dtc is not None else 0.0
        sigma_t = max(c.bb_jitter_rms_s, 1e-15)
        gol = None
        for _ in range(8):
            # a metastability window costs gain, not output power: the flop
            # still emits +/-1, just uncorrelated with dt inside the window
            kbb = (np.sqrt(2.0 / np.pi) / sigma_t
                   * meta_gain_penalty(c.bb_meta_window_s, sigma_t))
            # e = Kbb * dt_pd ; dt_pd = phi_out/(2π fout)
            det = kbb / (TWOPI * c.fout)
            gol = self._dlf_fr(f) * self._dco_phase_fr(f) * det
            h = gol.feedback()
            err = 1.0 - h
            # output jitter contributions at the PD
            s_dco = c.osc.leeson("dco").psd(f) * err.mag2()
            from ..core.jitter import integrate_pn
            var_phi = integrate_pn(f, s_dco, 1e4, c.fref / 2)
            # everything the comparator actually sees: loop-shaped DCO noise,
            # DTC quantization AND the DTC's own random jitter (it sits in the
            # same edge path, so leaving it out over-predicts Kbb and the BW)
            var_t = var_phi / (TWOPI * c.fout) ** 2 \
                + q_dtc**2 / 12.0 + j_dtc**2 + c.bb_jitter_rms_s**2
            sigma_new = np.sqrt(var_t)
            if abs(sigma_new - sigma_t) < 1e-18:
                break
            sigma_t = 0.5 * sigma_t + 0.5 * sigma_new
        kbb = (np.sqrt(2.0 / np.pi) / sigma_t
               * meta_gain_penalty(c.bb_meta_window_s, sigma_t))
        return gol, kbb, sigma_t

    # ------------------------------------------------------------ simulate
    def simulate(self, n_cycles: int, *, noise: bool = True, calibration: bool = True,
                 seed: int = 0, f_start_offset: float = 0.0,
                 kdco_cal=None, tdc_cal=None, dtc_gain_init_error: float = 0.0,
                 supply_ripple: tuple[float, float] | None = None,
                 mod_freq: np.ndarray | None = None, mod_dp_gain: float = 1.0,
                 dtc_gain_drift: np.ndarray | None = None) -> SimResult:
        """The two modes take different knobs, and asking for the wrong one
        raises rather than being ignored: a silently dropped mod_freq returns a
        perfectly normal-looking SimResult with no modulation in it, and the
        EVM then reads as noise-limited.

        mode="tdc":      kdco_cal, tdc_cal, mod_freq, mod_dp_gain
        mode="dtc_bbpd": dtc_gain_init_error, dtc_gain_drift
        Both: noise, calibration, seed, f_start_offset.
        """
        if self.cfg.mode == "tdc":
            self._reject("tdc", dtc_gain_init_error=dtc_gain_init_error,
                         dtc_gain_drift=dtc_gain_drift)
            return self._sim_tdc(n_cycles, noise, calibration, seed,
                                 f_start_offset, kdco_cal, tdc_cal,
                                 mod_freq, mod_dp_gain, supply_ripple)
        self._reject("dtc_bbpd", kdco_cal=kdco_cal, tdc_cal=tdc_cal,
                     mod_freq=mod_freq, mod_dp_gain=None
                     if mod_dp_gain == 1.0 else mod_dp_gain)
        return self._sim_bbpd(n_cycles, noise, calibration, seed,
                              f_start_offset, dtc_gain_init_error,
                              dtc_gain_drift, supply_ripple)

    @staticmethod
    def _reject(mode: str, **unsupported):
        for name, value in unsupported.items():
            if value is None or (np.isscalar(value) and value == 0.0):
                continue
            raise TypeError(
                f"ADPLL.simulate(): {name} is not supported in mode={mode!r} "
                "and would have been ignored")

    def _ref_jitter(self, n_cycles, rng, noise):
        c = self.cfg
        if not noise:
            return np.zeros(n_cycles)
        src = FlickerFloorPhase.from_spot("ref", c.ref_pn_dbchz, c.ref_pn_fc)
        return synth_from_psd(src.psd, c.fref, n_cycles, rng) / (TWOPI * c.fref)

    def _sim_tdc(self, n_cycles, noise, calibration, seed, f_start_offset,
                 kdco_cal, tdc_cal, mod_freq=None, mod_dp_gain=1.0,
                 supply_ripple=None):
        c = self.cfg
        rng = np.random.default_rng(seed)
        tref = 1.0 / c.fref
        v_sup = supply_ripple_v(supply_ripple, n_cycles, tref)
        f_pull = pull_hz(c.osc, n_cycles, tref)
        fcw = c.fcw
        osc = Oscillator(c.osc, c.fref, rng, noise=noise, name="dco")
        tdc = TDC(c.tdc, rng, noise=noise)
        kdco_hat = c.osc.gain * (1.0 + c.kdco_est_error)
        otw_center = (c.fout - c.osc.f0) / c.osc.gain + f_start_offset / c.osc.gain

        # DLF state
        acc = 0.0
        iir_state = [0.0] * len(c.dlf.iir_lambdas)
        qerr = 0.0                       # 1st-order DCO dither state
        phi_v = 0.0                      # DCO phase [UI]
        r_acc = 0.0                      # reference accumulator [UI]
        cpp_nom = (1.0 / c.fout) / c.tdc.t_res    # nominal codes per period

        osc_noise = osc.noise_steps(n_cycles) if noise else np.zeros(n_cycles)
        prev_phi_n = 0.0
        jit_ref = self._ref_jitter(n_cycles, rng, noise)

        phase_err = np.empty(n_cycles)
        freq_out = np.empty(n_cycles)
        otw_rec = np.empty(n_cycles)
        fv = c.osc.freq_law(otw_center)

        for n in range(n_cycles):
            d_phi_n = (osc_noise[n] - prev_phi_n) / TWOPI     # UI
            prev_phi_n = osc_noise[n]
            phi_v += fv * tref + d_phi_n
            r_acc += fcw
            if mod_freq is not None:
                # lowpass point [UI] — one cycle behind the direct point:
                # the fv used for phi_v this cycle carries mod_freq[n-1]
                r_acc += (mod_freq[n - 1] if n > 0 else 0.0) * tref
            # reference jitter shifts the sampling instant of the DCO phase
            phi_sample = phi_v + jit_ref[n] * fv
            count = np.floor(phi_sample)
            frac_ui = phi_sample - count
            tdco = 1.0 / fv
            code = tdc.measure(frac_ui * tdco)
            if tdc_cal is not None and calibration:
                cpp_meas = tdco / tdc.t_lsb_true + rng.normal(0.0, 0.5) if noise \
                    else tdco / tdc.t_lsb_true
                tdc_cal.step(cpp_meas)
                tdc_ui = tdc_cal.code_to_ui(code)
            else:
                tdc_ui = code / cpp_nom
            e_ui = r_acc - (count + tdc_ui)

            if kdco_cal is not None and calibration and not kdco_cal.done:
                # open-loop FCAL phase: loop frozen, OTW stepped +/-A; the
                # frequency is measured from the counter (phase slope)
                kdco_cal.step(fv)
                kdco_hat = kdco_cal.value
                otw = otw_center + kdco_cal.perturbation
                r_acc = count + tdc_ui       # keep PD aligned for loop closure
                acc = 0.0
            else:
                # DLF
                acc += c.dlf.rho * e_ui
                x = c.dlf.alpha * e_ui + acc
                for i, lam in enumerate(c.dlf.iir_lambdas):
                    iir_state[i] += lam * (x - iir_state[i])
                    x = iir_state[i]
                otw = x * c.fref / kdco_hat + otw_center
            if mod_freq is not None:                 # highpass (direct) point
                otw += mod_freq[n] * mod_dp_gain / kdco_hat
            # DCO quantization with optional 1st-order dither
            if c.dco_dither_order > 0:
                otw_q = np.floor(otw + qerr)
                qerr = otw + qerr - otw_q
            else:
                otw_q = np.round(otw)
            fv = (c.osc.freq_law(otw_q) + c.osc.pushing_hz_v * v_sup[n]
                  + f_pull[n])

            phase_err[n] = TWOPI * (phi_v - (n + 1) * fcw)
            freq_out[n] = fv
            otw_rec[n] = otw_q

        t = np.arange(n_cycles) * tref
        lock = detect_lock(t, freq_out - c.fout, tol_hz=c.fout * 2e-5)
        sim = SimResult(fs=c.fref, f0=c.fout, t=t, phase_err_out=phase_err,
                        freq_out=freq_out, ctrl=otw_rec, lock_time_s=lock)
        if kdco_cal is not None:
            sim.cal_traces["kdco_hat"] = np.asarray(kdco_cal.trace)
        if tdc_cal is not None:
            sim.cal_traces["tdc_cpp"] = np.asarray(tdc_cal.trace)
        # TDC mode takes a fractional FCW natively (no MASH, no DTC), so the
        # fractional beat lands in the spectrum just as it does everywhere
        # else -- tabulate it instead of leaving the user to find it by eye
        frac = c.fcw % 1.0
        offs = frac_spur_offsets(frac, c.fref) if frac > 1e-9 else None
        offs = add_pull_offset(offs, c.osc, c.fref)
        if supply_ripple is not None and supply_ripple[1] < 0.45 * c.fref:
            offs = (offs or []) + [supply_ripple[1]]
        return postprocess(sim, int_band=c.int_band, spur_offsets=offs)

    def _sim_bbpd(self, n_cycles, noise, calibration, seed, f_start_offset,
                  dtc_gain_init_error, dtc_gain_drift=None,
                  supply_ripple=None):
        c = self.cfg
        rng = np.random.default_rng(seed)
        tref = 1.0 / c.fref
        v_sup = supply_ripple_v(supply_ripple, n_cycles, tref)
        f_pull = pull_hz(c.osc, n_cycles, tref)
        osc = Oscillator(c.osc, c.fref, rng, noise=noise, name="dco")
        bb = BBPD(c.bb_jitter_rms_s, rng, noise=noise,
                  meta_window_s=c.bb_meta_window_s)
        mash = c.frac.make_mash()
        frac_word = c.frac.frac_word
        n_int = int(c.fout // c.fref)
        otw_center = (c.fout - c.osc.f0) / c.osc.gain + f_start_offset / c.osc.gain

        dtc = None
        dtc_cal = None
        if c.frac.dtc is not None:
            from ..blocks.dtc import DTC
            dtc = DTC(c.frac.dtc, rng, noise=noise, gain_error=dtc_gain_init_error)
            if calibration:
                dtc_cal = c.frac.dtc_cal

        acc = 0.0
        qerr = 0.0
        phi_out = 0.0
        t_div = 0.0
        n_next = n_int
        osc_noise = osc.noise_steps(n_cycles) if noise else np.zeros(n_cycles)
        prev_phi_n = 0.0
        jit_ref = self._ref_jitter(n_cycles, rng, noise)

        phase_err = np.empty(n_cycles)
        freq_out = np.empty(n_cycles)
        otw_rec = np.empty(n_cycles)
        cal_trace = np.empty(n_cycles) if dtc_cal is not None else None
        fv = c.osc.freq_law(otw_center)

        for n in range(n_cycles):
            t_ref = n * tref + jit_ref[n]
            residual_ui = mash.residual_ui()
            if dtc is not None:
                if dtc_gain_drift is not None:
                    dtc.gain_error = dtc_gain_drift[n]
                t_ref += dtc.delay(residual_ui / c.fout)
            e = bb.sample(t_div - t_ref)

            if dtc_cal is not None:
                dtc_cal.step(e, residual_ui)
                dtc.gain_corr = dtc_cal.value
                cal_trace[n] = dtc_cal.value

            acc += c.dlf.rho * e
            otw = c.dlf.alpha * e + acc + otw_center
            if c.dco_dither_order > 0:
                otw_q = np.floor(otw + qerr)
                qerr = otw + qerr - otw_q
            else:
                otw_q = np.round(otw)
            fv = (c.osc.freq_law(otw_q) + c.osc.pushing_hz_v * v_sup[n]
                  + f_pull[n])

            n_next = n_int + mash.step(frac_word)
            d_osc = osc_noise[n] - prev_phi_n
            prev_phi_n = osc_noise[n]
            t_div += n_next / fv - d_osc / (TWOPI * fv)

            phi_out += TWOPI * (fv - c.fout) * tref + d_osc
            phase_err[n] = phi_out
            freq_out[n] = fv
            otw_rec[n] = otw_q

        t = np.arange(n_cycles) * tref
        lock = detect_lock(t, freq_out - c.fout, tol_hz=c.fout * 2e-5)
        sim = SimResult(fs=c.fref, f0=c.fout, t=t, phase_err_out=phase_err,
                        freq_out=freq_out, ctrl=otw_rec, lock_time_s=lock)
        if dtc_cal is not None:
            sim.cal_traces["dtc_gain"] = cal_trace
        if c.bb_meta_window_s > 0:
            frac_meta = bb.n_meta / max(n_cycles, 1)
            sim.extra["bbpd_metastable_frac"] = frac_meta
            sim.notes.append(
                f"BBPD decision was a coin flip on {frac_meta * 100:.1f}% of "
                "cycles (metastability window): that is lost detector gain, "
                "not added noise — the comparator still emits +/-1")
        offs = add_pull_offset(
            frac_spur_offsets(c.frac.frac, c.fref, fmin=8.0 * c.fref / n_cycles),
            c.osc, c.fref)
        return postprocess(sim, int_band=c.int_band, spur_offsets=offs)
