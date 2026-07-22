"""Self-checking iverilog testbench generators (zero-tolerance compare).

Pattern: stimulus applied at negedge, DUT clocks at posedge, outputs compared
one timestep later against the mirror-produced expected memory.  Prints
"PASS <name>" or "FAIL ..." lines; the pytest wrapper asserts on stdout.
Vector files are referenced relative to the tb location (run vvp from rtl/).
"""
from __future__ import annotations


def _harness(name: str, n: int, decls: str, dut: str, drive: str,
             compare: str) -> str:
    return f"""\
`timescale 1ns/1ps
module tb_{name};
  reg clk = 0, rst_n = 0;
  integer i, errors;
{decls}
  always #5 clk = ~clk;

{dut}

  initial begin
    errors = 0;
    i = 0;
    // hold reset until the first stimulus negedge: no clock edge may hit the
    // DUT with undriven inputs, or its state diverges from the golden mirror
    for (i = 0; i < {n}; i = i + 1) begin
      @(negedge clk);
      rst_n = 1;
{drive}
      @(posedge clk);
      #1;
{compare}
    end
    if (errors == 0) $display("PASS {name}");
    else $display("FAIL {name}: %0d mismatches", errors);
    $finish;
  end
endmodule
"""


def tb_mash(kind: str, bits: int, n: int) -> tuple[str, str]:
    ywidth = {"efm1": 1, "mash11": 3, "mash111": 4}[kind]
    ydecl = "wire y;" if ywidth == 1 else f"wire signed [{ywidth - 1}:0] y;"
    decls = f"""\
  reg [{bits - 1}:0] stim [0:{n - 1}];
  reg [{ywidth - 1}:0] exp_y [0:{n - 1}];
  reg [{bits + 3}:0] exp_res [0:{n - 1}];
  reg [{bits - 1}:0] frac;
  {ydecl}
  wire signed [{bits + 3}:0] res_num;
  initial begin
    $readmemh("vectors/{kind}_frac.hex", stim);
    $readmemh("vectors/{kind}_y.hex", exp_y);
    $readmemh("vectors/{kind}_res.hex", exp_res);
  end"""
    dut = (f"  pllsim_{kind} #(.BITS({bits})) dut "
           f"(.clk(clk), .rst_n(rst_n), .frac(frac), .y(y), .res_num(res_num));")
    drive = "      frac = stim[i];"
    compare = f"""\
      if ({'{y}' if ywidth == 1 else 'y'} !== $signed(exp_y[i]) ||
          res_num !== $signed(exp_res[i])) begin
        errors = errors + 1;
        if (errors < 5)
          $display("FAIL {kind} @%0d: y=%0d exp=%0d res=%0d exp=%0d",
                   i, y, $signed(exp_y[i]), res_num, $signed(exp_res[i]));
      end"""
    if ywidth == 1:
        compare = compare.replace("{y} !== $signed(exp_y[i])",
                                  "y !== exp_y[i][0]")
    return f"tb_{kind}.v", _harness(kind, n, decls, dut, drive, compare)


def tb_dlf(w: int, sh_a: int, sh_r: int, sh_iir: tuple[int, ...],
           n: int) -> tuple[str, str]:
    iir_p = "".join(f", .SH_L{i}({s})" for i, s in enumerate(sh_iir))
    decls = f"""\
  reg [{w - 1}:0] stim [0:{n - 1}];
  reg [{w - 1}:0] expv [0:{n - 1}];
  reg signed [{w - 1}:0] e;
  wire signed [{w - 1}:0] y;
  initial begin
    $readmemh("vectors/dlf_e.hex", stim);
    $readmemh("vectors/dlf_y.hex", expv);
  end"""
    dut = (f"  pllsim_dlf #(.W({w}), .SH_A({sh_a}), .SH_R({sh_r}){iir_p}) dut "
           f"(.clk(clk), .rst_n(rst_n), .e(e), .y(y));")
    drive = "      e = $signed(stim[i]);"
    compare = """\
      if (y !== $signed(expv[i])) begin
        errors = errors + 1;
        if (errors < 5)
          $display("FAIL dlf @%0d: y=%0d exp=%0d", i, y, $signed(expv[i]));
      end"""
    return "tb_dlf.v", _harness("dlf", n, decls, dut, drive, compare)


def tb_sslms(w_err: int, f_gain: int, w_gain: int, sh_mu: int, sh_muf: int,
             sh_ema: int, gear_n: int, n: int) -> tuple[str, str]:
    decls = f"""\
  reg [{w_err - 1}:0] stim_e [0:{n - 1}];
  reg [{w_err - 1}:0] stim_r [0:{n - 1}];
  reg [{w_gain - 1}:0] expv [0:{n - 1}];
  reg signed [{w_err - 1}:0] err, reg_in;
  wire [{w_gain - 1}:0] gain;
  initial begin
    $readmemh("vectors/sslms_err.hex", stim_e);
    $readmemh("vectors/sslms_reg.hex", stim_r);
    $readmemh("vectors/sslms_gain.hex", expv);
  end"""
    dut = (f"  pllsim_sslms #(.W_ERR({w_err}), .F_GAIN({f_gain}), "
           f".W_GAIN({w_gain}), .SH_MU({sh_mu}), .SH_MUF({sh_muf}), "
           f".SH_EMA({sh_ema}), .GEAR_N({gear_n})) dut\n"
           f"    (.clk(clk), .rst_n(rst_n), .err(err), .reg_in(reg_in), "
           f".gain(gain));")
    drive = ("      err = $signed(stim_e[i]);\n"
             "      reg_in = $signed(stim_r[i]);")
    compare = """\
      if (gain !== expv[i]) begin
        errors = errors + 1;
        if (errors < 5)
          $display("FAIL sslms @%0d: g=%0d exp=%0d", i, gain, expv[i]);
      end"""
    return "tb_sslms.v", _harness("sslms", n, decls, dut, drive, compare)


def tb_ftl(w_dac: int, mu: int, gear_n: int, mu_f: int, n: int) -> tuple[str, str]:
    decls = f"""\
  reg [1:0] stim [0:{n - 1}];
  reg [{w_dac - 1}:0] expv [0:{n - 1}];
  reg drift_pos, drift_zero;
  wire signed [{w_dac - 1}:0] f_code;
  initial begin
    $readmemh("vectors/ftl_drift.hex", stim);
    $readmemh("vectors/ftl_code.hex", expv);
  end"""
    dut = (f"  pllsim_ftl #(.W_DAC({w_dac}), .MU({mu}), .GEAR_N({gear_n}), "
           f".MU_F({mu_f})) dut\n    (.clk(clk), .rst_n(rst_n), .en(1'b1), "
           f".drift_pos(drift_pos), .drift_zero(drift_zero), .f_code(f_code));")
    drive = ("      drift_pos = stim[i][1];\n"
             "      drift_zero = stim[i][0];")
    compare = """\
      if (f_code !== $signed(expv[i])) begin
        errors = errors + 1;
        if (errors < 5)
          $display("FAIL ftl @%0d: c=%0d exp=%0d", i, f_code, $signed(expv[i]));
      end"""
    return "tb_ftl.v", _harness("ftl", n, decls, dut, drive, compare)


def tb_bandselect(n_bands: int, target: int, w_cnt: int, w_band: int,
                  n: int) -> tuple[str, str]:
    decls = f"""\
  reg [{w_cnt - 1}:0] stim [0:{n - 1}];
  reg [{w_band - 1}:0] exp_b [0:{n - 1}];
  reg [0:0] exp_d [0:{n - 1}];
  reg [{w_cnt - 1}:0] meas;
  wire [{w_band - 1}:0] band;
  wire done;
  initial begin
    $readmemh("vectors/bsel_meas.hex", stim);
    $readmemh("vectors/bsel_band.hex", exp_b);
    $readmemh("vectors/bsel_done.hex", exp_d);
  end"""
    dut = (f"  pllsim_bandselect #(.W_BAND({w_band}), .N_BANDS({n_bands}), "
           f".W_CNT({w_cnt}), .TARGET({target})) dut\n"
           f"    (.clk(clk), .rst_n(rst_n), .meas_valid(1'b1), "
           f".meas_counts(meas), .band(band), .done(done));")
    drive = "      meas = stim[i];"
    compare = """\
      if (band !== exp_b[i] || done !== exp_d[i][0]) begin
        errors = errors + 1;
        if (errors < 5)
          $display("FAIL bsel @%0d: band=%0d exp=%0d done=%b exp=%b",
                   i, band, exp_b[i], done, exp_d[i][0]);
      end"""
    return "tb_bandselect.v", _harness("bandselect", n, decls, dut, drive,
                                       compare)


def tb_fll(window: int, n_target: int, th_eng: int, th_rel: int,
           n: int) -> tuple[str, str]:
    decls = f"""\
  reg [7:0] stim [0:{n - 1}];
  reg [0:0] exp_e [0:{n - 1}];
  reg [20:0] exp_f [0:{n - 1}];
  reg [7:0] cycles;
  wire engaged, fd_valid;
  wire signed [20:0] ferr;
  initial begin
    $readmemh("vectors/fll_cycles.hex", stim);
    $readmemh("vectors/fll_eng.hex", exp_e);
    $readmemh("vectors/fll_ferr.hex", exp_f);
  end"""
    dut = (f"  pllsim_fll #(.W_CNT(20), .WINDOW({window}), "
           f".N_TARGET({n_target}), .TH_ENG({th_eng}), .TH_REL({th_rel})) dut\n"
           f"    (.clk(clk), .rst_n(rst_n), .cycles(cycles), "
           f".engaged(engaged), .ferr(ferr), .fd_valid(fd_valid));")
    drive = "      cycles = stim[i];"
    compare = """\
      if (engaged !== exp_e[i][0] || ferr !== $signed(exp_f[i])) begin
        errors = errors + 1;
        if (errors < 5)
          $display("FAIL fll @%0d: eng=%b exp=%b ferr=%0d exp=%0d",
                   i, engaged, exp_e[i][0], ferr, $signed(exp_f[i]));
      end"""
    return "tb_fll.v", _harness("fll", n, decls, dut, drive, compare)
