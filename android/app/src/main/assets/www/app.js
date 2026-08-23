/* Workbench UI over the pllsim.appbridge JSON RPC.
 *
 * The form is generated from the bridge's field list -- the same
 * guiutil.FIELD_INFO that drives the Streamlit form, the Qt form and the
 * config reference -- so a field added to the library appears here with no
 * change to this file.  Only values the user actually edited are sent back
 * (the web GUI's changed-only semantics), so a preset stays a preset.
 */
"use strict";

/* ---------------------------------------------------------- host RPC */
const pending = {};
let seq = 0;

function call(method, args) {
  return new Promise((resolve, reject) => {
    const id = String(++seq);
    pending[id] = { resolve, reject };
    window.host.call(id, method, JSON.stringify(args || {}));
  });
}

window.onHostReply = (id, replyStr) => {
  const p = pending[id];
  delete pending[id];
  if (!p) return;
  let r;
  try { r = JSON.parse(replyStr); }
  catch (e) { p.reject(new Error("bad reply: " + e)); return; }
  if (r.ok) p.resolve(r.result);
  else p.reject(new Error(r.error));
};

/* ---------------------------------------------------------- language */
let lang = "zh";
function applyLang() {
  document.querySelectorAll("[data-zh]").forEach(el => {
    el.textContent = el.dataset[lang];
  });
  document.getElementById("lang").textContent = lang === "zh" ? "EN" : "中文";
  document.documentElement.lang = lang;
}

/* ---------------------------------------------------------- helpers */
const $ = id => document.getElementById(id);
const esc = s => String(s).replace(/[&<>"]/g,
  c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

function busy(textZh, textEn, on) {
  $("busy").hidden = !on;
  $("busy-text").textContent = lang === "zh" ? textZh : textEn;
  $("run-analyze").disabled = on;
  $("run-simulate").disabled = on;
}

function metricsHtml(items) {
  return '<div class="metrics">' + items.map(([k, v]) =>
    `<div class="metric"><b>${esc(v)}</b><span>${esc(k)}</span></div>`
  ).join("") + "</div>";
}

function notesHtml(notes) {
  return (notes || []).map(n => `<p class="note">note: ${esc(n)}</p>`).join("");
}

function pngHtml(b64) {
  return `<img class="plot" src="data:image/png;base64,${b64}">`;
}

function errHtml(e) {
  return `<p class="error">${esc(e.message || e)}</p>`;
}

/* ---------------------------------------------------------- form */
let baseline = {};          // path -> preset value string
let fieldMeta = null;       // last fields() reply
let candidate = "";         // non-empty: editing a selector candidate

function wbArgs(extra) {
  // every workbench call goes through here so candidate mode cannot be
  // half-applied: either all calls carry the candidate or none do
  const a = Object.assign({ overrides: overrides() }, extra || {});
  if (candidate) a.candidate = candidate;
  else a.preset = $("preset").value;
  return a;
}

function overrides() {
  const out = {};
  document.querySelectorAll("#form input[data-path]").forEach(inp => {
    if (inp.value.trim() !== baseline[inp.dataset.path].trim()) {
      out[inp.dataset.path] = inp.value;
    }
  });
  return out;
}

function markEdited() {
  const paths = Object.keys(overrides());
  document.querySelectorAll("#form input[data-path]").forEach(inp => {
    inp.classList.toggle("edited", paths.includes(inp.dataset.path));
  });
  const el = $("edited");
  el.hidden = paths.length === 0;
  el.textContent = (lang === "zh" ? "已修改: " : "edited: ") + paths.join(", ");
}

async function loadPreset(name) {
  busy("载入 preset…", "loading preset…", true);
  try {
    fieldMeta = await call("fields",
      candidate ? { candidate } : { preset: name });
    baseline = {};
    const groups = {};
    fieldMeta.fields.forEach(f => {
      (groups[f.group] = groups[f.group] || []).push(f);
      baseline[f.path] = f.value;
    });
    $("preset-info").textContent =
      `${fieldMeta.arch}: fref = ${fieldMeta.fref_mhz} MHz -> ` +
      `fout = ${(+fieldMeta.fout_ghz).toPrecision(6)} GHz`;
    $("form").innerHTML = Object.entries(groups).map(([g, fs], i) => {
      const gl = fieldMeta.group_labels[g] || { zh: g, en: g };
      const inner = fs.map(f => {
        const label = (lang === "zh" ? f.label_zh : f.label_en) +
                      (f.unit ? ` [${f.unit}]` : "");
        return `<label>${esc(label)}<input data-path="${esc(f.path)}"
                value="${esc(f.value)}" inputmode="text"
                autocapitalize="off" autocorrect="off"></label>`;
      }).join("");
      return `<details ${i === 0 ? "open" : ""}><summary>${esc(
        lang === "zh" ? gl.zh : gl.en)}</summary>
        <div class="field-grid">${inner}</div></details>`;
    }).join("");
    document.querySelectorAll("#form input[data-path]").forEach(inp =>
      inp.addEventListener("input", markEdited));
    markEdited();
    $("fine-row").hidden = !fieldMeta.supports_fine;
    $("analyze-out").innerHTML = "";
    $("simulate-out").innerHTML = "";
  } catch (e) {
    $("form").innerHTML = errHtml(e);
  } finally {
    busy("", "", false);
  }
}

/* ---------------------------------------------------------- actions */
async function runAnalyze() {
  busy("analyze…", "analyze…", true);
  const out = $("analyze-out");
  try {
    const r = await call("analyze", wbArgs());
    let html = metricsHtml([
      ["jitter", r.jitter_fs === null ? "-" : r.jitter_fs.toFixed(1) + " fs"],
      ["IPN", r.ipn_dbc === null ? "-" : r.ipn_dbc.toFixed(1) + " dBc"],
      ["UGB", r.f_ugb_hz === null ? "-" : (r.f_ugb_hz / 1e3).toFixed(0) + " kHz"],
      ["PM", r.pm_deg === null ? "-" : r.pm_deg.toFixed(0) + " deg"],
    ]);
    html += notesHtml(r.notes);
    if (Object.keys(r.spurs_analytic).length) {
      html += `<pre class="spurs">${esc(JSON.stringify(r.spurs_analytic, null, 1))}</pre>`;
    }
    html += pngHtml(r.png);
    out.innerHTML = html;
  } catch (e) {
    out.innerHTML = errHtml(e);
  } finally {
    busy("", "", false);
  }
}

async function updateFineNote() {
  if (!fieldMeta || !fieldMeta.supports_fine) return;
  const m = +$("m-os").value;
  if (m <= 1) { $("fine-note").textContent = ""; return; }
  try {
    const r = await call("fine_info", wbArgs({
      n_cycles: +$("n-cycles").value, m,
    }));
    let t = `record ~${r.record_mb.toFixed(0)} MB`;
    if (r.note) t += " — " + r.note;
    $("fine-note").textContent = t;
  } catch (e) {
    $("fine-note").textContent = String(e.message || e);
  }
}

async function runSimulate() {
  const m = +$("m-os").value;
  const nCycles = +$("n-cycles").value;
  // same guard as the web GUI, tightened for a phone: a fine record in the
  // hundreds of MB will OOM-kill the process, not just feel slow
  if (m > 1 && nCycles * m * 8 / 1e6 > 500) {
    $("simulate-out").innerHTML = errHtml(new Error(lang === "zh"
      ? "细采样记录超过 500 MB，请先降低周期数或 M"
      : "the fine record exceeds 500 MB; lower the cycle count or M first"));
    return;
  }
  busy("时域仿真中…（手机上可能需要数分钟）",
       "simulating… (this can take minutes on a phone)", true);
  const out = $("simulate-out");
  try {
    const r = await call("simulate", wbArgs({
      n_cycles: nCycles, seed: +$("seed").value,
      noise: $("noise").checked, calibration: $("cal").checked,
      f_start_offset_mhz: +$("f-off").value,
      dtc_gain_init_error: +$("dtc-err").value,
      fine_oversample: m,
    }));
    let html = metricsHtml([
      ["jitter", r.jitter_fs === null ? "-" : r.jitter_fs.toFixed(1) + " fs"],
      ["lock", r.lock_time_us === null ? "-" : r.lock_time_us.toFixed(1) + " us"],
      ["f_end", r.f_end_ghz.toFixed(6) + " GHz"],
    ]);
    html += notesHtml(r.notes);
    r.pngs.forEach(p => { html += `<p class="muted">${esc(p.title)}</p>` + pngHtml(p.png); });
    if (r.spurs_fft.length) {
      const rows = r.spurs_fft.map(s =>
        `${(s.offset_hz / 1e3).toFixed(1)} kHz: ` +
        (s.dbc === null ? "below noise" : s.dbc.toFixed(1) + " dBc"));
      html += `<pre class="spurs">${esc(rows.join("\n"))}</pre>`;
    }
    out.innerHTML = html;
  } catch (e) {
    out.innerHTML = errHtml(e);
  } finally {
    busy("", "", false);
  }
}

/* ---------------------------------------------------------- tabs */
function showTab(name) {
  document.querySelectorAll("#tabs button").forEach(b =>
    b.classList.toggle("active", b.dataset.tab === name));
  document.querySelectorAll(".tab").forEach(t =>
    t.hidden = t.id !== "tab-" + name);
}
document.querySelectorAll("#tabs button").forEach(b =>
  b.addEventListener("click", () => showTab(b.dataset.tab)));

function tableHtml(rows) {
  if (!rows.length) return "";
  const cols = Object.keys(rows[0]);
  return '<table class="rows"><tr>' +
    cols.map(c => `<th>${esc(c)}</th>`).join("") + "</tr>" +
    rows.map(r => "<tr>" + cols.map(c => `<td>${esc(r[c])}</td>`).join("") +
             "</tr>").join("") + "</table>";
}

/* ---------------------------------------------------------- spurs tab */
function spurArgs() {
  return {
    preset: $("sp-preset").value,
    inl_amp_s: Number($("sp-inl").value),
    inl_cycles: Number($("sp-cyc").value),
    gain_residual: Number($("sp-gain").value),
  };
}

async function runInto(outId, fn, busyZh, busyEn) {
  busy(busyZh, busyEn, true);
  const out = $(outId);
  try { out.innerHTML = await fn(); }
  catch (e) { out.innerHTML = errHtml(e); }
  finally { busy("", "", false); }
}

$("sp-predict").addEventListener("click", () => runInto(
  "sp-predict-out", async () => {
    const r = await call("spur_predict", spurArgs());
    return tableHtml(r.rows.map(x =>
      ({ offset: x.offset, "spur [dBc]": x.dbc }))) + notesHtml(r.notes);
  }, "analyze…", "analyze…"));

$("sp-measure").addEventListener("click", () => runInto(
  "sp-measure-out", async () => {
    const r = await call("spur_spectrum",
      { ...spurArgs(), n_cycles: +$("sp-ncyc").value });
    return notesHtml(r.notes) + pngHtml(r.png);
  }, "时域仿真中…", "simulating…"));

$("sp-ref").addEventListener("click", () => runInto(
  "sp-ref-out", async () => {
    const r = await call("ref_spur", {
      preset: $("sp-preset").value,
      m: +$("sp-m").value, n_cycles: +$("sp-refcyc").value,
    });
    return tableHtml(r.rows) +
      r.notes.map(n => `<p class="muted">${esc(n)}</p>`).join("");
  }, "时域仿真中…", "simulating…"));

$("sp-sweep").addEventListener("click", () => runInto(
  "sp-sweep-out", async () => {
    const r = await call("spur_sweep", spurArgs());
    return pngHtml(r.png);
  }, "扫描 8 个通道中…", "sweeping 8 channels…"));

/* ---------------------------------------------------------- hop tab */
async function updateFllBanner() {
  const el = $("hop-fll");
  el.innerHTML = "";
  try {
    const st = await call("hop_check", { preset: $("hop-preset").value });
    if (st === null) return;
    const txt = `FLL: slew ${st.slew_khz_per_window.toFixed(0)} kHz/window, ` +
      `i_fll_max ${st.i_fll_max_ua.toFixed(2)} uA, ` +
      `margin ${st.margin.toFixed(2)}x` +
      (st.ok ? "" : (lang === "zh" ? " —— 超界：FLL 将极限环振荡、永不交接！"
                                   : " — OVER the bound: limit cycle, never hands off!"));
    el.innerHTML = `<p class="${st.ok ? "banner-ok" : "banner-bad"}">${esc(txt)}</p>`;
  } catch (e) {
    el.innerHTML = errHtml(e);
  }
}

$("hop-preset").addEventListener("change", updateFllBanner);

$("hop-run").addEventListener("click", () => runInto(
  "hop-out", async () => {
    const r = await call("hop", {
      preset: $("hop-preset").value, hop_hz: Number($("hop-hz").value),
      n_cycles: +$("hop-ncyc").value, seed: +$("hop-seed").value,
    });
    const ns = lang === "zh" ? "未建立" : "not settled";
    return metricsHtml([
      ["t_freq", r.t_freq_us === null ? ns : r.t_freq_us.toFixed(1) + " us"],
      ["t_phase", r.t_phase_us === null ? ns : r.t_phase_us.toFixed(1) + " us"],
      ["FLL", r.fll_us === null ? "-" : r.fll_us.toFixed(1) + " us"],
      ["jitter", r.jitter_fs === null ? "-" : r.jitter_fs.toFixed(0) + " fs"],
    ]) + pngHtml(r.png);
  }, "跳频仿真中…", "hopping…"));

$("hop-stats").addEventListener("click", () => runInto(
  "hop-stats-out", async () => {
    const r = await call("hop_stats", {
      preset: $("hop-preset").value, hop_hz: Number($("hop-hz").value),
      n_cycles: +$("hop-ncyc").value, n_seeds: +$("hop-seeds").value,
    });
    return metricsHtml([
      ["p50", r.p50_us === null ? "-" : r.p50_us.toFixed(0) + " us"],
      ["p95", r.p95_us === null ? "-" : r.p95_us.toFixed(0) + " us"],
      [lang === "zh" ? "最差" : "worst",
       r.worst_us === null ? "-" : r.worst_us.toFixed(0) + " us"],
      [lang === "zh" ? "未建立" : "failed", r.fail_pct.toFixed(0) + " %"],
    ]) + pngHtml(r.png);
  }, "多种子跳频中…", "hopping (all seeds)…"));

/* ------------------------------------------------- selector tab */
async function enterCandidate(arch) {
  candidate = arch;
  $("wb-candidate").hidden = false;
  $("wb-candidate-label").textContent = (lang === "zh"
    ? `正在编辑来自选型器的候选：${arch}（不是 preset）`
    : `editing a candidate handed over by the selector: ${arch} (not a preset)`);
  $("preset").disabled = true;
  showTab("workbench");
  await loadPreset("");
}

$("wb-back").addEventListener("click", async () => {
  candidate = "";
  $("wb-candidate").hidden = true;
  $("preset").disabled = false;
  await loadPreset($("preset").value);
});

$("sel-run").addEventListener("click", () => runInto(
  "sel-out", async () => {
    const r = await call("select", {
      fref_hz: Number($("sel-fref").value),
      fout_hz: Number($("sel-fout").value),
      jitter_fs_max: Number($("sel-jmax").value),
      band_lo_hz: Number($("sel-blo").value),
      band_hi_hz: Number($("sel-bhi").value),
      modulation: $("sel-mod").checked,
    });
    let html = tableHtml(r.rows.map(x => ({
      arch: x.arch,
      "jitter [fs]": x.jitter_fs === null ? "-" : x.jitter_fs.toFixed(1),
      verdict: x.verdict,
      "UGB [kHz]": x.f_ugb_khz === null ? "-" : x.f_ugb_khz.toFixed(0),
      notes: x.notes,
    })));
    if (r.best !== null) {
      html += `<p class="banner-ok">${esc((lang === "zh"
        ? `推荐: ${r.best}（${r.best_jitter_fs.toFixed(0)} fs，目标 ${r.target_fs} fs）`
        : `recommendation: ${r.best} (${r.best_jitter_fs.toFixed(0)} fs vs target ${r.target_fs} fs)`))}</p>`;
      html += `<p class="muted">${lang === "zh" ? "在工作台中打开：" : "open in the workbench:"}</p>`;
      html += r.handoff.map(a =>
        `<button class="handoff" data-arch="${esc(a)}">${esc(a)}</button>`).join(" ");
    } else {
      html += `<p class="note">${lang === "zh"
        ? "没有架构达标：放宽目标、改善振荡器档或提高 fref。"
        : "no architecture meets the target — relax it, improve the oscillator class, or raise fref."}</p>`;
    }
    return html;
  }, "七架构综合中…", "synthesizing 7 architectures…").then(() => {
    document.querySelectorAll("#sel-out button.handoff").forEach(b =>
      b.addEventListener("click", () => enterCandidate(b.dataset.arch)));
  }));

/* ------------------------------------------------- synthesis tab */
function filtHtml(r) {
  return tableHtml([{ c1: r.c1_f.toPrecision(4) + " F",
                      r2: r.r2_ohm.toPrecision(4) + " Ohm",
                      c2: r.c2_f.toPrecision(4) + " F",
                      r3: r.r3_ohm.toPrecision(4) + " Ohm",
                      c3: r.c3_f.toPrecision(4) + " F" }]);
}

$("sy-cp-run").addEventListener("click", () => runInto(
  "sy-cp-out", async () => filtHtml(await call("synth_cp", {
    icp_a: Number($("sy-cp-icp").value), n: Number($("sy-cp-n").value),
    kvco_hz_v: Number($("sy-cp-kv").value), ugb_hz: Number($("sy-cp-ugb").value),
    pm_deg: Number($("sy-cp-pm").value), fref_hz: Number($("sy-cp-fr").value),
  })), "综合中…", "synthesizing…"));

$("sy-ss-run").addEventListener("click", () => runInto(
  "sy-ss-out", async () => filtHtml(await call("synth_sspll", {
    amp_v: Number($("sy-ss-amp").value), gm_s: Number($("sy-ss-gm").value),
    pulse_s: Number($("sy-ss-pw").value), kvco_hz_v: Number($("sy-ss-kv").value),
    ugb_hz: Number($("sy-ss-ugb").value), pm_deg: Number($("sy-ss-pm").value),
    fref_hz: Number($("sy-ss-fr").value),
  })), "综合中…", "synthesizing…"));

$("sy-sp-run").addEventListener("click", () => runInto(
  "sy-sp-out", async () => filtHtml(await call("synth_spll", {
    amp_v: Number($("sy-sp-amp").value), gm_s: Number($("sy-sp-gm").value),
    pulse_s: Number($("sy-sp-pw").value), n: Number($("sy-sp-n").value),
    kvco_hz_v: Number($("sy-sp-kv").value), ugb_hz: Number($("sy-sp-ugb").value),
    pm_deg: Number($("sy-sp-pm").value), fref_hz: Number($("sy-sp-fr").value),
  })), "综合中…", "synthesizing…"));

$("sy-d-run").addEventListener("click", () => runInto(
  "sy-d-out", async () => {
    const r = await call("synth_dlf", {
      fref_hz: Number($("sy-d-fr").value), ugb_hz: Number($("sy-d-ugb").value),
      pm_deg: Number($("sy-d-pm").value),
    });
    return tableHtml([{ alpha: r.alpha.toPrecision(6),
                        rho: r.rho.toPrecision(6) }]);
  }, "综合中…", "synthesizing…"));

$("sw-run").addEventListener("click", () => runInto(
  "sw-out", async () => {
    const pmTxt = $("sw-pm").value.trim();
    const args = {
      preset: $("sw-preset").value, lo_hz: Number($("sw-lo").value),
      hi_hz: Number($("sw-hi").value), n_points: +$("sw-n").value,
    };
    if (pmTxt !== "") args.pm_deg = Number(pmTxt);
    const r = await call("bw_sweep", args);
    let html = "";
    if (r.jitter_fs.length < r.n_requested) {
      html += `<p class="note">${lang === "zh"
        ? `${r.n_requested} 个带宽点中 ${r.jitter_fs.length} 个可综合，其余跳过`
        : `${r.jitter_fs.length} of ${r.n_requested} UGB targets were synthesizable; the rest were skipped`}</p>`;
    }
    return html + pngHtml(r.png);
  }, "带宽扫描中…", "sweeping…"));

/* ------------------------------------------------- modulation tab */
let presetMeta = [];        // list_presets rows, for fref lookups

function updateSpsNote() {
  const p = presetMeta.find(x => x.name === $("mod-preset").value);
  if (!p) return;
  const sps = p.fref_mhz * 1e6 / Number($("mod-rb").value);
  $("mod-sps").textContent = sps >= 8
    ? `${sps.toFixed(1)} samples/symbol`
    : (lang === "zh"
       ? `${sps.toFixed(1)} 采样/符号 < 8：离散化底会抬高读数，结论只看失配敏感度`
       : `${sps.toFixed(1)} samples/symbol < 8: the per-ref-cycle grid floors the comparison — trust the mismatch trend`);
}
$("mod-preset").addEventListener("change", updateSpsNote);
$("mod-rb").addEventListener("change", updateSpsNote);

$("mod-run").addEventListener("click", () => runInto(
  "mod-out", async () => {
    const r = await call("modulate", {
      preset: $("mod-preset").value,
      bit_rate_hz: Number($("mod-rb").value),
      dp_err: Number($("mod-dperr").value),
      n_cycles: +$("mod-ncyc").value,
    });
    return metricsHtml([
      ["EVM", r.evm_pct.toFixed(2) + " %"],
      ["EVM", r.evm_db.toFixed(1) + " dB"],
      [lang === "zh" ? "相位误差" : "phase err",
       r.phase_err_rms_deg.toFixed(2) + " deg rms"],
    ]) + pngHtml(r.png);
  }, "调制仿真中…", "modulating…"));

/* ------------------------------------------------- drift tab */
async function updateDriftRate() {
  try {
    const r = await call("drift_info", {
      preset: $("dr-preset").value,
      eps_total: Number($("dr-eps").value),
      ramp_cycles: +$("dr-ncyc").value,
    });
    $("dr-rate").textContent =
      `rate = ${r.rate_per_cycle.toExponential(2)} /cycle = ` +
      `${r.rate_over_mu.toFixed(2)} x mu_final ` +
      `(${r.mu_final.toExponential(1)}) — ` +
      (lang === "zh" ? "超过 1x 即符号-符号转换率墙"
                     : "the sign-sign slew wall is 1x");
  } catch (e) {
    $("dr-rate").textContent = String(e.message || e);
  }
}
$("dr-preset").addEventListener("change", updateDriftRate);
$("dr-eps").addEventListener("change", updateDriftRate);
$("dr-ncyc").addEventListener("change", updateDriftRate);

$("dr-run").addEventListener("click", () => runInto(
  "dr-out", async () => {
    const r = await call("drift", {
      preset: $("dr-preset").value,
      eps_total: Number($("dr-eps").value),
      ramp_cycles: +$("dr-ncyc").value,
      ramp_start: +$("dr-start").value,
    });
    return metricsHtml([
      [lang === "zh" ? "峰值滞后" : "peak lag",
       r.peak_lag_pct.toFixed(2) + " %"],
      ["jitter", r.jitter_fs === null ? "-" : r.jitter_fs.toFixed(0) + " fs"],
      [lang === "zh" ? "滞后杂散" : "lag spur",
       r.lag_spur_dbc === null ? "-" : r.lag_spur_dbc.toFixed(1) + " dBc"],
    ]) + notesHtml(r.notes) + pngHtml(r.png);
  }, "斜坡仿真中…", "ramping…"));

/* ------------------------------------------------- benchmarks tab */
let benchLoaded = false;
async function loadBench() {
  if (benchLoaded) return;
  try {
    const r = await call("benchmarks");
    $("bench-out").innerHTML = tableHtml(r.rows.map(x => ({
      paper: x.paper,
      "published [fs]": x["published [fs]"],
      "linear [fs]": x["linear [fs]"],
      "time-domain [fs]": x["time-domain [fs]"],
    })));
    benchLoaded = true;
  } catch (e) {
    $("bench-out").innerHTML = errHtml(e);
  }
}
document.querySelector('#tabs button[data-tab="bench"]')
  .addEventListener("click", loadBench);

/* ---------------------------------------------------------- boot */
async function boot() {
  applyLang();
  try {
    const presets = await call("list_presets");
    const opt = p =>
      `<option value="${esc(p.name)}">${esc(p.name)} (${esc(p.arch)})</option>`;
    $("preset").innerHTML = presets.map(opt).join("");
    $("sp-preset").innerHTML = presets.filter(p => p.frac).map(opt).join("");
    $("hop-preset").innerHTML = presets.map(opt).join("");
    $("sw-preset").innerHTML =
      presets.filter(p => p.sweepable).map(opt).join("");
    presetMeta = presets;
    $("mod-preset").innerHTML =
      presets.filter(p => p.two_point).map(opt).join("");
    $("dr-preset").innerHTML =
      presets.filter(p => p.frac).map(opt).join("");
    updateSpsNote();
    updateDriftRate();
    $("boot").hidden = true;
    $("app").hidden = false;
    await loadPreset(presets[0].name);
    await updateFllBanner();
  } catch (e) {
    $("boot").innerHTML = errHtml(e);
  }
}

$("preset").addEventListener("change", ev => loadPreset(ev.target.value));
$("run-analyze").addEventListener("click", runAnalyze);
$("run-simulate").addEventListener("click", runSimulate);
$("m-os").addEventListener("change", updateFineNote);
$("n-cycles").addEventListener("change", updateFineNote);
$("lang").addEventListener("click", () => {
  lang = lang === "zh" ? "en" : "zh";
  applyLang();
  if (fieldMeta) loadPreset($("preset").value);
});

boot();
