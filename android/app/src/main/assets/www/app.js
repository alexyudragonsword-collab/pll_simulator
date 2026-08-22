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
    fieldMeta = await call("fields", { preset: name });
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
    const r = await call("analyze",
      { preset: $("preset").value, overrides: overrides() });
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
    const r = await call("fine_info", {
      preset: $("preset").value, overrides: overrides(),
      n_cycles: +$("n-cycles").value, m,
    });
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
    const r = await call("simulate", {
      preset: $("preset").value, overrides: overrides(),
      n_cycles: nCycles, seed: +$("seed").value,
      noise: $("noise").checked, calibration: $("cal").checked,
      f_start_offset_mhz: +$("f-off").value,
      dtc_gain_init_error: +$("dtc-err").value,
      fine_oversample: m,
    });
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

/* ---------------------------------------------------------- boot */
async function boot() {
  applyLang();
  try {
    const presets = await call("list_presets");
    $("preset").innerHTML = presets.map(p =>
      `<option value="${esc(p.name)}">${esc(p.name)} (${esc(p.arch)})</option>`
    ).join("");
    $("boot").hidden = true;
    $("app").hidden = false;
    await loadPreset(presets[0].name);
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
