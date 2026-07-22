"""Bit-true sign-sign LMS gain calibrator RTL.

Mirrors pllsim.export.fixedpoint.SignSignLmsFx:
  err_mean += (err - err_mean) >>> SH_EMA   (same for reg_mean)
  e = err - err_mean; d = reg - reg_mean
  step = 1 << max(F_GAIN - sh_mu, 0), sh_mu gear-shifts after GEAR_N cycles
  if (e != 0 && d != 0) gain +/-= step by sign agreement
Gain word is unsigned around 1.0 = 1 << F_GAIN.  The registered gain after
clock n equals SignSignLmsFx.step(err[n], reg[n]).
"""
from ..formatting import module_header

_BODY = """\
module pllsim_sslms #(
  parameter integer W_ERR   = 24,  // signed err/reg input width
  parameter integer F_GAIN  = 24,  // gain fixed point: 1.0 = 1<<F_GAIN
  parameter integer W_GAIN  = 28,  // gain register width (unsigned)
  parameter integer SH_MU   = 18,  // mu = 2^-SH_MU
  parameter integer SH_MUF  = 21,  // mu after gearshift
  parameter integer SH_EMA  = 10,  // ema = 2^-SH_EMA
  parameter integer GEAR_N  = 60000,
  parameter integer W_CNT   = 32
) (
  input  wire                     clk,
  input  wire                     rst_n,
  input  wire signed [W_ERR-1:0]  err,
  input  wire signed [W_ERR-1:0]  reg_in,
  output reg        [W_GAIN-1:0]  gain    // starts at 1.0 = 1<<F_GAIN
);
  reg signed [W_ERR-1:0] err_mean, reg_mean;
  reg        [W_CNT-1:0] n;

  wire signed [W_ERR-1:0] em_next = err_mean + ((err    - err_mean) >>> SH_EMA);
  wire signed [W_ERR-1:0] rm_next = reg_mean + ((reg_in - reg_mean) >>> SH_EMA);
  wire signed [W_ERR-1:0] e = err    - em_next;
  wire signed [W_ERR-1:0] d = reg_in - rm_next;

  wire              gear   = (n > GEAR_N);
  wire [5:0]        sh_now = gear ? SH_MUF[5:0] : SH_MU[5:0];
  wire [W_GAIN-1:0] one    = { {(W_GAIN-1){1'b0}}, 1'b1 };
  wire [W_GAIN-1:0] step   = (F_GAIN > sh_now) ? (one << (F_GAIN - sh_now)) : one;

  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      err_mean <= {W_ERR{1'b0}};
      reg_mean <= {W_ERR{1'b0}};
      n        <= {W_CNT{1'b0}};
      gain     <= one << F_GAIN;   // 1.0
    end else begin
      err_mean <= em_next;
      reg_mean <= rm_next;
      n        <= n + 1'b1;
      if (e != 0 && d != 0)
        gain <= (e[W_ERR-1] == d[W_ERR-1]) ? gain + step : gain - step;
    end
  end
endmodule
"""


def emit_sslms() -> tuple[str, str]:
    return "pllsim_sslms", module_header(
        "sign-sign LMS gain calibration with EMA DC removal + gearshift",
        "bit-true mirror of pllsim.export.fixedpoint.SignSignLmsFx") + _BODY
