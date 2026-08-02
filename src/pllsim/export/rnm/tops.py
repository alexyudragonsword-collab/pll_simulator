"""Architecture-level RNM tops (Cadence wreal) + golden-CSV testbenches.

Each top is a single cycle-true `always @(posedge ref_clk)` recursion — a
line-for-line transplant of the corresponding golden engine in
export/rnm_golden.py (itself pytest-locked to the Python simulate()).  A
single sequential block eliminates cross-module event-ordering hazards and
makes the noise-free run reproduce the golden CSV to double-precision
round-off.  Debug wreal ports expose every golden column; EN_NOISE gates
$rdist_normal injection at the same points as the Python engine.
"""
from __future__ import annotations

import numpy as np

from ...blocks.loopfilter import LoopFilter
from ..formatting import module_header, vreal

TWOPI = 2.0 * np.pi

RNM_ARCHS = ("cppll_int", "cppll_frac", "sspll_int", "sspll_frac", "spll",
             "spll_frac", "adpll_tdc", "adpll_bbpd", "ilcm", "mdll")


def _p(name: str, value: float, comment: str) -> str:
    return f"  parameter real {name} = {vreal(value)},  // {comment}\n"


def _pi(name: str, value: int, comment: str) -> str:
    return f"  parameter integer {name} = {int(value)},  // {comment}\n"


def _lf_params(filt, fref: float) -> str:
    lf = LoopFilter(filt, 1.0 / fref)
    ad = np.eye(3)
    b = np.zeros(3)
    n = lf.ad.shape[0]
    ad[:n, :n] = lf.ad
    b[:n] = lf.ad @ lf.b       # x' = Ad x + (Ad b) dq  == Ad(x + b dq)
    out = ""
    for i in range(3):
        for j in range(3):
            out += _p(f"AD{i+1}{j+1}", ad[i, j],
                      f"exp(A*Tref)[{i}][{j}] (identity-padded)")
    for i in range(3):
        out += _p(f"B{i+1}", b[i], "Ad@b input vector [1/F]")
    out += _pi("LF_ORDER", filt.order, "loop filter order")
    return out


def _mash_body(order: int, bits: int) -> str:
    """Integer MASH recursion (blocking assigns, inside the main always)."""
    mask = (1 << bits) - 1
    if order == 1:
        return f"""\
      s1 = m_a1 + frac_word;
      y_mash = s1 >> {bits};
      m_a1 = s1 & {mask};
"""
    if order == 2:
        return f"""\
      s1 = m_a1 + frac_word;  c1 = s1 >> {bits};  m_a1 = s1 & {mask};
      s2 = m_a2 + (s1 & {mask});  c2 = s2 >> {bits};  m_a2 = s2 & {mask};
      y_mash = c1 + c2 - m_c2p;
      m_c2p = c2;
"""
    return f"""\
      s1 = m_a1 + frac_word;  c1 = s1 >> {bits};  m_a1 = s1 & {mask};
      s2 = m_a2 + (s1 & {mask});  c2 = s2 >> {bits};  m_a2 = s2 & {mask};
      s3 = m_a3 + (s2 & {mask});  c3 = s3 >> {bits};  m_a3 = s3 & {mask};
      y_mash = c1 + (c2 - m_c2p) + (c3 - 2*m_c3p + m_c3pp);
      m_c2p = c2;  m_c3pp = m_c3p;  m_c3p = c3;
"""


_MASH_DECL = """\
  integer m_a1, m_a2, m_a3, m_c2p, m_c3p, m_c3pp;
  integer s1, s2, s3, c1, c2, c3, y_mash, res_num;
"""
_MASH_INIT = "    m_a1=0; m_a2=0; m_a3=0; m_c2p=0; m_c3p=0; m_c3pp=0; res_num=0;\n"

_LF_DECL = "  real x1, x2, x3, y1, y2, y3;\n"
_LF_INIT = "    x1 = VINIT; x2 = VINIT; x3 = VINIT;\n"
_LF_STEP = """\
      y1 = x1 + B1*dq;  y2 = x2 + B2*dq;  y3 = x3 + B3*dq;
      x1 = AD11*y1 + AD12*y2 + AD13*y3;
      x2 = AD21*y1 + AD22*y2 + AD23*y3;
      x3 = AD31*y1 + AD32*y2 + AD33*y3;
      vctrl = (LF_ORDER == 3) ? x3 : x2;
"""

_DTC_CALC = """\
      t_req = t_target + DTC_RANGE/2.0;
      code  = t_req*gain_corr/DTC_TRES + 0.5;
      if (code < 0) code = 0;
      if (code > DTC_CODEMAX) code = DTC_CODEMAX;
      xdtc  = code*1.0/DTC_CODEMAX;
      d_dtc = code*DTC_TRES*(1.0+DTC_GAINERR)
            + DTC_INL_AMP*$sin(6.283185307179586*DTC_INL_CYC*xdtc + DTC_INL_PH);
"""


def _dbg_ports(cols: list[str]) -> tuple[str, str]:
    ports = "".join(f",\n  output dbg_{c}" for c in cols)
    decls = "  " + "  ".join(f"wreal dbg_{c};" for c in cols) + "\n"
    decls += "".join(f"  real r_{c};\n" for c in cols)
    decls += "".join(f"  assign dbg_{c} = r_{c};\n" for c in cols)
    return ports, decls


def _wrap_pm() -> str:
    # wrap to (-pi, pi]: mirrors ((x+pi) % 2pi) - pi with Python-sign modulo
    return """\
  function real wrap_pm;
    input real x;
    real m;
    begin
      m = x + 3.141592653589793;
      m = m - 6.283185307179586*$floor(m/6.283185307179586);
      wrap_pm = m - 3.141592653589793;
    end
  endfunction
"""


# --------------------------------------------------------------- CPPLL
def _top_cppll(cfg, name: str) -> tuple[str, list[str]]:
    frac = cfg.frac is not None
    cols = ["dt", "dq", "vctrl", "fv"] + (["residual", "dtc_delay"] if frac else [])
    ports, dbg = _dbg_ports(cols)
    c = cfg
    n_int = int(c.fout // c.fref) if frac else int(round(c.n_div))
    up = c.cp.icp * (1.0 + 0.005 * c.cp.mismatch_pct)
    dn = c.cp.icp * (1.0 - 0.005 * c.cp.mismatch_pct)
    params = (
        _p("FREF", c.fref, "cfg.fref [Hz]") +
        _p("TREF", 1.0 / c.fref, "reference period [s]") +
        _p("F0", c.osc.f0, "cfg.osc.f0 [Hz]") +
        _p("KVCO", c.osc.gain, "cfg.osc.gain [Hz/V]") +
        _p("NL1", c.osc.nl1, "Kvco nonlinearity") +
        _p("NL2", c.osc.nl2, "Kvco nonlinearity") +
        _p("I_UP", up, "CP up current incl. mismatch [A]") +
        _p("I_DN", dn, "CP down current incl. mismatch [A]") +
        _p("T_RESET", c.cp.t_reset, "PFD reset pulse [s]") +
        _p("I_LEAK", c.cp.leakage_a, "CP leakage [A]") +
        _p("VINIT", c.osc.v_for(c.fout), "initial vctrl (locked point) [V]") +
        _lf_params(c.filt, c.fref) +
        _pi("N_INT", n_int, "integer divide ratio") +
        _pi("EN_NOISE", 0, "1 = inject CP/DTC noise ($rdist_normal)") +
        _pi("SEED", 1, "noise seed"))
    mash_decl = mash_init = mash_body = dtc_par = ""
    if frac:
        f = c.frac
        dtc_par = (
            _pi("FRAC_WORD", f.frac_word, "cfg.frac.frac_word") +
            _p("DTC_TRES", f.dtc.t_res, "DTC LSB [s]") +
            _pi("DTC_CODEMAX", (1 << f.dtc.n_bits) - 1, "DTC code max") +
            _p("DTC_RANGE", f.dtc.range_s, "DTC full-scale [s]") +
            _p("DTC_GAINERR", 0.0, "true DTC gain error (impairment)") +
            _p("DTC_INL_AMP", (f.dtc.inl_sin[0] if f.dtc.inl_sin else 0.0),
               "DTC INL sine amplitude [s]") +
            _p("DTC_INL_CYC", (f.dtc.inl_sin[1] if f.dtc.inl_sin else 0.0),
               "DTC INL cycles over the range") +
            _p("DTC_INL_PH", (f.dtc.inl_sin[2] if f.dtc.inl_sin else 0.0),
               "DTC INL phase [rad]") +
            _p("DTC_JITTER", f.dtc.jitter_rms_s, "DTC jitter [s], EN_NOISE") +
            _p("FOUT_NOM", c.fout, "nominal output [Hz]"))
        mash_decl = _MASH_DECL
        mash_init = _MASH_INIT
        mash_body = _mash_body(f.mash_order, f.bits)
    body = f"""\
`timescale 1fs/1fs
module {name}_top_rnm #(
{params}{dtc_par}  parameter integer EMIT_UNUSED = 0
) (
  input ref_clk{ports}
);
{dbg}{_LF_DECL}{mash_decl}\
  real t_div, t_ref, dt, dt_eff, dq, fv, vctrl;
  real residual, t_target, t_req, xdtc, d_dtc, gain_corr;
  integer code, n_next, cyc, seed;

  initial begin
{_LF_INIT}{mash_init}\
    t_div = 0.0; cyc = 0; seed = SEED; gain_corr = 1.0;
    vctrl = VINIT;
    fv = F0 + KVCO*vctrl*(1.0 + NL1*vctrl + NL2*vctrl*vctrl);
  end

  always @(posedge ref_clk) begin
    t_ref = cyc*TREF;
"""
    if frac:
        body += f"""\
      residual = (res_num)*1.0/(1<<{c.frac.bits});
      t_target = residual/FOUT_NOM;
{_DTC_CALC}\
      if (EN_NOISE) d_dtc = d_dtc + $rdist_normal(seed,0,1000000)/1.0e6*DTC_JITTER;
      t_ref = t_ref + d_dtc;
"""
    body += """\
      dt = t_div - t_ref;
      dt_eff = dt;
      if (dt_eff >  0.45*TREF) dt_eff =  0.45*TREF;
      if (dt_eff < -0.45*TREF) dt_eff = -0.45*TREF;
      dq = (I_UP - I_DN)*T_RESET
         + ((dt_eff > 0.0) ? I_UP : I_DN)*dt_eff + I_LEAK*TREF;
"""
    body += _LF_STEP
    body += """\
      fv = F0 + KVCO*vctrl*(1.0 + NL1*vctrl + NL2*vctrl*vctrl);
      if (fv < 0.05*F0) fv = 0.05*F0;
"""
    if frac:
        body += mash_body
        body += f"""\
      res_num = res_num + (y_mash<<{c.frac.bits}) - FRAC_WORD;
      n_next  = N_INT + y_mash;
"""
    else:
        body += "      n_next = N_INT;\n"
    body += """\
      t_div = t_div + n_next*1.0/fv;
      cyc = cyc + 1;
"""
    body += "".join(f"      r_{c2} = {m};\n" for c2, m in
                    [("dt", "dt"), ("dq", "dq"), ("vctrl", "vctrl"),
                     ("fv", "fv")] +
                    ([("residual", "residual"), ("dtc_delay", "d_dtc")]
                     if frac else []))
    body += """\
  end
endmodule
"""
    hdr = module_header(f"{name}: cycle-true RNM top (charge-pump PLL)",
                        "transplant of pllsim.export.rnm_golden.golden_cppll")
    return hdr + body, cols


# --------------------------------------------------------------- SSPLL/SPLL
def _top_sspll(cfg, name: str) -> tuple[str, list[str]]:
    frac = cfg.frac is not None
    cols = ["perr", "vs", "dq", "vctrl", "fv"]
    ports, dbg = _dbg_ports(cols)
    c, s = cfg, cfg.sampler
    params = (
        _p("FREF", c.fref, "cfg.fref [Hz]") +
        _p("TREF", 1.0 / c.fref, "reference period [s]") +
        _p("F0", c.osc.f0, "cfg.osc.f0 [Hz]") +
        _p("KVCO", c.osc.gain, "cfg.osc.gain [Hz/V]") +
        _p("NL1", c.osc.nl1, "") + _p("NL2", c.osc.nl2, "") +
        _p("AMP", s.amp_v, "sampled swing [V]") +
        _p("GM", s.gm, "pulser gm [A/V]") +
        _p("TPUL", s.pulse_width, "gm pulse width [s]") +
        _p("VPED", s.pedestal_v, "sampling pedestal [V]") +
        _p("KTC_SIG", s.ktc_sigma_v, "kT/C sigma [V], EN_NOISE") +
        _p("VINIT", c.osc.v_for(c.fout), "initial vctrl [V]") +
        _lf_params(c.filt, c.fref) +
        _pi("EN_NOISE", 0, "1 = kT/C + DTC noise") + _pi("SEED", 2, ""))
    mash_decl = mash_init = mash_body = dtc_par = ""
    if frac:
        f = c.frac
        dtc_par = (
            _pi("FRAC_WORD", f.frac_word, "cfg.frac.frac_word") +
            _p("DTC_TRES", f.dtc.t_res, "DTC LSB [s]") +
            _pi("DTC_CODEMAX", (1 << f.dtc.n_bits) - 1, "") +
            _p("DTC_RANGE", f.dtc.range_s, "DTC full-scale [s]") +
            _p("DTC_GAINERR", 0.0, "true DTC gain error") +
            _p("DTC_INL_AMP", 0.0, "") + _p("DTC_INL_CYC", 0.0, "") +
            _p("DTC_INL_PH", 0.0, "") +
            _p("DTC_JITTER", f.dtc.jitter_rms_s, "") +
            _p("FOUT_NOM", c.fout, "nominal output [Hz]"))
        mash_decl = _MASH_DECL
        mash_init = _MASH_INIT
        mash_body = _mash_body(1, f.bits)
    body = f"""\
`timescale 1fs/1fs
module {name}_top_rnm #(
{params}{dtc_par}  parameter integer EMIT_UNUSED = 0
) (
  input ref_clk{ports}
);
{dbg}{_wrap_pm()}{_LF_DECL}{mash_decl}\
  real phi_frac, prev_extra, extra, dt_period, perr, vs, dq, fv, vctrl;
  real residual, t_target, t_req, xdtc, d_dtc, gain_corr;
  integer code, cyc, seed;

  initial begin
{_LF_INIT}{mash_init}\
    phi_frac = 0.0; prev_extra = 0.0; cyc = 0; seed = SEED; gain_corr = 1.0;
    vctrl = VINIT;
    fv = F0 + KVCO*vctrl*(1.0 + NL1*vctrl + NL2*vctrl*vctrl);
  end

  always @(posedge ref_clk) begin
    extra = 0.0;
"""
    if frac:
        body += f"""\
      residual = (res_num)*1.0/(1<<{c.frac.bits});
      t_target = (1.0 + residual)/FOUT_NOM - DTC_RANGE/2.0;
{_DTC_CALC}\
      if (EN_NOISE) d_dtc = d_dtc + $rdist_normal(seed,0,1000000)/1.0e6*DTC_JITTER;
      extra = extra + d_dtc;
"""
    body += """\
      dt_period = TREF + extra - prev_extra;
      prev_extra = extra;
      phi_frac = phi_frac + 6.283185307179586*fv*dt_period;
      phi_frac = phi_frac - 6.283185307179586
                 *$floor(phi_frac/6.283185307179586);
      perr = wrap_pm(phi_frac);
      vs = AMP*$sin(perr) + VPED;
      if (EN_NOISE) vs = vs + $rdist_normal(seed,0,1000000)/1.0e6*KTC_SIG;
      dq = -GM*vs*TPUL;                 // inverting gm
"""
    if frac:
        body += mash_body
        body += f"      res_num = res_num + (y_mash<<{c.frac.bits}) - FRAC_WORD;\n"
    body += _LF_STEP
    body += """\
      fv = F0 + KVCO*vctrl*(1.0 + NL1*vctrl + NL2*vctrl*vctrl);
      if (fv < 0.05*F0) fv = 0.05*F0;
      cyc = cyc + 1;
      r_perr = perr;  r_vs = vs;  r_dq = dq;  r_vctrl = vctrl;  r_fv = fv;
  end
endmodule
"""
    hdr = module_header(f"{name}: cycle-true RNM top (sub-sampling PLL)",
                        "transplant of pllsim.export.rnm_golden.golden_sspll")
    return hdr + body, cols


def _top_spll(cfg, name: str) -> tuple[str, list[str]]:
    frac = cfg.frac is not None
    cols = ["perr", "dq", "vctrl", "fv"]
    ports, dbg = _dbg_ports(cols)
    c, s = cfg, cfg.sampler
    n_int = int(c.fout // c.fref) if frac else int(round(c.n_div))
    params = (
        _p("FREF", c.fref, "cfg.fref [Hz]") +
        _p("TREF", 1.0 / c.fref, "") +
        _p("F0", c.osc.f0, "") + _p("KVCO", c.osc.gain, "") +
        _p("NL1", c.osc.nl1, "") + _p("NL2", c.osc.nl2, "") +
        _p("AMP", s.amp_v, "") + _p("GM", s.gm, "") +
        _p("TPUL", s.pulse_width, "") + _p("VPED", s.pedestal_v, "") +
        _p("VINIT", c.osc.v_for(c.fout), "") +
        _lf_params(c.filt, c.fref) +
        _pi("N_INT", n_int, "integer divide ratio") +
        _pi("EN_NOISE", 0, "") + _pi("SEED", 3, ""))
    mash_decl = mash_init = mash_body = dtc_par = ""
    if frac:
        f = c.frac
        dtc_par = (
            _pi("FRAC_WORD", f.frac_word, "cfg.frac.frac_word") +
            _p("DTC_TRES", f.dtc.t_res, "DTC LSB [s]") +
            _pi("DTC_CODEMAX", (1 << f.dtc.n_bits) - 1, "") +
            _p("DTC_RANGE", f.dtc.range_s, "DTC full-scale [s]") +
            _p("DTC_GAINERR", 0.0, "true DTC gain error") +
            _p("DTC_INL_AMP", 0.0, "") + _p("DTC_INL_CYC", 0.0, "") +
            _p("DTC_INL_PH", 0.0, "") +
            _p("DTC_JITTER", f.dtc.jitter_rms_s, "") +
            _p("FOUT_NOM", c.fout, "nominal output [Hz]"))
        mash_decl = _MASH_DECL
        mash_init = _MASH_INIT
        mash_body = _mash_body(1, f.bits)
    frac_pre = ""
    if frac:
        frac_pre = f"""\
      residual = (res_num)*1.0/(1<<{c.frac.bits});
      t_target = -residual/FOUT_NOM - DTC_RANGE/2.0;
{_DTC_CALC}\
      if (EN_NOISE) d_dtc = d_dtc + $rdist_normal(seed,0,1000000)/1.0e6*DTC_JITTER;
"""
    frac_step = ""
    if frac:
        frac_step = mash_body + f"""\
      res_num = res_num + (y_mash<<{c.frac.bits}) - FRAC_WORD;
      n_next = N_INT + y_mash;
"""
    else:
        frac_step = "      n_next = N_INT;\n"
    body = f"""\
`timescale 1fs/1fs
module {name}_top_rnm #(
{params}{dtc_par}  parameter integer EMIT_UNUSED = 0
) (
  input ref_clk{ports}
);
{dbg}{_wrap_pm()}{_LF_DECL}{mash_decl}\
  real t_div, perr, vs, dq, fv, vctrl;
  real residual, t_target, t_req, xdtc, d_dtc, gain_corr;
  integer code, n_next, cyc, seed;

  initial begin
{_LF_INIT}{mash_init}\
    t_div = 0.0; cyc = 0; seed = SEED; gain_corr = 1.0; d_dtc = 0.0;
    vctrl = VINIT;
    fv = F0 + KVCO*vctrl*(1.0 + NL1*vctrl + NL2*vctrl*vctrl);
  end

  always @(posedge ref_clk) begin
{frac_pre}\
      perr = wrap_pm(6.283185307179586*FREF*(t_div + d_dtc - cyc*TREF));
      vs = AMP*$sin(perr) + VPED;
      dq = GM*vs*TPUL;
{_LF_STEP}\
      fv = F0 + KVCO*vctrl*(1.0 + NL1*vctrl + NL2*vctrl*vctrl);
      if (fv < 0.05*F0) fv = 0.05*F0;
{frac_step}\
      t_div = t_div + n_next*1.0/fv;
      cyc = cyc + 1;
      r_perr = perr;  r_dq = dq;  r_vctrl = vctrl;  r_fv = fv;
  end
endmodule
"""
    hdr = module_header(f"{name}: cycle-true RNM top (reference-sampling PLL)",
                        "transplant of pllsim.export.rnm_golden.golden_spll")
    return hdr + body, cols


# --------------------------------------------------------------- ADPLL
def _top_adpll_tdc(cfg, name: str) -> tuple[str, list[str]]:
    cols = ["e_ui", "otw_q", "fv"]
    ports, dbg = _dbg_ports(cols)
    c = cfg
    iir_par = "".join(_p(f"LAM{i}", lam, f"IIR stage {i}")
                      for i, lam in enumerate(c.dlf.iir_lambdas))
    iir_decl = "".join(f"  real iir{i};\n"
                       for i in range(len(c.dlf.iir_lambdas)))
    iir_init = "".join(f"    iir{i} = 0.0;\n"
                       for i in range(len(c.dlf.iir_lambdas)))
    iir_body = ""
    src = "x"
    for i in range(len(c.dlf.iir_lambdas)):
        iir_body += f"      iir{i} = iir{i} + LAM{i}*({src} - iir{i});\n"
        src = f"iir{i}"
    params = (
        _p("FREF", c.fref, "") + _p("TREF", 1.0 / c.fref, "") +
        _p("FCW", c.fcw, "frequency command word") +
        _p("F0", c.osc.f0, "") + _p("KDCO", c.osc.gain, "[Hz/LSB]") +
        _p("KDCO_HAT", c.osc.gain * (1.0 + c.kdco_est_error),
           "normalization estimate") +
        _p("ALPHA", c.dlf.alpha, "DLF proportional") +
        _p("RHO", c.dlf.rho, "DLF integral") + iir_par +
        _p("TDC_TRES", c.tdc.t_res, "TDC LSB [s]") +
        _p("TDC_TLSB_TRUE", c.tdc.t_res * (1.0 + c.tdc.gain_error),
           "true TDC LSB [s]") +
        _pi("TDC_CODEMAX", (1 << c.tdc.n_bits) - 1, "") +
        _p("CPP_NOM", (1.0 / c.fout) / c.tdc.t_res, "nominal codes/period") +
        _p("OTW_CENTER", (c.fout - c.osc.f0) / c.osc.gain, "center OTW [LSB]") +
        _pi("DITHER", 1 if c.dco_dither_order > 0 else 0, "1st-order dither") +
        _pi("EN_NOISE", 0, "") + _pi("SEED", 4, ""))
    body = f"""\
`timescale 1fs/1fs
module {name}_top_rnm #(
{params}  parameter integer EMIT_UNUSED = 0
) (
  input ref_clk{ports}
);
{dbg}{iir_decl}\
  real phi_v, r_acc, frac_ui, e_ui, acc, x, otw, otw_q, qerr, fv, cnt;
  integer code, cyc, seed;

  initial begin
{iir_init}\
    phi_v = 0.0; r_acc = 0.0; acc = 0.0; qerr = 0.0; cyc = 0; seed = SEED;
    fv = F0 + KDCO*OTW_CENTER;
  end

  always @(posedge ref_clk) begin
      phi_v = phi_v + fv*TREF;
      r_acc = r_acc + FCW;
      cnt = $floor(phi_v);
      frac_ui = phi_v - cnt;
      code = frac_ui*(1.0/fv)/TDC_TLSB_TRUE;   // truncation, as in Python int()
      if (code < 0) code = 0;
      if (code > TDC_CODEMAX) code = TDC_CODEMAX;
      e_ui = r_acc - (cnt + code/CPP_NOM);
      acc = acc + RHO*e_ui;
      x = ALPHA*e_ui + acc;
{iir_body}\
      otw = {src}*FREF/KDCO_HAT + OTW_CENTER;
      if (DITHER) begin
        otw_q = $floor(otw + qerr);
        qerr = otw + qerr - otw_q;
      end else otw_q = $floor(otw + 0.5);
      fv = F0 + KDCO*otw_q;
      cyc = cyc + 1;
      r_e_ui = e_ui;  r_otw_q = otw_q;  r_fv = fv;
  end
endmodule
"""
    hdr = module_header(f"{name}: cycle-true RNM top (counter/TDC ADPLL)",
                        "transplant of pllsim.export.rnm_golden.golden_adpll_tdc")
    return hdr + body, cols


def _top_adpll_bbpd(cfg, name: str) -> tuple[str, list[str]]:
    cols = ["e", "otw_q", "fv", "residual"]
    ports, dbg = _dbg_ports(cols)
    c, f = cfg, cfg.frac
    params = (
        _p("FREF", c.fref, "") + _p("TREF", 1.0 / c.fref, "") +
        _p("F0", c.osc.f0, "") + _p("KDCO", c.osc.gain, "[Hz/LSB]") +
        _p("ALPHA", c.dlf.alpha, "BB DLF proportional [LSB]") +
        _p("RHO", c.dlf.rho, "BB DLF integral [LSB]") +
        _p("OTW_CENTER", (c.fout - c.osc.f0) / c.osc.gain, "") +
        _pi("N_INT", int(c.fout // c.fref), "") +
        _pi("FRAC_WORD", f.frac_word, "") +
        _p("DTC_TRES", f.dtc.t_res, "") +
        _pi("DTC_CODEMAX", (1 << f.dtc.n_bits) - 1, "") +
        _p("DTC_RANGE", f.dtc.range_s, "") +
        _p("DTC_GAINERR", 0.0, "") +
        _p("DTC_INL_AMP", 0.0, "") + _p("DTC_INL_CYC", 0.0, "") +
        _p("DTC_INL_PH", 0.0, "") +
        _p("DTC_JITTER", f.dtc.jitter_rms_s, "") +
        _p("FOUT_NOM", c.fout, "") +
        _p("BB_JITTER", c.bb_jitter_rms_s, "BBPD input jitter, EN_NOISE") +
        _pi("DITHER", 1 if c.dco_dither_order > 0 else 0, "") +
        _pi("EN_NOISE", 0, "") + _pi("SEED", 5, ""))
    body = f"""\
`timescale 1fs/1fs
module {name}_top_rnm #(
{params}  parameter integer EMIT_UNUSED = 0
) (
  input ref_clk{ports}
);
{dbg}{_MASH_DECL}\
  real t_div, t_ref, e, acc, otw, otw_q, qerr, fv;
  real residual, t_target, t_req, xdtc, d_dtc, gain_corr, dtbb;
  integer code, n_next, cyc, seed;

  initial begin
{_MASH_INIT}\
    t_div = 0.0; acc = 0.0; qerr = 0.0; cyc = 0; seed = SEED; gain_corr = 1.0;
    fv = F0 + KDCO*OTW_CENTER;
  end

  always @(posedge ref_clk) begin
      t_ref = cyc*TREF;
      residual = (res_num)*1.0/(1<<{f.bits});
      t_target = residual/FOUT_NOM;
{_DTC_CALC}\
      if (EN_NOISE) d_dtc = d_dtc + $rdist_normal(seed,0,1000000)/1.0e6*DTC_JITTER;
      t_ref = t_ref + d_dtc;
      dtbb = t_div - t_ref;
      if (EN_NOISE) dtbb = dtbb + $rdist_normal(seed,0,1000000)/1.0e6*BB_JITTER;
      e = (dtbb >= 0.0) ? 1.0 : -1.0;
      acc = acc + RHO*e;
      otw = ALPHA*e + acc + OTW_CENTER;
      if (DITHER) begin
        otw_q = $floor(otw + qerr);
        qerr = otw + qerr - otw_q;
      end else otw_q = $floor(otw + 0.5);
      fv = F0 + KDCO*otw_q;
{_mash_body(f.mash_order, f.bits)}\
      res_num = res_num + (y_mash<<{f.bits}) - FRAC_WORD;
      n_next = N_INT + y_mash;
      t_div = t_div + n_next*1.0/fv;
      cyc = cyc + 1;
      r_e = e;  r_otw_q = otw_q;  r_fv = fv;  r_residual = residual;
  end
endmodule
"""
    hdr = module_header(f"{name}: cycle-true RNM top (DTC+BBPD ADPLL)",
                        "transplant of pllsim.export.rnm_golden.golden_adpll_bbpd")
    return hdr + body, cols


# --------------------------------------------------------------- ILCM/MDLL
def _top_realign(cfg, name: str, mdll: bool) -> tuple[str, list[str]]:
    cols = (["e_pre", "tune"] if mdll else ["e", "f_corr"])
    ports, dbg = _dbg_ports(cols)
    c = cfg
    if mdll:
        extra = (_p("KDCO", c.osc.gain, "tuning DAC gain [Hz/LSB]") +
                 _p("TUNE_KI", c.tune_ki_lsb, "integrator step [LSB]") +
                 _p("MUX_JIT", c.mux_jitter_rms_s, "mux jitter [s], EN_NOISE"))
    else:
        extra = (_p("BETA", c.beta, "realignment factor") +
                 _p("FTL_LSB", c.ftl_f_lsb, "FTL DAC LSB [Hz]") +
                 _p("FTL_MU", c.ftl_mu, "FTL step multiplier") +
                 _p("INJ_JIT", c.inj_jitter_rms_s, "injection jitter [s]"))
    params = (
        _p("FREF", c.fref, "") + _p("TREF", 1.0 / c.fref, "") +
        _p("F0", c.osc.f0, "free-running frequency [Hz]") +
        _p("FOUT", c.fout, "target output [Hz]") +
        _p("F_FREE_ERR", 0.0, "initial free-running error [Hz]") +
        extra + _pi("EN_NOISE", 0, "") + _pi("SEED", 6, ""))
    if mdll:
        loop = """\
      f_free = F0 + KDCO*tune + F_FREE_ERR;
      dphi = 6.283185307179586*(f_free - FOUT)*TREF;
      e_pre = e + dphi;
      if (e_pre > 0.0) tune = tune - TUNE_KI;
      else if (e_pre < 0.0) tune = tune + TUNE_KI;
      e = 0.0;
      if (EN_NOISE)
        e = 6.283185307179586*FOUT*$rdist_normal(seed,0,1000000)/1.0e6*MUX_JIT;
      r_e_pre = e_pre;  r_tune = tune;
"""
        decls = "  real e, e_pre, tune, f_free, dphi;\n"
        inits = "    e = 0.0; tune = 0.0;\n"
    else:
        loop = """\
      f_free = F0 + F_FREE_ERR + f_corr;
      dphi = 6.283185307179586*(f_free - FOUT)*TREF;
      e_pre = e + dphi;
      e_wrap = wrap_pm(e_pre);
      phi_inj = 0.0;
      if (EN_NOISE)
        phi_inj = 6.283185307179586*FOUT*$rdist_normal(seed,0,1000000)/1.0e6*INJ_JIT;
      e = (1.0 - BETA)*e_wrap + BETA*phi_inj;
      drift = e_pre - e;
      if (drift > 0.0) f_corr = f_corr - FTL_MU*FTL_LSB;
      else if (drift < 0.0) f_corr = f_corr + FTL_MU*FTL_LSB;
      r_e = e;  r_f_corr = f_corr;
"""
        decls = "  real e, e_pre, e_wrap, phi_inj, f_corr, f_free, dphi, drift;\n"
        inits = "    e = 0.0; f_corr = 0.0;\n"
    body = f"""\
`timescale 1fs/1fs
module {name}_top_rnm #(
{params}  parameter integer EMIT_UNUSED = 0
) (
  input ref_clk{ports}
);
{dbg}{_wrap_pm() if not mdll else ''}{decls}\
  integer cyc, seed;

  initial begin
{inits}\
    cyc = 0; seed = SEED;
  end

  always @(posedge ref_clk) begin
{loop}\
      cyc = cyc + 1;
  end
endmodule
"""
    kind = "MDLL (edge replacement)" if mdll else "ILCM (realignment)"
    src = "golden_mdll" if mdll else "golden_ilcm"
    hdr = module_header(f"{name}: cycle-true RNM top ({kind})",
                        f"transplant of pllsim.export.rnm_golden.{src}")
    return hdr + body, cols


# ---------------------------------------------------------------- dispatch
def emit_rnm_top(kind: str, cfg, name: str) -> tuple[str, list[str]]:
    """Returns (module_text, golden_column_names) for `<name>_top_rnm`."""
    if kind in ("cppll_int", "cppll_frac"):
        return _top_cppll(cfg, name)
    if kind in ("sspll_int", "sspll_frac"):
        return _top_sspll(cfg, name)
    if kind in ("spll", "spll_frac"):
        return _top_spll(cfg, name)
    if kind == "adpll_tdc":
        return _top_adpll_tdc(cfg, name)
    if kind == "adpll_bbpd":
        return _top_adpll_bbpd(cfg, name)
    if kind == "ilcm":
        return _top_realign(cfg, name, mdll=False)
    if kind == "mdll":
        return _top_realign(cfg, name, mdll=True)
    raise ValueError(f"unknown RNM arch kind {kind}")


def emit_rnm_tb(name: str, cols: list[str], fref: float, n: int,
                int_cols: tuple[str, ...] = ()) -> str:
    """Golden-CSV self-checking testbench (run on Cadence: xrun -sv ...)."""
    fmt = "%d," + ",".join("%f" for _ in cols)
    scan_args = ", ".join(["g_cycle"] + [f"g_{c}" for c in cols])
    checks = ""
    for c in cols:
        tol = "1e-12" if c in int_cols else \
            f"( (g_{c} < 0.0 ? -g_{c} : g_{c})*1.0e-6 + 1.0e-9 )"
        checks += f"""\
      diff = dbg_{c} - g_{c};
      if (diff < 0.0) diff = -diff;
      if (diff > {tol}) begin
        errors = errors + 1;
        if (errors < 10)
          $display("FAIL {name} cycle %0d col {c}: dut=%g gold=%g",
                   i, dbg_{c}, g_{c});
      end
"""
    dbg_ports = ", ".join(f".dbg_{c}(dbg_{c})" for c in cols)
    dbg_decl = "  " + "  ".join(f"wreal dbg_{c};" for c in cols) + "\n"
    half_fs = 0.5e15 / fref
    return f"""\
// self-checking RNM testbench for {name} — compares every cycle against
// golden_rnm.csv (generated by pllsim.export.rnm_golden, noise-free).
// run: xrun -ams {name}_top_rnm.vams tb_{name}_rnm.vams
`timescale 1fs/1fs
module tb_{name}_rnm;
  reg ref_clk = 0;
{dbg_decl}
  real g_{', g_'.join(cols)};
  real diff;
  integer fd, i, ok, errors, g_cycle;

  {name}_top_rnm dut (.ref_clk(ref_clk), {dbg_ports});

  always #({half_fs:.0f}) ref_clk = ~ref_clk;

  initial begin
    errors = 0;
    fd = $fopen("golden_rnm.csv", "r");
    if (fd == 0) begin $display("FAIL cannot open golden_rnm.csv"); $finish; end
    ok = $fgets(scratch, fd);          // header line
    for (i = 0; i < {n}; i = i + 1) begin
      ok = $fscanf(fd, "{fmt}\\n", {scan_args});
      @(posedge ref_clk);
      #1;
{checks}\
    end
    if (errors == 0) $display("PASS {name} RNM golden check ({n} cycles)");
    else $display("FAIL {name}: %0d mismatches", errors);
    $finish;
  end
  reg [1023:0] scratch;
endmodule
"""
