"""Bit-true control FSM RTL: FTL, band select, FLL.

All three operate purely on integers (counter counts, band indices, DAC
codes), so the golden mirrors are small integer-domain Python classes in
fixedpoint.py (FtlFx, BandSelectFx, FllFx).
"""
from ..formatting import module_header

_FTL = """\
module pllsim_ftl #(
  parameter integer W_DAC = 16,     // signed frequency-DAC code width
  parameter integer MU    = 1,      // step in DAC LSB per update
  parameter integer GEAR_N = 0,     // 0 = no gearshift
  parameter integer MU_F  = 1,
  parameter integer W_CNT = 32
) (
  input  wire               clk,
  input  wire               rst_n,
  input  wire               en,          // one FD decision per cycle
  input  wire               drift_pos,   // sign of observed drift
  input  wire               drift_zero,  // drift exactly zero -> hold
  output reg signed [W_DAC-1:0] f_code   // frequency correction [DAC LSB]
);
  reg [W_CNT-1:0] n;
  wire [W_CNT-1:0] mu_now = (GEAR_N != 0 && n > GEAR_N) ? MU_F : MU;

  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      f_code <= {W_DAC{1'b0}};
      n      <= {W_CNT{1'b0}};
    end else if (en) begin
      n <= n + 1'b1;
      if (!drift_zero)
        f_code <= drift_pos ? f_code - mu_now[W_DAC-1:0]
                            : f_code + mu_now[W_DAC-1:0];
    end
  end
endmodule
"""

_BSEL = """\
module pllsim_bandselect #(
  parameter integer W_BAND   = 6,    // band index width (n_bands <= 2^W_BAND)
  parameter integer N_BANDS  = 32,
  parameter integer W_CNT    = 32,   // frequency-count width
  parameter integer TARGET   = 0     // target counts per measurement window
) (
  input  wire               clk,
  input  wire               rst_n,
  input  wire               meas_valid,   // pulses once per finished window
  input  wire [W_CNT-1:0]   meas_counts,  // counter counts in the window
  output reg  [W_BAND-1:0]  band,         // band under trial / final choice
  output reg                done
);
  reg [W_BAND-1:0] lo, hi, best_band;
  reg [W_CNT-1:0]  best_err;
  wire signed [W_CNT:0] err = $signed({1'b0, meas_counts}) - TARGET;
  wire [W_CNT-1:0] abs_err = err[W_CNT] ? (~err[W_CNT-1:0] + 1'b1)
                                        : err[W_CNT-1:0];

  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      lo <= {W_BAND{1'b0}};
      hi <= N_BANDS - 1;
      band <= (N_BANDS - 1) / 2;
      best_band <= (N_BANDS - 1) / 2;
      best_err <= {W_CNT{1'b1}};
      done <= (N_BANDS <= 1);
    end else if (meas_valid && !done) begin
      if (abs_err < best_err) begin
        best_err  <= abs_err;
        best_band <= band;
      end
      if (err[W_CNT]) begin           // measured low -> go up
        if (band == hi) begin
          done <= 1'b1;
          band <= (abs_err < best_err) ? band : best_band;
        end else begin
          lo   <= band + 1'b1;
          band <= (band + 1'b1 + hi) >> 1;
        end
      end else begin                  // measured high (or equal) -> go down
        if (band == lo) begin
          done <= 1'b1;
          band <= (abs_err < best_err) ? band : best_band;
        end else begin
          hi   <= band - 1'b1;
          band <= (lo + band - 1'b1) >> 1;
        end
      end
    end
  end
endmodule
"""

_FLL = """\
module pllsim_fll #(
  parameter integer W_CNT    = 20,   // per-window cycle-count accumulator width
  parameter integer WINDOW   = 64,   // ref cycles per FD window
  parameter integer N_TARGET = 0,    // expected counts per window (N*WINDOW)
  parameter integer TH_ENG   = 0,    // engage threshold [counts per window]
  parameter integer TH_REL   = 0,    // release threshold [counts per window]
  parameter integer HYST     = 3     // consecutive windows for a transition
) (
  input  wire                  clk,       // reference clock
  input  wire                  rst_n,
  input  wire [7:0]            cycles,    // VCO cycles counted this ref period
  output reg                   engaged,   // 1 = FLL drives, sampler gated off
  output reg  signed [W_CNT:0] ferr,      // last window count error
  output reg                   fd_valid   // pulses when ferr updates
);
  reg [W_CNT-1:0] acc;
  reg [15:0]      w;
  reg [3:0]       quiet;
  wire [W_CNT-1:0] acc_next = acc + {{(W_CNT-8){1'b0}}, cycles};
  wire window_end = (w == WINDOW - 1);
  wire signed [W_CNT:0] ferr_next = $signed({1'b0, acc_next}) - N_TARGET;
  wire [W_CNT:0] abs_ferr = ferr_next[W_CNT] ? (~ferr_next + 1'b1) : ferr_next;

  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      acc <= {W_CNT{1'b0}};  w <= 16'd0;  quiet <= 4'd0;
      engaged <= 1'b1;  ferr <= {(W_CNT+1){1'b0}};  fd_valid <= 1'b0;
    end else begin
      fd_valid <= 1'b0;
      if (window_end) begin
        acc  <= {W_CNT{1'b0}};
        w    <= 16'd0;
        ferr <= ferr_next;
        fd_valid <= 1'b1;
        if (engaged) begin
          if (abs_ferr < TH_REL) begin
            if (quiet == HYST - 1) begin
              engaged <= 1'b0;  quiet <= 4'd0;
            end else quiet <= quiet + 1'b1;
          end else quiet <= 4'd0;
        end else begin
          if (abs_ferr > TH_ENG) begin
            if (quiet == HYST - 1) begin
              engaged <= 1'b1;  quiet <= 4'd0;
            end else quiet <= quiet + 1'b1;
          end else quiet <= 4'd0;
        end
      end else begin
        acc <= acc_next;
        w   <= w + 1'b1;
      end
    end
  end
endmodule
"""


def emit_ftl() -> tuple[str, str]:
    return "pllsim_ftl", module_header(
        "bang-bang frequency tracking loop (ILCM/MDLL)",
        "integer transplant of pllsim.calibration.ftl.FTL") + _FTL


def emit_bandselect() -> tuple[str, str]:
    return "pllsim_bandselect", module_header(
        "binary-search coarse band selection",
        "integer transplant of pllsim.calibration.gain_cal.BandSelect") + _BSEL


def emit_fll() -> tuple[str, str]:
    return "pllsim_fll", module_header(
        "counter-FD frequency-locked acquisition state machine (SSPLL/SPLL)",
        "integer transplant of pllsim.calibration.ftl.FLLStateMachine") + _FLL
