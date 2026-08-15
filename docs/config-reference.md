# Configuration reference

**Generated** by `docs/gen_config_reference.py` — edit the configs or
`guiutil.FIELD_INFO`, not this file.  `tests/test_docs_consistency.py`
fails when the two disagree.

Every field below is editable from both GUIs (the forms are built from
the same table) and settable in code:

```python
from pllsim import presets
p = presets.cppll_frac_38p4m_6g()
p.cfg.cp.mismatch_pct = 3.0          # a dotted path below is an attribute path
p.cfg.frac.dtc.inl_sin = (50e-15, 1.0, 0.3)
ar = p.analyze()
```

Values shown are that preset's, as a sense of scale — not defaults.
`_unset_` means the field is `None`, which is a legal value the GUIs
show as an empty box (an unlimited control-voltage range, a noise
figure to be derived rather than declared).

## CPPLL

charge-pump PLL, fractional-N with DTC — `presets.cppll_frac_38p4m_6g()`, 52 fields.

### Top level

| field | unit | value | meaning |
|---|---|---|---|
| `fref` | Hz | `3.84e+07` | reference frequency / 参考频率 |
| `fout` | Hz | `6.0001e+09` | output frequency / 输出频率 |
| `ref_pn_dbchz` | dBc/Hz | `-160` | reference PN floor / 参考噪声底 |
| `ref_pn_fc` | Hz | `20000` | reference flicker corner / 参考闪烁拐角 |
| `div_pn_dbchz` | dBc/Hz | `-160` | divider PN floor / 分频器噪声底 |
| `div_pn_fc` | Hz | `100000` | divider flicker corner / 分频器闪烁拐角 |
| `ref_doubler_duty_err` | — | `0` | reference-doubler duty error / 参考倍频器占空比误差 |
| `retime_jitter_rms_s` | s | `0` | retiming jitter / 重定时抖动 |
| `int_band` | Hz,Hz | `(1000, 1e+08)` | integration band / 积分带 |

### osc — oscillator (`blocks.oscillator.OscConfig`)

| field | unit | value | meaning |
|---|---|---|---|
| `osc.f0` | Hz | `5.95e+09` | free-running frequency / 自由振荡频率 |
| `osc.gain` | Hz/V | Hz/LSB | `8e+07` | tuning gain / 调谐增益 |
| `osc.pn_dbchz` | dBc/Hz | `-120` | PN at spot offset / 相噪@偏移 |
| `osc.pn_foffset` | Hz | `1e+06` | PN spot offset / 相噪偏移点 |
| `osc.pn_f1f3` | Hz | `300000` | 1/f^3 corner / 1/f^3 拐角 |
| `osc.pn_floor_dbchz` | dBc/Hz | `-152` | PN floor / 相噪底 |
| `osc.nl1` | 1/V | `0` | Kvco 1st-order nonlinearity / Kvco 一阶非线性 |
| `osc.nl2` | 1/V^2 | `0` | Kvco 2nd-order nonlinearity / Kvco 二阶非线性 |
| `osc.pushing_hz_v` | Hz/V | `0` | supply pushing / 电源推频 |
| `osc.band_step_hz` | Hz | `0` | band step / 频段间距 |
| `osc.n_bands` | — | `1` | coarse bands / 粗调频段数 |
| `osc.v_min` | V | `_unset_` | control-voltage min (blank = none) / 控制电压下限（空=不限） |
| `osc.v_max` | V | `_unset_` | control-voltage max (blank = none) / 控制电压上限（空=不限） |
| `osc.pull_lock_range_hz` | Hz | `0` | injection lock range f_L / 注入锁定范围 f_L |
| `osc.pull_offset_hz` | Hz | `0` | aggressor offset / 干扰源频偏 |

### cp — charge pump / PFD (`blocks.chargepump.CPConfig`)

| field | unit | value | meaning |
|---|---|---|---|
| `cp.icp` | A | `0.0015` | charge-pump current / CP 电流 |
| `cp.mismatch_pct` | % | `1` | up/down mismatch / 上下电流失配 |
| `cp.leakage_a` | A | `1e-09` | leakage / 泄漏电流 |
| `cp.t_reset` | s | `1.5e-10` | PFD reset time / PFD 复位时间 |
| `cp.noise_a2hz` | A^2/Hz | `_unset_` | CP current noise (blank = default) / CP 电流噪声（空=默认） |
| `cp.flicker_corner` | Hz | `100000` | CP flicker corner / CP 闪烁拐角 |
| `cp.mismatch_slope_pct_v` | %/V | `0` | mismatch vs control voltage / 失配随控制电压斜率 |
| `cp.leakage_slope_a_v` | A/V | `0` | leakage vs control voltage / 泄漏随控制电压斜率 |
| `cp.v_ref` | V | `0` | control voltage where mismatch/leakage are quoted / 失配/泄漏的参考控制电压 |
| `cp.dead_zone_s` | s | `0` | PFD dead zone / PFD 死区 |
| `cp.pfd_mode` | — | `clamp` | PFD out-of-range behaviour (clamp/wrap) / PFD 越界行为（clamp/wrap） |

### filt — loop filter (`blocks.loopfilter.FilterDesign`)

| field | unit | value | meaning |
|---|---|---|---|
| `filt.c1` | F | `4.7e-10` | filter C1 / 滤波 C1 |
| `filt.r2` | Ohm | `15000` | filter R2 / 滤波 R2 |
| `filt.c2` | F | `3.3e-12` | filter C2 / 滤波 C2 |
| `filt.r3` | Ohm | `1500` | filter R3 / 滤波 R3 |
| `filt.c3` | F | `2.2e-12` | filter C3 / 滤波 C3 |

### frac — fractional-N (`arch.cppll.FracConfig`)

| field | unit | value | meaning |
|---|---|---|---|
| `frac.frac` | — | `0.2525` | fractional word / 小数字 |
| `frac.mash_order` | — | `2` | MASH order / MASH 阶数 |
| `frac.bits` | bit | `24` | accumulator bits / 累加器位宽 |

### frac.dtc — digital-to-time converter (`blocks.dtc.DTCConfig`)

| field | unit | value | meaning |
|---|---|---|---|
| `frac.dtc.t_res` | s | `2.5e-13` | resolution LSB / 分辨率 LSB |
| `frac.dtc.n_bits` | bit | `12` | bits / 位数 |
| `frac.dtc.inl_poly` | — | `()` | polynomial INL coefficients / 多项式 INL 系数 |
| `frac.dtc.inl_sin` | s,cyc,rad | `()` | sine INL (amplitude, cycles, phase) / 正弦 INL（幅度, 周期数, 相位） |
| `frac.dtc.jitter_rms_s` | s | `3e-14` | additive jitter / 附加抖动 |
| `frac.dtc.gain_error_residual` | — | `0.01` | analyze gain residual / analyze 残余增益误差 |

### frac.dtc_cal — background DTC gain calibration

| field | unit | value | meaning |
|---|---|---|---|
| `frac.dtc_cal.mu` | — | `5e-06` | LMS mu / LMS 步长 |
| `frac.dtc_cal.gear_shift_n` | cyc | `100000` | gear-shift cycle / 换挡时刻 |
| `frac.dtc_cal.mu_final` | — | `5e-07` | post-gear-shift mu / 换挡后步长 |

## SSPLL

sub-sampling PLL with FLL — `presets.sspll_frac_19p2m_4p806g()`, 50 fields.

### Top level

| field | unit | value | meaning |
|---|---|---|---|
| `fref` | Hz | `1.92e+07` | reference frequency / 参考频率 |
| `fout` | Hz | `4.80481e+09` | output frequency / 输出频率 |
| `ref_pn_dbchz` | dBc/Hz | `-162` | reference PN floor / 参考噪声底 |
| `ref_pn_fc` | Hz | `20000` | reference flicker corner / 参考闪烁拐角 |
| `fll_i` | A | `5e-07` | FLL current / FLL 电流 |
| `fll_window` | cyc | `64` | FLL window / FLL 测量窗 |
| `fll_engage` | Hz | `2e+06` | FLL engage / FLL 接入阈值 |
| `fll_release` | Hz | `400000` | FLL release / FLL 释放阈值 |
| `int_band` | Hz,Hz | `(1000, 1e+08)` | integration band / 积分带 |

### osc — oscillator (`blocks.oscillator.OscConfig`)

| field | unit | value | meaning |
|---|---|---|---|
| `osc.f0` | Hz | `4.755e+09` | free-running frequency / 自由振荡频率 |
| `osc.gain` | Hz/V | Hz/LSB | `6e+07` | tuning gain / 调谐增益 |
| `osc.pn_dbchz` | dBc/Hz | `-122` | PN at spot offset / 相噪@偏移 |
| `osc.pn_foffset` | Hz | `1e+06` | PN spot offset / 相噪偏移点 |
| `osc.pn_f1f3` | Hz | `300000` | 1/f^3 corner / 1/f^3 拐角 |
| `osc.pn_floor_dbchz` | dBc/Hz | `-155` | PN floor / 相噪底 |
| `osc.nl1` | 1/V | `0` | Kvco 1st-order nonlinearity / Kvco 一阶非线性 |
| `osc.nl2` | 1/V^2 | `0` | Kvco 2nd-order nonlinearity / Kvco 二阶非线性 |
| `osc.pushing_hz_v` | Hz/V | `0` | supply pushing / 电源推频 |
| `osc.band_step_hz` | Hz | `0` | band step / 频段间距 |
| `osc.n_bands` | — | `1` | coarse bands / 粗调频段数 |
| `osc.v_min` | V | `_unset_` | control-voltage min (blank = none) / 控制电压下限（空=不限） |
| `osc.v_max` | V | `_unset_` | control-voltage max (blank = none) / 控制电压上限（空=不限） |
| `osc.pull_lock_range_hz` | Hz | `0` | injection lock range f_L / 注入锁定范围 f_L |
| `osc.pull_offset_hz` | Hz | `0` | aggressor offset / 干扰源频偏 |

### sampler — sampling PD (`blocks.sampler.SamplerConfig`)

| field | unit | value | meaning |
|---|---|---|---|
| `sampler.amp_v` | V | `0.4` | sampled amplitude / 采样摆幅 |
| `sampler.c_samp` | F | `6e-14` | sampling cap / 采样电容 |
| `sampler.gm` | S | `0.001` | transconductance / 跨导 |
| `sampler.pulse_width` | s | `1.5e-10` | pulse width / 采样脉宽 |
| `sampler.pedestal_v` | V | `0.001` | pedestal error / 基座误差 |
| `sampler.gm_noise_a2hz` | A^2/Hz | `_unset_` | gm current noise (blank = default) / gm 电流噪声（空=默认） |
| `sampler.temp_k` | K | `290` | temperature (for kT/C noise) / 温度（kT/C 噪声用） |
| `sampler.kick_q_c` | C | `0` | sampling-clock kickback charge / 采样时钟馈通电荷 |
| `sampler.kick_delay_s` | s | `0` | kickback delay from the sampling instant / 馈通相对采样时刻的延迟 |

### filt — loop filter (`blocks.loopfilter.FilterDesign`)

| field | unit | value | meaning |
|---|---|---|---|
| `filt.c1` | F | `6.8e-10` | filter C1 / 滤波 C1 |
| `filt.r2` | Ohm | `20000` | filter R2 / 滤波 R2 |
| `filt.c2` | F | `2.2e-12` | filter C2 / 滤波 C2 |
| `filt.r3` | Ohm | `2000` | filter R3 / 滤波 R3 |
| `filt.c3` | F | `1e-12` | filter C3 / 滤波 C3 |

### frac — fractional-N (`arch.cppll.FracConfig`)

| field | unit | value | meaning |
|---|---|---|---|
| `frac.frac` | — | `0.2503` | fractional word / 小数字 |
| `frac.mash_order` | — | `1` | MASH order / MASH 阶数 |
| `frac.bits` | bit | `24` | accumulator bits / 累加器位宽 |

### frac.dtc — digital-to-time converter (`blocks.dtc.DTCConfig`)

| field | unit | value | meaning |
|---|---|---|---|
| `frac.dtc.t_res` | s | `2.5e-13` | resolution LSB / 分辨率 LSB |
| `frac.dtc.n_bits` | bit | `10` | bits / 位数 |
| `frac.dtc.inl_poly` | — | `()` | polynomial INL coefficients / 多项式 INL 系数 |
| `frac.dtc.inl_sin` | s,cyc,rad | `()` | sine INL (amplitude, cycles, phase) / 正弦 INL（幅度, 周期数, 相位） |
| `frac.dtc.jitter_rms_s` | s | `3e-14` | additive jitter / 附加抖动 |
| `frac.dtc.gain_error_residual` | — | `0.01` | analyze gain residual / analyze 残余增益误差 |

### frac.dtc_cal — background DTC gain calibration

| field | unit | value | meaning |
|---|---|---|---|
| `frac.dtc_cal.mu` | — | `5e-06` | LMS mu / LMS 步长 |
| `frac.dtc_cal.gear_shift_n` | cyc | `60000` | gear-shift cycle / 换挡时刻 |
| `frac.dtc_cal.mu_final` | — | `5e-07` | post-gear-shift mu / 换挡后步长 |

## SPLL

reference-sampling PLL — `presets.spll_frac_52m_6p253g()`, 52 fields.

### Top level

| field | unit | value | meaning |
|---|---|---|---|
| `fref` | Hz | `5.2e+07` | reference frequency / 参考频率 |
| `fout` | Hz | `6.25302e+09` | output frequency / 输出频率 |
| `ref_pn_dbchz` | dBc/Hz | `-160` | reference PN floor / 参考噪声底 |
| `ref_pn_fc` | Hz | `20000` | reference flicker corner / 参考闪烁拐角 |
| `div_pn_dbchz` | dBc/Hz | `-160` | divider PN floor / 分频器噪声底 |
| `div_pn_fc` | Hz | `100000` | divider flicker corner / 分频器闪烁拐角 |
| `fll_i` | A | `1e-06` | FLL current / FLL 电流 |
| `fll_window` | cyc | `64` | FLL window / FLL 测量窗 |
| `fll_engage` | Hz | `3e+06` | FLL engage / FLL 接入阈值 |
| `fll_release` | Hz | `600000` | FLL release / FLL 释放阈值 |
| `int_band` | Hz,Hz | `(1000, 1e+08)` | integration band / 积分带 |

### osc — oscillator (`blocks.oscillator.OscConfig`)

| field | unit | value | meaning |
|---|---|---|---|
| `osc.f0` | Hz | `6.2e+09` | free-running frequency / 自由振荡频率 |
| `osc.gain` | Hz/V | Hz/LSB | `6e+07` | tuning gain / 调谐增益 |
| `osc.pn_dbchz` | dBc/Hz | `-118` | PN at spot offset / 相噪@偏移 |
| `osc.pn_foffset` | Hz | `1e+06` | PN spot offset / 相噪偏移点 |
| `osc.pn_f1f3` | Hz | `300000` | 1/f^3 corner / 1/f^3 拐角 |
| `osc.pn_floor_dbchz` | dBc/Hz | `-152` | PN floor / 相噪底 |
| `osc.nl1` | 1/V | `0` | Kvco 1st-order nonlinearity / Kvco 一阶非线性 |
| `osc.nl2` | 1/V^2 | `0` | Kvco 2nd-order nonlinearity / Kvco 二阶非线性 |
| `osc.pushing_hz_v` | Hz/V | `0` | supply pushing / 电源推频 |
| `osc.band_step_hz` | Hz | `0` | band step / 频段间距 |
| `osc.n_bands` | — | `1` | coarse bands / 粗调频段数 |
| `osc.v_min` | V | `_unset_` | control-voltage min (blank = none) / 控制电压下限（空=不限） |
| `osc.v_max` | V | `_unset_` | control-voltage max (blank = none) / 控制电压上限（空=不限） |
| `osc.pull_lock_range_hz` | Hz | `0` | injection lock range f_L / 注入锁定范围 f_L |
| `osc.pull_offset_hz` | Hz | `0` | aggressor offset / 干扰源频偏 |

### sampler — sampling PD (`blocks.sampler.SamplerConfig`)

| field | unit | value | meaning |
|---|---|---|---|
| `sampler.amp_v` | V | `0.5` | sampled amplitude / 采样摆幅 |
| `sampler.c_samp` | F | `1.5e-13` | sampling cap / 采样电容 |
| `sampler.gm` | S | `0.004` | transconductance / 跨导 |
| `sampler.pulse_width` | s | `6e-10` | pulse width / 采样脉宽 |
| `sampler.pedestal_v` | V | `0.001` | pedestal error / 基座误差 |
| `sampler.gm_noise_a2hz` | A^2/Hz | `_unset_` | gm current noise (blank = default) / gm 电流噪声（空=默认） |
| `sampler.temp_k` | K | `290` | temperature (for kT/C noise) / 温度（kT/C 噪声用） |
| `sampler.kick_q_c` | C | `0` | sampling-clock kickback charge / 采样时钟馈通电荷 |
| `sampler.kick_delay_s` | s | `0` | kickback delay from the sampling instant / 馈通相对采样时刻的延迟 |

### filt — loop filter (`blocks.loopfilter.FilterDesign`)

| field | unit | value | meaning |
|---|---|---|---|
| `filt.c1` | F | `4.7e-10` | filter C1 / 滤波 C1 |
| `filt.r2` | Ohm | `12000` | filter R2 / 滤波 R2 |
| `filt.c2` | F | `2.2e-12` | filter C2 / 滤波 C2 |
| `filt.r3` | Ohm | `1500` | filter R3 / 滤波 R3 |
| `filt.c3` | F | `1e-12` | filter C3 / 滤波 C3 |

### frac — fractional-N (`arch.cppll.FracConfig`)

| field | unit | value | meaning |
|---|---|---|---|
| `frac.frac` | — | `0.2503` | fractional word / 小数字 |
| `frac.mash_order` | — | `1` | MASH order / MASH 阶数 |
| `frac.bits` | bit | `24` | accumulator bits / 累加器位宽 |

### frac.dtc — digital-to-time converter (`blocks.dtc.DTCConfig`)

| field | unit | value | meaning |
|---|---|---|---|
| `frac.dtc.t_res` | s | `2.5e-13` | resolution LSB / 分辨率 LSB |
| `frac.dtc.n_bits` | bit | `10` | bits / 位数 |
| `frac.dtc.inl_poly` | — | `()` | polynomial INL coefficients / 多项式 INL 系数 |
| `frac.dtc.inl_sin` | s,cyc,rad | `()` | sine INL (amplitude, cycles, phase) / 正弦 INL（幅度, 周期数, 相位） |
| `frac.dtc.jitter_rms_s` | s | `3e-14` | additive jitter / 附加抖动 |
| `frac.dtc.gain_error_residual` | — | `0.01` | analyze gain residual / analyze 残余增益误差 |

### frac.dtc_cal — background DTC gain calibration

| field | unit | value | meaning |
|---|---|---|---|
| `frac.dtc_cal.mu` | — | `5e-06` | LMS mu / LMS 步长 |
| `frac.dtc_cal.gear_shift_n` | cyc | `60000` | gear-shift cycle / 换挡时刻 |
| `frac.dtc_cal.mu_final` | — | `5e-07` | post-gear-shift mu / 换挡后步长 |

## ADPLL (TDC)

all-digital PLL, counter + TDC — `presets.adpll_100m_10g()`, 33 fields.

### Top level

| field | unit | value | meaning |
|---|---|---|---|
| `fref` | Hz | `1e+08` | reference frequency / 参考频率 |
| `fout` | Hz | `1.00503e+10` | output frequency / 输出频率 |
| `mode` | — | `tdc` | mode / 工作模式 |
| `dco_dither_order` | — | `1` | DCO dither order / DCO 抖动阶数 |
| `ref_pn_dbchz` | dBc/Hz | `-158` | reference PN floor / 参考噪声底 |
| `ref_pn_fc` | Hz | `20000` | reference flicker corner / 参考闪烁拐角 |
| `kdco_est_error` | — | `0` | KDCO estimate error / KDCO 估计误差 |
| `bb_jitter_rms_s` | s | `1e-13` | BBPD input jitter / BBPD 输入抖动 |
| `bb_meta_window_s` | s | `0` | BBPD metastability window / BBPD 亚稳态窗口 |
| `int_band` | Hz,Hz | `(1000, 1e+08)` | integration band / 积分带 |

### osc — oscillator (`blocks.oscillator.OscConfig`)

| field | unit | value | meaning |
|---|---|---|---|
| `osc.f0` | Hz | `1e+10` | free-running frequency / 自由振荡频率 |
| `osc.gain` | Hz/V | Hz/LSB | `20000` | tuning gain / 调谐增益 |
| `osc.pn_dbchz` | dBc/Hz | `-112` | PN at spot offset / 相噪@偏移 |
| `osc.pn_foffset` | Hz | `1e+06` | PN spot offset / 相噪偏移点 |
| `osc.pn_f1f3` | Hz | `400000` | 1/f^3 corner / 1/f^3 拐角 |
| `osc.pn_floor_dbchz` | dBc/Hz | `-150` | PN floor / 相噪底 |
| `osc.nl1` | 1/V | `0` | Kvco 1st-order nonlinearity / Kvco 一阶非线性 |
| `osc.nl2` | 1/V^2 | `0` | Kvco 2nd-order nonlinearity / Kvco 二阶非线性 |
| `osc.pushing_hz_v` | Hz/V | `0` | supply pushing / 电源推频 |
| `osc.band_step_hz` | Hz | `0` | band step / 频段间距 |
| `osc.n_bands` | — | `1` | coarse bands / 粗调频段数 |
| `osc.v_min` | V | `_unset_` | control-voltage min (blank = none) / 控制电压下限（空=不限） |
| `osc.v_max` | V | `_unset_` | control-voltage max (blank = none) / 控制电压上限（空=不限） |
| `osc.pull_lock_range_hz` | Hz | `0` | injection lock range f_L / 注入锁定范围 f_L |
| `osc.pull_offset_hz` | Hz | `0` | aggressor offset / 干扰源频偏 |

### dlf — digital loop filter (`arch.adpll.DLFConfig`)

| field | unit | value | meaning |
|---|---|---|---|
| `dlf.alpha` | — | `0.0625` | DLF proportional / DLF 比例 |
| `dlf.rho` | — | `0.000488281` | DLF integral / DLF 积分 |
| `dlf.iir_lambdas` | — | `(0.5)` | IIR lambdas / IIR 系数 |

### tdc — time-to-digital converter (`blocks.tdc.TDCConfig`)

| field | unit | value | meaning |
|---|---|---|---|
| `tdc.t_res` | s | `5e-13` | resolution LSB / 分辨率 LSB |
| `tdc.n_bits` | bit | `8` | bits / 位数 |
| `tdc.inl_sin` | s,cyc,rad | `()` | sine INL (amplitude, cycles, phase) / 正弦 INL（幅度, 周期数, 相位） |
| `tdc.jitter_rms_s` | s | `0` | additive jitter / 附加抖动 |
| `tdc.gain_error` | — | `0` | TDC gain error (unknown to the loop) / TDC 增益误差（环路不知情） |

## ADPLL (BBPD)

all-digital PLL, DTC + bang-bang — `presets.adpll_bb_100m_10g()`, 40 fields.

### Top level

| field | unit | value | meaning |
|---|---|---|---|
| `fref` | Hz | `1e+08` | reference frequency / 参考频率 |
| `fout` | Hz | `1.00503e+10` | output frequency / 输出频率 |
| `mode` | — | `dtc_bbpd` | mode / 工作模式 |
| `dco_dither_order` | — | `1` | DCO dither order / DCO 抖动阶数 |
| `ref_pn_dbchz` | dBc/Hz | `-158` | reference PN floor / 参考噪声底 |
| `ref_pn_fc` | Hz | `20000` | reference flicker corner / 参考闪烁拐角 |
| `kdco_est_error` | — | `0` | KDCO estimate error / KDCO 估计误差 |
| `bb_jitter_rms_s` | s | `2e-13` | BBPD input jitter / BBPD 输入抖动 |
| `bb_meta_window_s` | s | `0` | BBPD metastability window / BBPD 亚稳态窗口 |
| `int_band` | Hz,Hz | `(1000, 1e+08)` | integration band / 积分带 |

### osc — oscillator (`blocks.oscillator.OscConfig`)

| field | unit | value | meaning |
|---|---|---|---|
| `osc.f0` | Hz | `1e+10` | free-running frequency / 自由振荡频率 |
| `osc.gain` | Hz/V | Hz/LSB | `20000` | tuning gain / 调谐增益 |
| `osc.pn_dbchz` | dBc/Hz | `-112` | PN at spot offset / 相噪@偏移 |
| `osc.pn_foffset` | Hz | `1e+06` | PN spot offset / 相噪偏移点 |
| `osc.pn_f1f3` | Hz | `400000` | 1/f^3 corner / 1/f^3 拐角 |
| `osc.pn_floor_dbchz` | dBc/Hz | `-150` | PN floor / 相噪底 |
| `osc.nl1` | 1/V | `0` | Kvco 1st-order nonlinearity / Kvco 一阶非线性 |
| `osc.nl2` | 1/V^2 | `0` | Kvco 2nd-order nonlinearity / Kvco 二阶非线性 |
| `osc.pushing_hz_v` | Hz/V | `0` | supply pushing / 电源推频 |
| `osc.band_step_hz` | Hz | `0` | band step / 频段间距 |
| `osc.n_bands` | — | `1` | coarse bands / 粗调频段数 |
| `osc.v_min` | V | `_unset_` | control-voltage min (blank = none) / 控制电压下限（空=不限） |
| `osc.v_max` | V | `_unset_` | control-voltage max (blank = none) / 控制电压上限（空=不限） |
| `osc.pull_lock_range_hz` | Hz | `0` | injection lock range f_L / 注入锁定范围 f_L |
| `osc.pull_offset_hz` | Hz | `0` | aggressor offset / 干扰源频偏 |

### dlf — digital loop filter (`arch.adpll.DLFConfig`)

| field | unit | value | meaning |
|---|---|---|---|
| `dlf.alpha` | — | `2` | DLF proportional / DLF 比例 |
| `dlf.rho` | — | `0.015625` | DLF integral / DLF 积分 |
| `dlf.iir_lambdas` | — | `()` | IIR lambdas / IIR 系数 |

### frac — fractional-N (`arch.cppll.FracConfig`)

| field | unit | value | meaning |
|---|---|---|---|
| `frac.frac` | — | `0.503` | fractional word / 小数字 |
| `frac.mash_order` | — | `2` | MASH order / MASH 阶数 |
| `frac.bits` | bit | `24` | accumulator bits / 累加器位宽 |

### frac.dtc — digital-to-time converter (`blocks.dtc.DTCConfig`)

| field | unit | value | meaning |
|---|---|---|---|
| `frac.dtc.t_res` | s | `2.5e-13` | resolution LSB / 分辨率 LSB |
| `frac.dtc.n_bits` | bit | `12` | bits / 位数 |
| `frac.dtc.inl_poly` | — | `()` | polynomial INL coefficients / 多项式 INL 系数 |
| `frac.dtc.inl_sin` | s,cyc,rad | `()` | sine INL (amplitude, cycles, phase) / 正弦 INL（幅度, 周期数, 相位） |
| `frac.dtc.jitter_rms_s` | s | `5e-14` | additive jitter / 附加抖动 |
| `frac.dtc.gain_error_residual` | — | `0.01` | analyze gain residual / analyze 残余增益误差 |

### frac.dtc_cal — background DTC gain calibration

| field | unit | value | meaning |
|---|---|---|---|
| `frac.dtc_cal.mu` | — | `1e-05` | LMS mu / LMS 步长 |
| `frac.dtc_cal.gear_shift_n` | cyc | `100000` | gear-shift cycle / 换挡时刻 |
| `frac.dtc_cal.mu_final` | — | `1e-06` | post-gear-shift mu / 换挡后步长 |

## ILCM

injection-locked clock multiplier with FTL — `presets.ilcm_250m_12g()`, 28 fields.

### Top level

| field | unit | value | meaning |
|---|---|---|---|
| `fref` | Hz | `2.5e+08` | reference frequency / 参考频率 |
| `fout` | Hz | `1.2e+10` | output frequency / 输出频率 |
| `beta` | — | `0.6` | injection strength / 注入强度 |
| `q_tank` | — | `8` | tank Q / 谐振腔 Q |
| `i_ratio` | — | `0.15` | injection current ratio / 注入电流比 |
| `inj_jitter_rms_s` | s | `1.5e-14` | injection edge jitter / 注入沿抖动 |
| `ref_pn_dbchz` | dBc/Hz | `-155` | reference PN floor / 参考噪声底 |
| `ref_pn_fc` | Hz | `20000` | reference flicker corner / 参考闪烁拐角 |
| `ftl_f_lsb` | Hz | `20000` | FTL frequency LSB / FTL 频率 LSB |
| `ftl_mu` | — | `1` | FTL step size / FTL 步长 |
| `ftl_det_offset_s` | s | `0` | FTL detector offset / FTL 鉴频器失调 |
| `timing_cal_step_s` | s | `5e-14` | injection timing cal step / 注入时序校准步长 |
| `int_band` | Hz,Hz | `(1000, 1e+08)` | integration band / 积分带 |

### osc — oscillator (`blocks.oscillator.OscConfig`)

| field | unit | value | meaning |
|---|---|---|---|
| `osc.f0` | Hz | `1.2e+10` | free-running frequency / 自由振荡频率 |
| `osc.gain` | Hz/V | Hz/LSB | `1` | tuning gain / 调谐增益 |
| `osc.pn_dbchz` | dBc/Hz | `-105` | PN at spot offset / 相噪@偏移 |
| `osc.pn_foffset` | Hz | `1e+06` | PN spot offset / 相噪偏移点 |
| `osc.pn_f1f3` | Hz | `500000` | 1/f^3 corner / 1/f^3 拐角 |
| `osc.pn_floor_dbchz` | dBc/Hz | `-145` | PN floor / 相噪底 |
| `osc.nl1` | 1/V | `0` | Kvco 1st-order nonlinearity / Kvco 一阶非线性 |
| `osc.nl2` | 1/V^2 | `0` | Kvco 2nd-order nonlinearity / Kvco 二阶非线性 |
| `osc.pushing_hz_v` | Hz/V | `0` | supply pushing / 电源推频 |
| `osc.band_step_hz` | Hz | `0` | band step / 频段间距 |
| `osc.n_bands` | — | `1` | coarse bands / 粗调频段数 |
| `osc.v_min` | V | `_unset_` | control-voltage min (blank = none) / 控制电压下限（空=不限） |
| `osc.v_max` | V | `_unset_` | control-voltage max (blank = none) / 控制电压上限（空=不限） |
| `osc.pull_lock_range_hz` | Hz | `0` | injection lock range f_L / 注入锁定范围 f_L |
| `osc.pull_offset_hz` | Hz | `0` | aggressor offset / 干扰源频偏 |

## MDLL

multiplying DLL — `presets.mdll_150m_2p4g()`, 22 fields.

### Top level

| field | unit | value | meaning |
|---|---|---|---|
| `fref` | Hz | `1.5e+08` | reference frequency / 参考频率 |
| `fout` | Hz | `2.4e+09` | output frequency / 输出频率 |
| `mux_jitter_rms_s` | s | `4e-14` | mux jitter / MUX 抖动 |
| `ref_pn_dbchz` | dBc/Hz | `-160` | reference PN floor / 参考噪声底 |
| `ref_pn_fc` | Hz | `20000` | reference flicker corner / 参考闪烁拐角 |
| `tune_ki_lsb` | LSB | `0.02` | MDLL tuning integral gain / MDLL 调谐积分增益 |
| `int_band` | Hz,Hz | `(1000, 1e+08)` | integration band / 积分带 |

### osc — oscillator (`blocks.oscillator.OscConfig`)

| field | unit | value | meaning |
|---|---|---|---|
| `osc.f0` | Hz | `2.4e+09` | free-running frequency / 自由振荡频率 |
| `osc.gain` | Hz/V | Hz/LSB | `100000` | tuning gain / 调谐增益 |
| `osc.pn_dbchz` | dBc/Hz | `-95` | PN at spot offset / 相噪@偏移 |
| `osc.pn_foffset` | Hz | `1e+06` | PN spot offset / 相噪偏移点 |
| `osc.pn_f1f3` | Hz | `800000` | 1/f^3 corner / 1/f^3 拐角 |
| `osc.pn_floor_dbchz` | dBc/Hz | `-140` | PN floor / 相噪底 |
| `osc.nl1` | 1/V | `0` | Kvco 1st-order nonlinearity / Kvco 一阶非线性 |
| `osc.nl2` | 1/V^2 | `0` | Kvco 2nd-order nonlinearity / Kvco 二阶非线性 |
| `osc.pushing_hz_v` | Hz/V | `0` | supply pushing / 电源推频 |
| `osc.band_step_hz` | Hz | `0` | band step / 频段间距 |
| `osc.n_bands` | — | `1` | coarse bands / 粗调频段数 |
| `osc.v_min` | V | `_unset_` | control-voltage min (blank = none) / 控制电压下限（空=不限） |
| `osc.v_max` | V | `_unset_` | control-voltage max (blank = none) / 控制电压上限（空=不限） |
| `osc.pull_lock_range_hz` | Hz | `0` | injection lock range f_L / 注入锁定范围 f_L |
| `osc.pull_offset_hz` | Hz | `0` | aggressor offset / 干扰源频偏 |
