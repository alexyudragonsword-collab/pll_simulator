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
  // the header title is a copy of the active entry's label; applyLang has
  // just rewritten those, so the copy is stale until refreshed here
  const active = document.querySelector("#tabs button.active");
  const title = document.getElementById("section-title");
  if (active && title) title.textContent = active.textContent;
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

/* Plots and their cursor maps.  The map is kept beside the image rather than
 * inlined into the markup because it is tens of KiB of numbers: a data-
 * attribute would be re-parsed on every render, and the DOM is not a place to
 * store a 7500-point periodogram. */
const plotData = new Map();
let plotSeq = 0;

function pngHtml(b64, cursor) {
  let attr = "";
  if (cursor && cursor.axes && cursor.axes.length) {
    const id = "p" + (++plotSeq);
    plotData.set(id, cursor);
    attr = ` data-cursor="${id}"`;
  } else if (cursor && cursor.dropped && cursor.dropped.length) {
    // say why rather than leaving the reader to wonder: a plot that silently
    // has no cursor is indistinguishable from one that is broken
    attr = ` data-nocursor="${esc(cursor.dropped.join(", "))}"`;
  }
  return `<img class="plot"${attr} src="data:image/png;base64,${b64}">`;
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
    $("bank-out").innerHTML = "";
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
    // the coarse-band bank first, as the desktop pages do: a bank that
    // cannot reach the target is the first thing to know, not a footnote
    // under thirty text boxes
    try {
      const bank = await call("bank", wbArgs());
      $("bank-out").innerHTML = bank.length
        ? `<p class="muted">${lang === "zh" ? "粗调频段组 (osc.v_min / v_max)"
             : "Coarse band bank (osc.v_min / v_max)"}</p>` +
          tableHtml(bank.map(b => ({
            check: lang === "zh" ? b.label_zh : b.label_en, value: b.value })))
        : "";
    } catch (e) {                  // a half-typed override; the run reports it
      $("bank-out").innerHTML = "";
    }
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
    html += pngHtml(r.png, r.cursor);
    // the curve says what shape the noise is; the pie says what to fix
    html += pngHtml(r.pie_png) + tableHtml(r.ipn_rows.map(x => ({
      source: x.source,
      "share [%]": x.share_pct.toFixed(1),
      "jitter [fs]": x.jitter_fs.toFixed(1),
    })));
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
    r.pngs.forEach(p => { html += `<p class="muted">${esc(p.title)}</p>` + pngHtml(p.png, p.cursor); });
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

/* --------------------------------------------------- navigation drawer
 * The left drawer is the phone's navigation: entries listed vertically,
 * opened by an edge swipe or the hamburger, closed by choosing one.  A
 * horizontal bar was carried alongside it for one release so the two could
 * be compared on a real device; that comparison is settled and the bar is
 * gone, along with the ?nav= switch and the Gradle flavors that selected it.
 */
function drawerOpen() {
  return $("drawer").classList.contains("open");
}

function setDrawer(open) {
  const d = $("drawer");
  d.classList.remove("dragging");
  d.style.transform = "";            // hand control back to the class
  d.classList.toggle("open", open);
  $("scrim").hidden = !open;
  $("menu-btn").setAttribute("aria-expanded", String(open));
}

function showTab(name) {
  document.querySelectorAll("#tabs button").forEach(b =>
    b.classList.toggle("active", b.dataset.tab === name));
  document.querySelectorAll(".tab").forEach(t =>
    t.hidden = t.id !== "tab-" + name);
  const btn = document.querySelector(`#tabs button[data-tab="${name}"]`);
  if (btn) $("section-title").textContent = btn.textContent;
  setDrawer(false);                  // choosing is done; get out of the way
}
document.querySelectorAll("#tabs button").forEach(b =>
  b.addEventListener("click", () => showTab(b.dataset.tab)));

$("menu-btn").addEventListener("click", () => setDrawer(!drawerOpen()));
$("scrim").addEventListener("click", () => setDrawer(false));

/* The horizontal drag.  Pointer events, not touch events: Playwright's
 * page.mouse drives pointer events, so the gesture is checkable in the
 * harness instead of only by hand. */
const EDGE_PX = 20;
let drag = null;

document.addEventListener("pointerdown", ev => {
  if (lightboxOpen()) return;      // the viewer is on top and owns the drag
  const open = drawerOpen();
  if (!open && ev.clientX > EDGE_PX) return;      // not an edge pull
  if (open && !$("drawer").contains(ev.target) && ev.target !== $("scrim")) return;
  drag = { x0: ev.clientX, open, w: $("drawer").offsetWidth, moved: false };
});

document.addEventListener("pointermove", ev => {
  if (!drag) return;
  const dx = ev.clientX - drag.x0;
  if (!drag.moved && Math.abs(dx) < 6) return;    // let taps stay taps
  drag.moved = true;
  const d = $("drawer");
  d.classList.add("dragging");
  $("scrim").hidden = false;
  const base = drag.open ? 0 : -drag.w;
  const x = Math.max(-drag.w, Math.min(0, base + dx));
  d.style.transform = `translateX(${x}px)`;
});

document.addEventListener("pointerup", ev => {
  if (!drag) return;
  const d = drag;
  drag = null;
  if (!d.moved) { setDrawer(d.open); return; }
  const dx = ev.clientX - d.x0;
  const base = d.open ? 0 : -d.w;
  setDrawer(base + dx > -d.w / 2);                // past halfway decides
});

/* The Android back button, forwarded by MainActivity.  Returning true means
 * "handled"; anything else lets the activity finish.  Not reachable from the
 * harness -- Chromium has no hardware back -- so it is device-verified. */
window.onAndroidBack = function () {
  if (lightboxOpen()) { closeLightbox(); return true; }
  if (drawerOpen()) { setDrawer(false); return true; }
  return false;
};

/* ------------------------------------------------- full-screen plot viewer
 * A phase-noise plot spans eight decades; in a 412 px column the reader can
 * see that a curve exists and nothing else.  Tapping one opens it here, with
 * pinch / double-tap / drag.
 *
 * Pointer events again, and for the same reason as the drawer: the harness
 * can drive them (multi-touch through CDP), so the gesture is checked rather
 * than eyeballed.  The scale lands in a data attribute precisely so a test
 * can read the zoom instead of trusting a screenshot.
 */
const MAX_SCALE = 8, DOUBLE_TAP_MS = 320;
const lbPointers = new Map();
let lbView = { s: 1, x: 0, y: 0 };   // transform: translate(x,y) scale(s)
let lbOrigin = 0;                    // untransformed left edge, screen coords
let lbOriginY = 0;
let lbPinch = null, lbDrag = null, lbLastTap = 0, lbDownTarget = null;

function lightboxOpen() { return !$("lightbox").hidden; }

/* Double-tap goes to the image's own resolution rather than a round number.
 * The bridge renders at dpi=130, which for the workbench PN plot is 1153 px
 * across; in a 412 px column that is 2.80x, so a fixed 3x was already past
 * native and softening the very detail the zoom exists to show.  Measured,
 * not guessed -- and it re-measures per image, because the pie and the
 * spectrum are not the same size. */
function lbNativeScale() {
  const el = $("lightbox-img");
  if (!el.naturalWidth || !el.offsetWidth) return 3;
  return Math.max(2, Math.min(MAX_SCALE, el.naturalWidth / el.offsetWidth));
}

function lbApply() {
  const el = $("lightbox-stage");
  el.style.transform =
    `translate(${lbView.x}px, ${lbView.y}px) scale(${lbView.s})`;
  const lb = $("lightbox");
  lb.dataset.scale = lbView.s.toFixed(3);
  lb.classList.toggle("zoomed", lbView.s > 1.01);
}

function lbClampPan() {
  // keep at least a corner of the image on screen; a plot dragged into the
  // void with no way back is worse than no panning at all
  const el = $("lightbox-stage");
  const w = el.offsetWidth * lbView.s, h = el.offsetHeight * lbView.s;
  const minX = Math.min(0, innerWidth - lbOrigin - w);
  const minY = Math.min(0, innerHeight - lbOriginY - h);
  lbView.x = Math.max(minX, Math.min(lbView.x, Math.max(0, -lbOrigin + 0)));
  lbView.y = Math.max(minY, Math.min(lbView.y, Math.max(0, -lbOriginY + 0)));
}

function lbZoomTo(scale, qx, qy) {
  const s1 = Math.max(1, Math.min(MAX_SCALE, scale));
  const ux = qx - lbOrigin, uy = qy - lbOriginY;
  lbView.x = ux - (ux - lbView.x) * (s1 / lbView.s);
  lbView.y = uy - (uy - lbView.y) * (s1 / lbView.s);
  lbView.s = s1;
  if (s1 === 1) { lbView.x = 0; lbView.y = 0; }
  lbClampPan();
  lbApply();
}

function lbMeasure() {
  const r = $("lightbox-stage").getBoundingClientRect();
  lbOrigin = r.left; lbOriginY = r.top;
}

function openLightbox(src, cursorId, noCursorWhy) {
  const lb = $("lightbox"), stage = $("lightbox-stage");
  const img = $("lightbox-img");
  img.src = src;
  lbView = { s: 1, x: 0, y: 0 };
  stage.style.transform = "";
  lb.hidden = false;

  lbMeasure();
  lbCursorSetup(cursorId, noCursorWhy);
  lbApply();
  // A src assignment does not lay out synchronously, so the eager measure
  // above can describe the previous image.  Re-measure once the new one is
  // there.  (This was originally written to fix a wrong cursor reading; that
  // turned out to be a harness bug comparing against an edited config, not a
  // race.  Kept because the asynchrony is real, not because it was measured.)
  if (!img.complete) {
    img.addEventListener("load", () => {
      lbMeasure();
      lbApply();
      if (lbCur && lbCur.on && lbCur.i >= 0) { lbDrawCursor(); lbRenderReadout(); }
    }, { once: true });
  }
}

function closeLightbox() {
  const lb = $("lightbox");
  lb.hidden = true;
  lb.classList.remove("zoomed", "dragging");
  lbPointers.clear(); lbPinch = null; lbDrag = null;
  lbCursorOff();
  $("lightbox-img").src = "";
}

/* ------------------------------------------------------- the plot cursor
 * The same contract as the desktop: snap to a sample, then read *every*
 * curve at that abscissa, worst first.  "What is it at 1 MHz" and "which
 * source is responsible" are two questions, and a crosshair reporting one
 * (x, y) answers neither.
 *
 * The numbers are the ones the figure was drawn from -- pllsim.plotting
 * hands over Line2D.get_xdata(), not a second evaluation of the model -- so
 * the readout cannot drift from the curve under the finger.  The axes
 * rectangle arrives in the PNG's own pixels, which is why the overlay
 * canvas is sized to the PNG rather than to its on-screen box.
 */
let lbCur = null;          // {data, ax, i, ref, on}

function lbCursorSetup(cursorId, noCursorWhy) {
  const btn = $("lightbox-cursor"), dbtn = $("lightbox-delta");
  lbCur = null;
  dbtn.hidden = true;
  btn.classList.remove("on");
  $("lightbox-readout").hidden = true;
  const data = cursorId ? plotData.get(cursorId) : null;
  if (!data) {
    btn.hidden = true;
    if (noCursorWhy) {
      // a plot that silently has no cursor reads as broken; say which curves
      // were too long to send rather than leaving it blank
      const r = $("lightbox-readout");
      r.textContent = (lang === "zh"
        ? "此图无游标：曲线点数超出传输上限\n" : "no cursor here: trace too long to send\n")
        + "  " + noCursorWhy;
      r.hidden = false;
    }
    return;
  }
  btn.hidden = false;
  lbCur = { data, ax: data.axes[0], i: -1, ref: null, on: false };
}

function lbCursorOff() {
  lbCur = null;
  $("lightbox-readout").hidden = true;
  $("lightbox-cursor").classList.remove("on");
  $("lightbox-delta").hidden = true;
  const c = $("lightbox-overlay");
  const g = c.getContext("2d");
  if (g) g.clearRect(0, 0, c.width, c.height);
}

function lbGridOf(t) {
  // x lives on the trace, or on the axes when every curve shares one, and
  // either may be an arithmetic grid sent as start/step/n
  const u = t.x_uniform || lbCur.ax.x_uniform;
  if (u) return { n: u.n, at: k => u.start + k * u.step };
  const arr = t.x || lbCur.ax.x;
  return { n: arr.length, at: k => arr[k] };
}

function lbAxisToPx(v, lo, hi, a, b, log) {
  const f = log ? Math.log10 : (z => z);
  return a + (f(v) - f(lo)) / (f(hi) - f(lo)) * (b - a);
}

function lbPxToAxis(p, lo, hi, a, b, log) {
  const f = log ? Math.log10 : (z => z);
  const t = (p - a) / (b - a);
  const v = f(lo) + t * (f(hi) - f(lo));
  return log ? Math.pow(10, v) : v;
}

/** Nearest sample index on the longest trace, given an x in PNG pixels. */
function lbIndexAt(pxImage) {
  const A = lbCur.ax, [x0, , x1] = [A.box[0], A.box[1], A.box[2]];
  const xd = lbPxToAxis(pxImage, A.xlim[0], A.xlim[1], x0, x1, A.xlog);
  let best = null;
  for (const t of A.traces) {
    const g = lbGridOf(t);
    // binary search on a monotonic abscissa; these run to 7500 points and
    // this happens on every pointer move
    let lo = 0, hi = g.n - 1;
    while (hi - lo > 1) {
      const mid = (lo + hi) >> 1;
      if (g.at(mid) <= xd) lo = mid; else hi = mid;
    }
    const k = Math.abs(g.at(lo) - xd) <= Math.abs(g.at(hi) - xd) ? lo : hi;
    const d = Math.abs(g.at(k) - xd);
    if (best === null || d < best.d) best = { d, k, x: g.at(k) };
  }
  return best;
}

function lbRowsAt(xd) {
  const rows = [];
  for (const t of A_traces()) {
    const g = lbGridOf(t);
    if (xd < Math.min(g.at(0), g.at(g.n - 1)) ||
        xd > Math.max(g.at(0), g.at(g.n - 1))) continue;
    let lo = 0, hi = g.n - 1;
    while (hi - lo > 1) {
      const mid = (lo + hi) >> 1;
      if (g.at(mid) <= xd) lo = mid; else hi = mid;
    }
    const k = Math.abs(g.at(lo) - xd) <= Math.abs(g.at(hi) - xd) ? lo : hi;
    rows.push({ label: t.label, y: t.y[k], color: t.color });
  }
  return rows.sort((p, q) => q.y - p.y);
}
function A_traces() { return lbCur.ax.traces; }

function lbEng(v) {
  if (!isFinite(v) || v === 0) return String(v);
  const a = Math.abs(v);
  const u = [[1e9, "G"], [1e6, "M"], [1e3, "k"], [1, ""], [1e-3, "m"],
             [1e-6, "µ"], [1e-9, "n"]];
  for (const [lim, suf] of u) {
    if (a >= lim) return (v / lim).toPrecision(4).replace(/\.?0+$/, "") + suf;
  }
  return v.toExponential(3);
}

function lbDrawCursor() {
  const c = $("lightbox-overlay"), A = lbCur.ax;
  const g = c.getContext("2d");
  c.width = lbCur.data.w; c.height = lbCur.data.h;
  g.clearRect(0, 0, c.width, c.height);
  if (lbCur.i < 0) return;
  const draw = (xv, style, width) => {
    const px = lbAxisToPx(xv, A.xlim[0], A.xlim[1], A.box[0], A.box[2], A.xlog);
    g.save();
    g.strokeStyle = style; g.lineWidth = width; g.setLineDash([6, 4]);
    g.beginPath(); g.moveTo(px, A.box[1]); g.lineTo(px, A.box[3]); g.stroke();
    g.restore();
  };
  if (lbCur.ref !== null) draw(lbCur.ref.x, "#d32f2f", 2);
  draw(lbCur.x, "#111", 2);
}

function lbRenderReadout() {
  const out = $("lightbox-readout"), A = lbCur.ax;
  if (lbCur.i < 0) { out.hidden = true; return; }
  const rows = lbRowsAt(lbCur.x);
  const xname = (A.xlabel || "x").split("[")[0].trim();
  const lines = [`${xname} = ${lbEng(lbCur.x)}`];
  if (lbCur.ref === null) {
    for (const r of rows) {
      lines.push("  " + r.label.padEnd(20).slice(0, 20) +
                 r.y.toFixed(2).padStart(9));
    }
  } else {
    const top = rows.length ? rows[0].label : "";
    const now = rows.length ? rows[0].y : NaN;
    const dy = now - lbCur.ref.y;
    lines.push(`ref = ${lbEng(lbCur.ref.x)}`);
    lines.push(`Δ   = ${lbEng(lbCur.x - lbCur.ref.x)}`);
    lines.push(`Δ${top} = ${dy >= 0 ? "+" : ""}${dy.toFixed(2)} dB`);
    if (A.xlog && lbCur.x > 0 && lbCur.ref.x > 0 && lbCur.x !== lbCur.ref.x) {
      const dec = Math.log10(lbCur.x / lbCur.ref.x);
      const sl = dy / dec;
      lines.push(`slope = ${sl >= 0 ? "+" : ""}${sl.toFixed(1)} dB/dec`);
    }
  }
  out.textContent = lines.join("\n");
  out.hidden = false;
  $("lightbox").dataset.cursorX = String(lbCur.x);
}

/** Move the cursor to a client-space point. */
function lbCursorTo(clientX) {
  const c = $("lightbox-overlay");
  const r = c.getBoundingClientRect();       // includes the zoom transform
  if (!r.width) return;                      // not laid out yet
  const pxImage = (clientX - r.left) / r.width * lbCur.data.w;
  const hit = lbIndexAt(pxImage);
  if (!hit) return;
  lbCur.i = hit.k; lbCur.x = hit.x;
  lbDrawCursor();
  lbRenderReadout();
}

$("lightbox-cursor").addEventListener("click", ev => {
  ev.stopPropagation();
  if (!lbCur) return;
  lbCur.on = !lbCur.on;
  $("lightbox-cursor").classList.toggle("on", lbCur.on);
  $("lightbox-delta").hidden = !lbCur.on;
  if (!lbCur.on) {
    lbCur.i = -1; lbCur.ref = null;
    lbDrawCursor();
    $("lightbox-readout").hidden = true;
  } else if (lbCur.i < 0) {
    lbCursorTo(innerWidth / 2);
  }
});

$("lightbox-delta").addEventListener("click", ev => {
  ev.stopPropagation();
  if (!lbCur || !lbCur.on) return;
  if (lbCur.ref !== null) { lbCur.ref = null; }
  else if (lbCur.i >= 0) {
    const rows = lbRowsAt(lbCur.x);
    if (!rows.length) return;
    lbCur.ref = { x: lbCur.x, y: rows[0].y };
  }
  lbDrawCursor();
  lbRenderReadout();
});

// delegated: plots are injected into a dozen different output containers,
// and a per-render binding is a binding somebody forgets on the next tab
document.addEventListener("click", ev => {
  const img = ev.target.closest && ev.target.closest("img.plot");
  if (img && !lightboxOpen()) {
    openLightbox(img.src, img.dataset.cursor, img.dataset.nocursor);
  }
});

$("lightbox-close").addEventListener("click", ev => {
  ev.stopPropagation();
  closeLightbox();
});

const lb = $("lightbox");

lb.addEventListener("pointerdown", ev => {
  // Controls own their own taps.  setPointerCapture does not merely retarget
  // pointer events -- it moves the *click* target to the capturing element
  // too, so capturing here swallowed the close button entirely: tapping the
  // X did nothing at all, and no test had ever tapped it.
  if (ev.target.closest("button")) return;
  // before setPointerCapture: capture retargets every later pointer event to
  // the capturing element, so ev.target at pointerup is always #lightbox and
  // "did this gesture start on the image" has to be answered here
  lbDownTarget = ev.target;
  lbPointers.set(ev.pointerId, { x: ev.clientX, y: ev.clientY });
  lb.setPointerCapture(ev.pointerId);
  if (lbPointers.size === 2) {
    const [a, b] = [...lbPointers.values()];
    lbPinch = { d0: Math.hypot(a.x - b.x, a.y - b.y), s0: lbView.s,
                cx: (a.x + b.x) / 2, cy: (a.y + b.y) / 2 };
    lbDrag = null;
    lb.classList.add("dragging");
    return;
  }
  if (lbPointers.size === 1) {
    lbDrag = { x0: ev.clientX, y0: ev.clientY,
               vx: lbView.x, vy: lbView.y, moved: false };
  }
});

lb.addEventListener("pointermove", ev => {
  if (!lbPointers.has(ev.pointerId)) return;
  lbPointers.set(ev.pointerId, { x: ev.clientX, y: ev.clientY });
  if (lbPinch && lbPointers.size >= 2) {
    const [a, b] = [...lbPointers.values()];
    const d = Math.hypot(a.x - b.x, a.y - b.y);
    if (lbPinch.d0 > 0) {
      lbZoomTo(lbPinch.s0 * (d / lbPinch.d0), lbPinch.cx, lbPinch.cy);
    }
    return;
  }
  // with the cursor armed, one finger drives it and two still pinch: the
  // alternative is a drag that both pans and reads, which does neither well
  if (lbCur && lbCur.on && lbPointers.size === 1) {
    if (lbDrag) lbDrag.moved = true;
    lbCursorTo(ev.clientX);
    return;
  }
  if (lbDrag && lbView.s > 1) {
    const dx = ev.clientX - lbDrag.x0, dy = ev.clientY - lbDrag.y0;
    if (!lbDrag.moved && Math.hypot(dx, dy) < 6) return;  // let taps stay taps
    lbDrag.moved = true;
    lb.classList.add("dragging");
    lbView.x = lbDrag.vx + dx;
    lbView.y = lbDrag.vy + dy;
    lbClampPan();
    lbApply();
  }
});

function lbEndPointer(ev) {
  const had = lbPointers.delete(ev.pointerId);
  if (lbPointers.size < 2) { lbPinch = null; }
  if (lbPointers.size === 0) {
    lb.classList.remove("dragging");
    const dragged = lbDrag && lbDrag.moved;
    lbDrag = null;
    if (!had || dragged) return;
    const now = Date.now();
    if (now - lbLastTap < DOUBLE_TAP_MS) {
      lbLastTap = 0;
      lbZoomTo(lbView.s > 1.01 ? 1 : lbNativeScale(), ev.clientX, ev.clientY);
      return;
    }
    lbLastTap = now;
    // a single tap on the backdrop at rest closes; on the image it does not,
    // because that is where the second tap of a double-tap lands
    if (lbView.s <= 1.01 && lbDownTarget === lb) {
      setTimeout(() => { if (lbLastTap) closeLightbox(); }, DOUBLE_TAP_MS);
    }
  }
}
lb.addEventListener("pointerup", lbEndPointer);
lb.addEventListener("pointercancel", lbEndPointer);

/* The activity handles orientation itself (configChanges in the manifest),
 * so the WebView reflows without a reload: the image gets a new box while
 * lbOrigin still describes the old one, and every anchor computed after that
 * is wrong.  Re-measure and go back to fit. */
addEventListener("resize", () => {
  if (!lightboxOpen()) return;
  const el = $("lightbox-stage");     // the element the transform lives on
  lbView = { s: 1, x: 0, y: 0 };
  el.style.transform = "";
  const r = el.getBoundingClientRect();
  lbOrigin = r.left; lbOriginY = r.top;
  lbApply();
  if (lbCur && lbCur.on) { lbDrawCursor(); }
});

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

async function spurFineNote(mId, cycId, outId) {
  const m = +$(mId).value;
  const el = $(outId);
  if (m <= 1) { el.textContent = ""; return; }
  try {
    const r = await call("fine_info", {
      preset: $("sp-preset").value, n_cycles: +$(cycId).value, m,
    });
    if (!r.supported) {
      el.textContent = lang === "zh"
        ? "该架构没有周期内记录，M 会被忽略"
        : "this architecture has no intra-period record — M is ignored";
      return;
    }
    // the note is the whole point: an M coarser than the reset pulse cannot
    // resolve the ripple doublet, and the spur then reads LOW with nothing
    // on screen saying so
    el.textContent = `record ~${r.record_mb.toFixed(0)} MB` +
      (r.note ? " — " + r.note : "");
  } catch (e) {
    el.textContent = String(e.message || e);
  }
}

function refreshSpurNotes() {
  spurFineNote("sp-mmeas", "sp-ncyc", "sp-mmeas-note");
  spurFineNote("sp-m", "sp-refcyc", "sp-ref-note");
}
["sp-preset", "sp-mmeas", "sp-ncyc", "sp-m", "sp-refcyc"].forEach(id =>
  $(id).addEventListener("change", refreshSpurNotes));

$("sp-predict").addEventListener("click", () => runInto(
  "sp-predict-out", async () => {
    const r = await call("spur_predict", spurArgs());
    return tableHtml(r.rows.map(x =>
      ({ offset: x.offset, "spur [dBc]": x.dbc }))) + notesHtml(r.notes);
  }, "analyze…", "analyze…"));

$("sp-measure").addEventListener("click", () => runInto(
  "sp-measure-out", async () => {
    const r = await call("spur_spectrum", {
      ...spurArgs(), n_cycles: +$("sp-ncyc").value,
      fine_oversample: +$("sp-mmeas").value,
    });
    let head = "";
    if (+$("sp-mmeas").value > 1 && !r.fine_applied) {
      head = `<p class="note">${lang === "zh"
        ? "该架构没有周期内记录，M 已忽略"
        : "this architecture has no intra-period record; M was ignored"}</p>`;
    }
    return head + notesHtml(r.notes) + pngHtml(r.png, r.cursor);
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
    return pngHtml(r.png, r.cursor);
  }, "扫描 8 个通道中…", "sweeping 8 channels…"));

/* ---------------------------------------------------------- hop tab */
async function updateFllBanner() {
  const el = $("hop-fll");
  el.innerHTML = "";
  try {
    const st = await call("hop_check", { preset: $("hop-preset").value });
    if (st === null) {
      // silence reads as a failed lookup; the desktop page says which it is
      el.innerHTML = `<p class="muted">${lang === "zh"
        ? "该架构没有 FLL 交接" : "no FLL in this architecture"}</p>`;
      return;
    }
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
    ]) + pngHtml(r.png, r.cursor);
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
    ]) + pngHtml(r.png, r.cursor);
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
      "PM [deg]": x.pm_deg === null ? "-" : x.pm_deg.toFixed(0),
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
    return html + pngHtml(r.png, r.cursor);
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
    ]) + pngHtml(r.png, r.cursor);
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
    ]) + notesHtml(r.notes) + pngHtml(r.png, r.cursor);
  }, "斜坡仿真中…", "ramping…"));

/* ------------------------------------------------- benchmarks tab */
let benchLoaded = false;
async function loadBench() {
  if (benchLoaded) return;
  try {
    const r = await call("benchmarks");
    $("pie-preset").innerHTML = r.presets.map(n =>
      `<option value="${esc(n)}">${esc(n)}</option>`).join("");
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

$("pie-run").addEventListener("click", () => runInto(
  "pie-out", async () => {
    const r = await call("benchmark_ipn", { preset: $("pie-preset").value });
    return metricsHtml([
      ["jitter", r.jitter_fs.toFixed(1) + " fs"],
      ["IPN", r.ipn_dbc.toFixed(1) + " dBc"],
      [lang === "zh" ? "主导源" : "dominant", r.dominant],
    ]) + pngHtml(r.png, r.cursor) + tableHtml(r.rows.map(x => ({
      source: x.source,
      "share [%]": x.share_pct.toFixed(1),
      "jitter [fs]": x.jitter_fs.toFixed(1),
    })));
  }, "analyze…", "analyze…"));

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
    refreshSpurNotes();
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
