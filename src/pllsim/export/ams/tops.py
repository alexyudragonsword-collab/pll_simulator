"""Electrical AMS tops + scalar-golden testbenches.

Two top styles:
  * full electrical loop (cppll/sspll/spll): PFD/divider/MASH in the digital
    kernel, cp_e -> lf_e (real RC) -> vco_e electrical — verifies the
    continuous-time loop assembly.  Scalar checks only: the continuous
    dynamics legitimately differ from the impulse-discretized Python engine.
  * digital-core + electrical output (adpll/ilcm/mdll): the cycle-true RNM
    core drives an electrical oscillator so downstream RF blocks see a real
    sine at fout.
"""
from __future__ import annotations

from ..formatting import module_header, vreal

AMS_FULL_ELECTRICAL = ("cppll_int", "cppll_frac", "sspll_int", "sspll_frac",
                       "spll")


def emit_ams_top(kind: str, cfg, name: str) -> str:
    if kind in ("cppll_int", "cppll_frac"):
        return _ams_cppll(cfg, name, frac=kind.endswith("frac"))
    if kind in ("sspll_int", "sspll_frac", "spll"):
        return _ams_sampling(cfg, name, kind)
    # digital-core architectures: RNM top + electrical oscillator shell
    return _ams_digital_core(cfg, name, kind)


def _ams_cppll(cfg, name: str, frac: bool) -> str:
    c = cfg
    n_int = int(c.fout // c.fref) if frac else int(round(c.n_div))
    mash_note = ("  // fractional divider control: instantiate the exported\n"
                 "  // rtl/pllsim_mash*.v next to this top and drive n_next\n"
                 if frac else "")
    return module_header(
        f"{name}: full electrical CPPLL core (PFD + CP + RC filter + VCO)",
        "blocks: pllsim_pfd / pllsim_cp_e / pllsim_lf_e / pllsim_vco_e") + f"""\
`include "disciplines.vams"
`timescale 1fs/1fs
module {name}_top_ams (
  input ref_clk,
  output vout,        // electrical VCO output
  output div_clk,
  output osc_clk,     // full-rate clock (frequency measurement)
  output vctrl        // electrical control node (probe)
);
  electrical vout, vctrl;
  wire up, dn;
  wire vco_clk;
  assign osc_clk = vco_clk;
  integer divcnt;
  reg div_q;
{mash_note}
  pllsim_pfd u_pfd (.ref_clk(ref_clk), .div_clk(div_q), .up(up), .dn(dn));
  pllsim_cp_e #(.ICP({vreal(c.cp.icp)}), .MISPCT({vreal(c.cp.mismatch_pct)}),
                .ILEAK({vreal(c.cp.leakage_a)}))
    u_cp (.up(up), .dn(dn), .out(vctrl));
  pllsim_lf_e #(.C1({vreal(c.filt.c1)}), .R2({vreal(c.filt.r2)}),
                .C2({vreal(c.filt.c2)}), .R3({vreal(c.filt.r3)}),
                .C3({vreal(c.filt.c3)}))
    u_lf (.n1(vctrl), .vctrl(vctrl));
  pllsim_vco_e #(.F0({vreal(c.osc.f0)}), .KVCO({vreal(c.osc.gain)}),
                 .NL1({vreal(c.osc.nl1)}), .NL2({vreal(c.osc.nl2)}))
    u_vco (.ctrl(vctrl), .vout(vout), .clk(vco_clk));

  // divide-by-{n_int}
  always @(posedge vco_clk) begin
    divcnt = divcnt + 1;
    if (divcnt >= {n_int}) begin
      divcnt = 0;
      div_q <= 1'b1;
      div_q <= #1000000 1'b0;   // 1 ns pulse
    end
  end
  assign div_clk = div_q;
  initial begin divcnt = 0; div_q = 0; end
endmodule
"""


def _ams_sampling(cfg, name: str, kind: str) -> str:
    c, s = cfg, cfg.sampler
    sub = kind.startswith("sspll")
    note = ("sub-sampling: the ref edge samples the VCO waveform directly"
            if sub else "reference-sampling: a divided edge samples the ref sine")
    return module_header(
        f"{name}: electrical sampling PLL core ({note})",
        "blocks: pllsim_sampler_e / pllsim_lf_e / pllsim_vco_e") + f"""\
`include "disciplines.vams"
`timescale 1fs/1fs
module {name}_top_ams (
  input ref_clk,
  input fll_engaged,   // gate the sampler off during FLL acquisition
  output vout,
  output osc_clk,      // full-rate clock (frequency measurement)
  output vctrl
);
  electrical vout, vctrl;
  wire vco_clk;
  assign osc_clk = vco_clk;
  wire gate = ~fll_engaged;

  pllsim_sampler_e #(.GM({vreal(s.gm)}), .TPUL({vreal(s.pulse_width)}),
                     .VPED({vreal(s.pedestal_v)}), .INVERT({1 if sub else 0}))
    u_pd (.ref_clk(ref_clk), .vco_in(vout), .gate(gate), .iout(vctrl));
  pllsim_lf_e #(.C1({vreal(c.filt.c1)}), .R2({vreal(c.filt.r2)}),
                .C2({vreal(c.filt.c2)}), .R3({vreal(c.filt.r3)}),
                .C3({vreal(c.filt.c3)}))
    u_lf (.n1(vctrl), .vctrl(vctrl));
  pllsim_vco_e #(.F0({vreal(c.osc.f0)}), .KVCO({vreal(c.osc.gain)}),
                 .NL1({vreal(c.osc.nl1)}), .NL2({vreal(c.osc.nl2)}),
                 .VAMP({vreal(s.amp_v)}))
    u_vco (.ctrl(vctrl), .vout(vout), .clk(vco_clk));
  // FLL acquisition path intentionally left to the exported rtl/pllsim_fll.v
  // (digital) + a small charge DAC — see the generated README.
endmodule
"""


def _ams_digital_core(cfg, name: str, kind: str) -> str:
    osc = cfg.osc
    if kind in ("adpll_tdc", "adpll_bbpd"):
        drive = "dbg_otw_q"
        gain = osc.gain
        note = "OTW drives the electrical DCO through an ideal DAC"
    elif kind == "mdll":
        drive = "dbg_tune"
        gain = osc.gain
        note = "tuning integrator drives the electrical oscillator"
    else:
        drive = "dbg_f_corr"
        gain = 1.0
        note = "FTL correction drives the electrical oscillator [Hz/V=1]"
    return module_header(
        f"{name}: cycle-true digital core + electrical oscillator output",
        note) + f"""\
`include "disciplines.vams"
`timescale 1fs/1fs
module {name}_top_ams (
  input ref_clk,
  output vout,
  output osc_clk
);
  electrical vout, dac;
  wreal {drive};
  real ctrl_word;

  {name}_top_rnm u_core (.ref_clk(ref_clk), .{drive}({drive}));

  always @(posedge ref_clk) ctrl_word = {drive};
  analog V(dac) <+ transition(ctrl_word, 0.0, 1e-9, 1e-9);

  pllsim_vco_e #(.F0({vreal(osc.f0)}), .KVCO({vreal(gain)}),
                 .NL1(0.0), .NL2(0.0))
    u_osc (.ctrl(dac), .vout(vout), .clk(osc_clk));
  initial ctrl_word = 0.0;
endmodule
"""


def emit_ams_tb(name: str, kind: str, fref: float, fout: float,
                vctrl_gold: float, t_settle_s: float) -> str:
    """Scalar self-check: output frequency by osc_clk edge counting, plus a
    vctrl bound for the full-electrical tops."""
    half_fs = 0.5e15 / fref
    n_meas = 2000
    full_e = kind in AMS_FULL_ELECTRICAL
    extra_ports = ", .fll_engaged(1'b0)" if kind.startswith(("sspll", "spll")) \
        else ""
    vc_check = ""
    if full_e:
        vc_check = f"""\
    if ((V(x.vctrl) > {vreal(vctrl_gold + 0.05)}) ||
        (V(x.vctrl) < {vreal(vctrl_gold - 0.05)}))
      $display("WARN {name}: vctrl %g vs golden {vreal(vctrl_gold)} +-50mV",
               V(x.vctrl));
"""
    return module_header(
        f"tb_{name}_ams: scalar golden checks (Cadence: xrun -ams ...)",
        f"golden: F_LOCK={vreal(fout)} Hz, settle <= {vreal(t_settle_s)} s") + f"""\
`include "disciplines.vams"
`timescale 1fs/1fs
module tb_{name}_ams;
  parameter real F_LOCK   = {vreal(fout)};
  parameter real F_TOL    = {vreal(max(fout * 1e-4, 1e5))};
  parameter real T_SETTLE = {vreal(t_settle_s)};

  reg ref_clk = 0;
  wire osc_clk;
  integer edges;
  real t0, f_meas;

  {name}_top_ams x (.ref_clk(ref_clk), .osc_clk(osc_clk){extra_ports});

  always #({half_fs:.0f}) ref_clk = ~ref_clk;
  always @(posedge osc_clk) edges = edges + 1;

  initial begin
    edges = 0;
    #(T_SETTLE*1.0e15);
    // measure output frequency over {n_meas} reference periods
    edges = 0;
    t0 = $realtime*1.0e-15;
    repeat ({n_meas}) @(posedge ref_clk);
    f_meas = edges/($realtime*1.0e-15 - t0);
    if (f_meas > F_LOCK - F_TOL && f_meas < F_LOCK + F_TOL)
      $display("PASS {name} AMS: f = %g Hz (golden %g)", f_meas, F_LOCK);
    else
      $display("FAIL {name} AMS: f = %g Hz vs golden %g +- %g",
               f_meas, F_LOCK, F_TOL);
{vc_check}\
    $finish;
  end
endmodule
"""
