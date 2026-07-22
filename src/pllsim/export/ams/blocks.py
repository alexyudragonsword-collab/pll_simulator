"""Electrical Verilog-AMS block library (block-level AMS verification).

Continuous-time models with electrical disciplines: the loop filter is the
REAL R/C netlist from FilterDesign, the charge pump is switched current
sources, the VCO integrates a bounded phase.  Digital timing blocks (PFD,
divider, MASH) remain in the digital kernel — the intended AMS Designer
partition.  Transient runs are deterministic; white_noise() contributions
exist only for small-signal .noise analyses (README: use the RNM flavor for
jitter).
"""
from ..formatting import module_header

_PFD = """\
`timescale 1fs/1fs
module pllsim_pfd (
  input  ref_clk,
  input  div_clk,
  output reg up,
  output reg dn
);
  // tri-state PFD with delayed reset (anti-backlash handled in the CP model)
  wire rst = up & dn;
  always @(posedge ref_clk or posedge rst)
    if (rst) up <= 1'b0; else up <= 1'b1;
  always @(posedge div_clk or posedge rst)
    if (rst) dn <= 1'b0; else dn <= 1'b1;
  initial begin up = 0; dn = 0; end
endmodule
"""

_CP_E = """\
`include "disciplines.vams"
module pllsim_cp_e (up, dn, out);
  parameter real ICP    = 1.5e-3;   // nominal current [A]
  parameter real MISPCT = 0.0;      // (Iup-Idn)/Icp in percent
  parameter real ILEAK  = 0.0;      // static leakage [A]
  parameter real TTR    = 20e-12;   // switch transition time [s]
  input up, dn;
  output out;
  electrical out;
  analog begin
    I(out) <+ -ICP*(1.0+0.005*MISPCT)*transition(up ? 1.0 : 0.0, 0.0, TTR, TTR)
              +ICP*(1.0-0.005*MISPCT)*transition(dn ? 1.0 : 0.0, 0.0, TTR, TTR)
              + ILEAK;
  end
endmodule
"""

_LF_E = """\
`include "disciplines.vams"
module pllsim_lf_e (n1, vctrl);
  parameter real C1 = 680e-12;   // series branch capacitor [F]
  parameter real R2 = 20e3;      // series branch resistor [ohm]
  parameter real C2 = 3.3e-12;   // node capacitor [F]
  parameter real R3 = 0.0;       // 3rd-order pole resistor (0 = 2nd order)
  parameter real C3 = 0.0;
  inout n1;
  output vctrl;
  electrical n1, vctrl, nz;
  analog begin
    I(n1)     <+ C2*ddt(V(n1));            // C2: node1 -> gnd
    I(n1, nz) <+ V(n1, nz)/R2;             // series R2 ...
    I(nz)     <+ C1*ddt(V(nz));            // ... + C1 -> gnd
    if (R3 > 0.0) begin
      I(n1, vctrl) <+ V(n1, vctrl)/R3;     // R3 to the vctrl node
      I(vctrl)     <+ C3*ddt(V(vctrl));    // C3 -> gnd
    end else
      V(vctrl, n1) <+ 0.0;                 // 2nd order: vctrl = node1
  end
endmodule
"""

_VCO_E = """\
`include "disciplines.vams"
`timescale 1fs/1fs
module pllsim_vco_e (ctrl, vout, clk);
  parameter real F0   = 4.75e9;   // [Hz]
  parameter real KVCO = 60e6;     // [Hz/V]
  parameter real NL1  = 0.0;      // f = F0 + KVCO*v*(1+NL1*v+NL2*v^2)
  parameter real NL2  = 0.0;
  parameter real VAMP = 0.4;      // output swing [V]
  input ctrl;
  output vout;
  output reg clk;
  electrical ctrl, vout;
  real fv, ph;
  analog begin
    fv = F0 + KVCO*V(ctrl)*(1.0 + NL1*V(ctrl) + NL2*V(ctrl)*V(ctrl));
    ph = idtmod(fv, 0.0, 1.0, -0.5);       // bounded phase [cycles]
    V(vout) <+ VAMP*sin(`M_TWO_PI*ph);
    @(cross(ph - 0.25, +1)) clk = 1'b1;    // one event pair per VCO cycle:
    @(cross(ph + 0.25, +1)) clk = 1'b0;    // dominates AMS runtime at GHz
  end
  initial clk = 0;
endmodule
"""

_SAMPLER_E = """\
`include "disciplines.vams"
`timescale 1fs/1fs
module pllsim_sampler_e (ref_clk, vco_in, gate, iout);
  parameter real GM   = 1e-3;     // pulser transconductance [A/V]
  parameter real TPUL = 150e-12;  // gm window [s]
  parameter real VPED = 0.0;      // sampling pedestal [V]
  parameter real TTR  = 10e-12;   // sample settling [s]
  parameter integer INVERT = 1;   // SSPLL uses an inverting gm
  input ref_clk, gate;
  input vco_in;
  output iout;
  electrical vco_in, iout;
  real vheld, win;
  always @(posedge ref_clk) begin
    vheld = V(vco_in);            // ideal track-and-hold at the ref edge
    win = 1.0;
    win <= #(TPUL*1.0e15) 0.0;
  end
  analog begin
    I(iout) <+ (INVERT ? 1.0 : -1.0) * GM
               * transition(win, 0.0, TTR, TTR)
               * (vheld + VPED) * (gate ? 1.0 : 0.0);
  end
  initial begin vheld = 0.0; win = 0.0; end
endmodule
"""

_INJ_OSC_E = """\
`include "disciplines.vams"
`timescale 1fs/1fs
module pllsim_inj_osc_e (inj, tune, vout, clk);
  parameter real F0    = 12e9;    // free-running frequency [Hz]
  parameter real KDCO  = 0.0;     // tuning gain [Hz/LSB-volt on tune]
  parameter real BETA  = 0.6;     // realignment factor (1.0 = MDLL replace)
  parameter real VAMP  = 0.3;
  input inj;
  input tune;
  output vout;
  output reg clk;
  electrical tune, vout;
  real fv, ph, e_off, ph_at_inj;
  // phase-domain realignment: at each injection the phase error toward the
  // nearest edge is multiplied by (1-BETA).  This is a behavioral phase
  // model, NOT a transistor-level mux — see the generated README.
  analog begin
    fv = F0 + KDCO*V(tune);
    ph = idtmod(fv, 0.0, 1.0, -0.5) + e_off;
    V(vout) <+ VAMP*sin(`M_TWO_PI*ph);
    @(cross(ph - 0.25, +1)) clk = 1'b1;
    @(cross(ph + 0.25, +1)) clk = 1'b0;
  end
  always @(posedge inj) begin
    ph_at_inj = e_off;                       // accumulated offset
    e_off = (1.0 - BETA)*(ph_at_inj - $floor(ph_at_inj + 0.5));
  end
  initial begin e_off = 0.0; clk = 0; end
endmodule
"""


def emit_ams_library() -> list[tuple[str, str]]:
    return [
        ("pllsim_pfd", module_header(
            "tri-state PFD (digital kernel)",
            "behavioral PFD for the electrical CPPLL core") + _PFD),
        ("pllsim_cp_e", module_header(
            "electrical charge pump: switched current sources",
            "transplant of pllsim.blocks.chargepump.CPConfig") + _CP_E),
        ("pllsim_lf_e", module_header(
            "electrical loop filter: the real R/C netlist",
            "transplant of pllsim.blocks.loopfilter.FilterDesign") + _LF_E),
        ("pllsim_vco_e", module_header(
            "electrical VCO: nonlinear tuning, bounded phase, sine + clock",
            "transplant of pllsim.blocks.oscillator.OscConfig.freq_law") + _VCO_E),
        ("pllsim_sampler_e", module_header(
            "electrical sampling PD front-end: T&H + windowed gm current",
            "transplant of pllsim.blocks.sampler.SamplingPD") + _SAMPLER_E),
        ("pllsim_inj_osc_e", module_header(
            "electrical injection-locked oscillator (phase-domain realign)",
            "transplant of pllsim.arch.ilcm realignment recursion") + _INJ_OSC_E),
    ]
