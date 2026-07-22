"""Standalone wreal (RNM) block library — Cadence Xcelium dialect.

These are the a-la-carte blocks for users assembling their own event-level
netlists (DTC in the clock path, divided-clock generation, LF charge pump).
The golden-checked architecture tops (tops.py) implement the cycle-true
recursion in a single always block instead — one source of sequencing truth
with the Python engine, no cross-module event-ordering hazards; they reuse
these blocks' arithmetic verbatim.
"""
from ..formatting import module_header

_LF = """\
`timescale 1fs/1fs
module pllsim_lf_rnm #(
  parameter integer ORDER = 3,
  parameter real AD11=1.0, AD12=0.0, AD13=0.0,   // exp(A*Tref) row-major;
  parameter real AD21=0.0, AD22=1.0, AD23=0.0,   // identity-padded for ORDER=2
  parameter real AD31=0.0, AD32=0.0, AD33=1.0,
  parameter real B1=0.0, B2=0.0, B3=0.0,         // input vector [1/F]
  parameter real VINIT=0.0
) (
  input  trig,          // one reference-cycle boundary per event
  input  dq,            // charge delivered this cycle [C]
  output vctrl
);
  wreal dq;  wreal vctrl;
  real x1, x2, x3, y1, y2, y3;
  initial begin x1 = VINIT; x2 = VINIT; x3 = VINIT; end
  assign vctrl = (ORDER == 3) ? x3 : x2;   // vctrl = last state (as in Python)
  always @(posedge trig) begin
    y1 = x1 + B1*dq;  y2 = x2 + B2*dq;  y3 = x3 + B3*dq;
    x1 = AD11*y1 + AD12*y2 + AD13*y3;
    x2 = AD21*y1 + AD22*y2 + AD23*y3;
    x3 = AD31*y1 + AD32*y2 + AD33*y3;
  end
endmodule
"""

_VCO = """\
`timescale 1fs/1fs
module pllsim_vco_rnm #(
  parameter real F0    = 4.75e9,   // band-center free-running frequency [Hz]
  parameter real KVCO  = 60e6,     // [Hz/V]
  parameter real NL1   = 0.0,      // f = F0 + KVCO*v*(1 + NL1*v + NL2*v^2)
  parameter real NL2   = 0.0,
  parameter real BAND_STEP = 0.0,  // coarse band pitch [Hz]
  parameter integer NBANDS = 1,
  parameter real JIT_WFM_RAD = 0.0, // per-ref-cycle random-walk sigma [rad]
  parameter real JIT_WPM_RAD = 0.0, // additive white PM sigma [rad]
  parameter integer EN_NOISE = 0,
  parameter integer SEED = 1
) (
  input  ref_clk,       // reference-rate trigger
  input  vctrl,         // wreal control voltage
  input  n_cycles,      // wreal divide ratio for this cycle (integer-valued)
  input  [7:0] band,
  output f_out,         // wreal instantaneous frequency
  output reg div_clk    // divided clock edge (event output)
);
  wreal vctrl, n_cycles, f_out;
  real fv, t_next, dphi_walk, dphi_add, tnow;
  integer seed;
  initial begin seed = SEED; t_next = 0.0; dphi_walk = 0.0; div_clk = 0; end
  assign f_out = fv;

  always @(vctrl or band)
    fv = F0 + (band - (NBANDS-1)/2.0)*BAND_STEP
            + KVCO*vctrl*(1.0 + NL1*vctrl + NL2*vctrl*vctrl);

  // schedule the next divided edge from the closed-form timestamp, exactly
  // as the Python engine does; oscillator noise shifts the edge
  always @(posedge ref_clk) begin
    if (EN_NOISE) begin
      dphi_walk = dphi_walk + $rdist_normal(seed, 0, 1000000)/1.0e6*JIT_WFM_RAD;
      dphi_add  = $rdist_normal(seed, 0, 1000000)/1.0e6*JIT_WPM_RAD;
    end
    tnow  = $realtime*1.0e-15;
    t_next = t_next + n_cycles/fv - (dphi_walk + dphi_add)/(6.283185307179586*fv);
    if (t_next > tnow) begin
      div_clk <= #((t_next - tnow)*1.0e15) 1'b1;
      div_clk <= #((t_next - tnow)*1.0e15 + 0.5/fv*1.0e15) 1'b0;
    end
  end
endmodule
"""

_DTC = """\
`timescale 1fs/1fs
module pllsim_dtc_rnm #(
  parameter real T_RES = 250e-15,      // nominal LSB [s]
  parameter integer NBITS = 12,
  parameter real GAIN_ERR = 0.0,       // true LSB = T_RES*(1+GAIN_ERR)
  parameter real INL_SIN_AMP = 0.0,    // INL = AMP*sin(2*pi*CYC*x + PH)
  parameter real INL_SIN_CYC = 0.0,
  parameter real INL_SIN_PH  = 0.0,
  parameter real JITTER_RMS = 0.0,
  parameter integer EN_NOISE = 0,
  parameter integer SEED = 7
) (
  input  clk_in,
  input  t_target,      // wreal requested (bipolar) delay [s]
  input  gain_corr,     // wreal calibrated code-domain gain (from LMS)
  output reg clk_out
);
  wreal t_target, gain_corr;
  real t_req, t_phys, x;
  integer code, seed;
  localparam real RANGE_S = T_RES * ((1<<NBITS) - 1);
  initial begin seed = SEED; clk_out = 0; end
  always @(posedge clk_in) begin
    t_req = t_target + RANGE_S/2.0;
    code  = t_req*gain_corr/T_RES + 0.5;    // round
    if (code < 0) code = 0;
    if (code > (1<<NBITS)-1) code = (1<<NBITS)-1;
    x = code*1.0/((1<<NBITS)-1);
    t_phys = code*T_RES*(1.0+GAIN_ERR)
           + INL_SIN_AMP*$sin(6.283185307179586*INL_SIN_CYC*x + INL_SIN_PH);
    if (EN_NOISE)
      t_phys = t_phys + $rdist_normal(seed, 0, 1000000)/1.0e6*JITTER_RMS;
    clk_out <= #(t_phys*1.0e15) 1'b1;
    clk_out <= #(t_phys*1.0e15 + 100000) 1'b0;   // 100 ps return
  end
endmodule
"""


def emit_rnm_library() -> list[tuple[str, str]]:
    """(filename_stem, text) pairs for the standalone RNM block library."""
    return [
        ("pllsim_lf_rnm", module_header(
            "RNM loop filter: exact discrete state-space x' = Ad(x + B*dq)",
            "transplant of pllsim.blocks.loopfilter.LoopFilter.update_impulse")
         + _LF),
        ("pllsim_vco_rnm", module_header(
            "RNM VCO: nonlinear tuning law + closed-form divided-edge output",
            "transplant of pllsim.blocks.oscillator (jitter from Leeson map)")
         + _VCO),
        ("pllsim_dtc_rnm", module_header(
            "RNM DTC: code quantization, gain error, sinusoidal INL, jitter",
            "transplant of pllsim.blocks.dtc.DTC") + _DTC),
    ]
