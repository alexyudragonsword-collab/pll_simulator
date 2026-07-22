"""Bit-true digital loop filter RTL (power-of-two coefficients as shifts).

Mirrors pllsim.export.fixedpoint.DlfFx exactly:
  acc += e >>> SH_R;  y = (e >>> SH_A) + acc;  per IIR stage:
  s += (y - s) >>> SH_L;  y = s.
Verilog >>> on signed values = floor division, same as Python >> on ints.
The registered output after clock n equals DlfFx.step(e[n]).
"""
from ..formatting import module_header


def emit_dlf(n_iir: int) -> tuple[str, str]:
    name = "pllsim_dlf"
    iir_params = "".join(
        f"  parameter integer SH_L{i} = 1,   // IIR stage {i}: lam = 2^-SH_L{i}\n"
        for i in range(n_iir))
    iir_state = "".join(f"  reg signed [W-1:0] s{i};\n" for i in range(n_iir))
    prev = "y_pi"
    iir_wires = ""
    for i in range(n_iir):
        iir_wires += (f"  wire signed [W-1:0] s{i}_next = "
                      f"s{i} + (({prev} - s{i}) >>> SH_L{i});\n")
        prev = f"s{i}_next"
    iir_reset = "".join(f"      s{i} <= {{W{{1'b0}}}};\n" for i in range(n_iir))
    iir_clk = "".join(f"      s{i} <= s{i}_next;\n" for i in range(n_iir))

    body = module_header(
        "digital loop filter: y = alpha*e + rho*sum(e), optional IIR stages",
        "bit-true mirror of pllsim.export.fixedpoint.DlfFx") + f"""\
module {name} #(
  parameter integer W    = 32,   // signed datapath width
  parameter integer SH_A = 4,    // alpha = 2^-SH_A
  parameter integer SH_R = 11,   // rho   = 2^-SH_R
{iir_params}\
  parameter integer UNUSED = 0
) (
  input  wire                 clk,
  input  wire                 rst_n,
  input  wire signed [W-1:0]  e,     // phase error on the 2^-F_IN grid
  output reg  signed [W-1:0]  y
);
  reg  signed [W-1:0] acc;
{iir_state}\
  wire signed [W-1:0] acc_next = acc + (e >>> SH_R);
  wire signed [W-1:0] y_pi     = (e >>> SH_A) + acc_next;
{iir_wires}\

  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      acc <= {{W{{1'b0}}}};
      y   <= {{W{{1'b0}}}};
{iir_reset}\
    end else begin
      acc <= acc_next;
{iir_clk}\
      y   <= {prev};
    end
  end
endmodule
"""
    return name, body
