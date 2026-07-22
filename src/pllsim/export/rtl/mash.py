"""Bit-true synthesizable MASH modulators (transplants of core/deltasigma.py).

residual_ui = res_num / 2^BITS, where res_num = sum(y)*2^BITS - sum(frac).
Noise shaping bounds res_num, so a signed BITS+4 register never wraps
(EFM1 in (-2^BITS, 0], MASH 1-1 within +-2*2^BITS, MASH 1-1-1 within
+-4*2^BITS) — asserted bit-true against the Python models in tests.
"""
from ..formatting import module_header

EFM1 = module_header("EFM1 — 1st-order error-feedback modulator",
                     "transplant of pllsim.core.deltasigma.Efm1") + """\
module pllsim_efm1 #(
  parameter integer BITS = 24
) (
  input  wire                    clk,
  input  wire                    rst_n,
  input  wire [BITS-1:0]         frac,
  output reg                     y,        // carry out {0,1}
  output reg signed [BITS+3:0]   res_num   // residual_ui = res_num / 2^BITS
);
  reg [BITS-1:0] acc;
  wire [BITS:0]  s1 = {1'b0, acc} + {1'b0, frac};

  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      acc <= {BITS{1'b0}};
      y <= 1'b0;
      res_num <= {(BITS+4){1'b0}};
    end else begin
      acc <= s1[BITS-1:0];
      y   <= s1[BITS];
      res_num <= res_num
                 + ($signed({3'b000, s1[BITS]}) <<< BITS)
                 - $signed({4'b0000, frac});
    end
  end
endmodule
"""

MASH11 = module_header("MASH 1-1 delta-sigma modulator",
                       "transplant of pllsim.core.deltasigma.Mash11") + """\
module pllsim_mash11 #(
  parameter integer BITS = 24
) (
  input  wire                    clk,
  input  wire                    rst_n,
  input  wire [BITS-1:0]         frac,
  output reg  signed [2:0]       y,        // {-1..2}
  output reg  signed [BITS+3:0]  res_num
);
  reg [BITS-1:0] a1, a2;
  reg            c2p;
  wire [BITS:0]  s1 = {1'b0, a1} + {1'b0, frac};
  wire [BITS:0]  s2 = {1'b0, a2} + {1'b0, s1[BITS-1:0]};
  wire signed [2:0] ynext = $signed({2'b00, s1[BITS]})
                          + $signed({2'b00, s2[BITS]})
                          - $signed({2'b00, c2p});

  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      a1 <= {BITS{1'b0}};  a2 <= {BITS{1'b0}};  c2p <= 1'b0;
      y <= 3'sd0;  res_num <= {(BITS+4){1'b0}};
    end else begin
      a1  <= s1[BITS-1:0];
      a2  <= s2[BITS-1:0];
      c2p <= s2[BITS];
      y   <= ynext;
      res_num <= res_num
                 + ({{(BITS+1){ynext[2]}}, ynext} <<< BITS)
                 - $signed({4'b0000, frac});
    end
  end
endmodule
"""

MASH111 = module_header("MASH 1-1-1 delta-sigma modulator",
                        "transplant of pllsim.core.deltasigma.Mash111") + """\
module pllsim_mash111 #(
  parameter integer BITS = 24
) (
  input  wire                    clk,
  input  wire                    rst_n,
  input  wire [BITS-1:0]         frac,
  output reg  signed [3:0]       y,        // {-3..4}
  output reg  signed [BITS+3:0]  res_num
);
  reg [BITS-1:0] a1, a2, a3;
  reg            c2p, c3p, c3pp;
  wire [BITS:0]  s1 = {1'b0, a1} + {1'b0, frac};
  wire [BITS:0]  s2 = {1'b0, a2} + {1'b0, s1[BITS-1:0]};
  wire [BITS:0]  s3 = {1'b0, a3} + {1'b0, s2[BITS-1:0]};
  // y = c1 + (c2 - c2p) + (c3 - 2*c3p + c3pp)
  wire signed [3:0] ynext = $signed({3'b000, s1[BITS]})
                          + $signed({3'b000, s2[BITS]}) - $signed({3'b000, c2p})
                          + $signed({3'b000, s3[BITS]})
                          - ($signed({3'b000, c3p}) <<< 1)
                          + $signed({3'b000, c3pp});

  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      a1 <= {BITS{1'b0}};  a2 <= {BITS{1'b0}};  a3 <= {BITS{1'b0}};
      c2p <= 1'b0;  c3p <= 1'b0;  c3pp <= 1'b0;
      y <= 4'sd0;  res_num <= {(BITS+4){1'b0}};
    end else begin
      a1   <= s1[BITS-1:0];
      a2   <= s2[BITS-1:0];
      a3   <= s3[BITS-1:0];
      c2p  <= s2[BITS];
      c3pp <= c3p;
      c3p  <= s3[BITS];
      y    <= ynext;
      res_num <= res_num
                 + ({{BITS{ynext[3]}}, ynext} <<< BITS)
                 - $signed({4'b0000, frac});
    end
  end
endmodule
"""


def emit_efm1() -> tuple[str, str]:
    return "pllsim_efm1", EFM1


def emit_mash11() -> tuple[str, str]:
    return "pllsim_mash11", MASH11


def emit_mash111() -> tuple[str, str]:
    return "pllsim_mash111", MASH111
