// 生成 docs/reports 下的管理层汇报幻灯片。
//
// 凡是关于代码的数字 —— 版本、架构数、preset 数、示例数、测试数、对标表 ——
// 一律来自 collect_facts.py 现算的 facts.json，不在本文件里写死。v0.9.0 的
// 那一版就是写死的，一个版本之内就过期了（还写着 405 项测试、20 个示例）。
// 详见 README.md。
const fs = require("fs");
const path = require("path");
const pptxgen = require("pptxgenjs");

const FACTS_PATH = path.join(__dirname, "facts.json");
if (!fs.existsSync(FACTS_PATH)) {
  console.error("facts.json 不存在 —— 先运行:  python collect_facts.py");
  process.exit(1);
}
const F = JSON.parse(fs.readFileSync(FACTS_PATH, "utf8"));
for (const k of ["version", "architectures", "presets", "examples", "tests",
                 "releases", "benchmarks"]) {
  if (F[k] === undefined) { console.error(`facts.json 缺少 ${k}`); process.exit(1); }
}

const pres = new pptxgen();
pres.layout = "LAYOUT_WIDE";           // 13.3 x 7.5 in
pres.author = "pllsim";
pres.title = "pllsim 项目总结";

// ---- palette: lab-instrument slate + amber signal marker -------------------
const SLATE = "152238";   // deep instrument slate (dark slides)
const SLATE2 = "24405A";  // lighter slate for cards on dark
const TEAL = "2E7D8E";    // secondary
const AMBER = "E8A33D";   // accent / marker
const OFFW = "F5F7FA";    // light background
const CARD = "E8EDF2";    // card tint on light
const INK = "16202B";     // body text on light
const MUTE = "5A6B7B";    // muted text

const HEAD = "Microsoft YaHei";
const BODY = "Microsoft YaHei";

const W = 13.3, H = 7.5, M = 0.7;

function darkBg(s) { s.background = { color: SLATE }; }
function lightBg(s) { s.background = { color: OFFW }; }

// section title on a light slide
function title(s, text, sub) {
  s.addText(text, {
    x: M, y: 0.45, w: W - 2 * M, h: 0.75,
    fontFace: HEAD, fontSize: 32, bold: true, color: INK, margin: 0,
  });
  if (sub) {
    s.addText(sub, {
      x: M, y: 1.2, w: W - 2 * M, h: 0.4,
      fontFace: BODY, fontSize: 14, color: MUTE, margin: 0,
    });
  }
}

// numbered dot motif — repeated on every content slide
function dot(s, n, x, y, size = 0.42, fill = AMBER, txt = SLATE) {
  s.addShape(pres.ShapeType.ellipse, {
    x, y, w: size, h: size, fill: { color: fill },
  });
  s.addText(String(n), {
    x, y, w: size, h: size,
    fontFace: HEAD, fontSize: 15, bold: true, color: txt,
    align: "center", valign: "middle", margin: 0,
  });
}

function card(s, x, y, w, h, fill = CARD) {
  s.addShape(pres.ShapeType.roundRect, {
    x, y, w, h, rectRadius: 0.06, fill: { color: fill },
    shadow: { type: "outer", angle: 90, blur: 8, offset: 0.04,
              color: "9AA8B5", opacity: 0.35 },
  });
}

/* ========================= 1. 封面 ========================= */
{
  const s = pres.addSlide(); darkBg(s);
  s.addShape(pres.ShapeType.ellipse, {
    x: 9.8, y: -1.6, w: 5.6, h: 5.6, fill: { color: SLATE2 },
  });
  s.addShape(pres.ShapeType.ellipse, {
    x: 11.3, y: 4.4, w: 2.6, h: 2.6, fill: { color: TEAL },
  });
  s.addText("pllsim", {
    x: M, y: 2.05, w: 8.5, h: 1.1,
    fontFace: HEAD, fontSize: 56, bold: true, color: "FFFFFF", margin: 0,
  });
  s.addText("锁相环系统级仿真平台", {
    x: M, y: 3.15, w: 8.5, h: 0.6,
    fontFace: HEAD, fontSize: 26, color: AMBER, margin: 0,
  });
  s.addText("项目总结汇报", {
    x: M, y: 3.95, w: 8.5, h: 0.45,
    fontFace: BODY, fontSize: 16, color: "C3CEDA", margin: 0,
  });
  s.addShape(pres.ShapeType.rect, {
    x: M, y: 4.72, w: 3.1, h: 0.02, fill: { color: TEAL },
  });
  s.addText(`v${F.version}    ·    ${F.architectures} 种架构    ·    ${F.tests} 项自动化测试`, {
    x: M, y: 4.95, w: 9.0, h: 0.45,
    fontFace: BODY, fontSize: 14, color: "8FA3B5", margin: 0,
  });
  s.addNotes("pllsim 是一套 PLL 系统级/行为级仿真库，用于架构选型与指标预算阶段。本次汇报覆盖它做什么、凭什么可信、以及一次完备性审计查出了什么。");
}

/* ========================= 2. 解决什么问题 ========================= */
{
  const s = pres.addSlide(); lightBg(s);
  title(s, "解决什么问题", "架构选型阶段需要的是小时级的可比较答案，而不是数天的精确答案");

  const rows = [
    ["晶体管级仿真（Cadence）",
     "一次瞬态跑数小时到数天，且必须先有电路。做完才知道架构选错了。",
     "B8C4CE"],
    ["pllsim 频域线性模型",
     "秒级给出相位噪声分解、环路稳定性、抖动预算 —— 每一条噪声路径单独列出。",
     AMBER],
    ["pllsim 时域行为模型",
     "秒到分钟级跑完锁定过程、杂散、校准收敛、跳频建立、蒙特卡洛良率。",
     AMBER],
  ];
  let y = 2.0;
  rows.forEach(([h1, h2, col], i) => {
    card(s, M, y, W - 2 * M, 1.12);
    s.addShape(pres.ShapeType.ellipse, {
      x: M + 0.32, y: y + 0.33, w: 0.46, h: 0.46, fill: { color: col },
    });
    s.addText(h1, {
      x: M + 1.0, y: y + 0.16, w: 3.6, h: 0.4,
      fontFace: HEAD, fontSize: 16, bold: true, color: INK, margin: 0,
    });
    s.addText(h2, {
      x: M + 4.7, y: y + 0.17, w: W - 2 * M - 5.1, h: 0.8,
      fontFace: BODY, fontSize: 13, color: MUTE, margin: 0,
    });
    y += 1.35;
  });

  s.addText("关键设计：同一份配置，两个域各自独立算，结果必须互相吻合 —— 不吻合就是有一边错了。",
    { x: M, y: 6.25, w: W - 2 * M, h: 0.5,
      fontFace: HEAD, fontSize: 15, bold: true, italic: true, color: TEAL, margin: 0 });
  s.addNotes("两个域互为校验，是这个工具区别于一般脚本的地方：任何一处物理建模错误，都会表现为两个域对不上。");
}

/* ========================= 3. 能力全景 ========================= */
{
  const s = pres.addSlide(); lightBg(s);
  title(s, "能力全景",
    `${F.architectures} 种架构 · ${F.presets} 个预设配置 · ${F.examples} 个可运行示例`);

  const stats = [[`${F.architectures}`, "架构"], [`${F.presets}`, "预设"],
                 [`${F.examples}`, "示例"], [`${F.tests}`, "测试"]];
  stats.forEach(([n, l], i) => {
    const x = M + i * 3.05;
    card(s, x, 1.85, 2.75, 1.15, SLATE);
    s.addText(n, { x, y: 1.95, w: 2.75, h: 0.62,
      fontFace: HEAD, fontSize: 34, bold: true, color: AMBER,
      align: "center", margin: 0 });
    s.addText(l, { x, y: 2.55, w: 2.75, h: 0.35,
      fontFace: BODY, fontSize: 13, color: "C3CEDA", align: "center", margin: 0 });
  });

  const cols = [
    ["架构模型", [
      "电荷泵 PLL（整数N / 小数N）",
      "子采样 PLL、采样 PLL",
      "全数字 PLL（TDC 与 bang-bang 两种）",
      "注入锁定倍频器、多倍频 DLL",
    ]],
    ["分析能力", [
      "环路综合与带宽扫描",
      "架构自动选型与排序",
      "蒙特卡洛良率、PVT 工艺角",
      "跳频建立、温漂跟踪、两点调制 EVM",
    ]],
    ["交付物", [
      "三层 Verilog 导出：RTL / RNM / 电气 AMS",
      "RTL 在导出时用 iverilog 位真验证",
      "双 GUI：桌面 + 浏览器，中英双语",
      "Windows 免安装 exe",
    ]],
  ];
  cols.forEach(([h, items], i) => {
    const x = M + i * 4.15;
    card(s, x - 0.22, 3.42, 4.0, 2.55);
    dot(s, i + 1, x, 3.68);
    s.addText(h, { x: x + 0.58, y: 3.69, w: 3.2, h: 0.4,
      fontFace: HEAD, fontSize: 17, bold: true, color: INK, margin: 0 });
    s.addText(items.map((t, k) => ({
      text: t, options: { bullet: true, breakLine: k !== items.length - 1 },
    })), { x, y: 4.3, w: 3.55, h: 1.55,
      fontFace: BODY, fontSize: 12.5, color: MUTE,
      paraSpaceAfter: 9, margin: 0 });
  });
  s.addText("三层导出的意义：系统级的结论可以直接带进 Cadence 的验证流程，而不是停在 Python 里。",
    { x: M, y: 6.35, w: W - 2 * M, h: 0.5,
      fontFace: HEAD, fontSize: 14.5, bold: true, italic: true, color: TEAL, margin: 0 });
  s.addNotes("三层导出的意义：系统级结论可以直接带进 Cadence 的验证流程，而不是停在 Python 里。");
}

/* ========================= 4. 文献对标 ========================= */
{
  const s = pres.addSlide(); lightBg(s);
  title(s, "凭什么可信：四篇 JSSC 论文对标",
    "五个通道，逐条比较发表值 / 线性模型 / 时域模型的积分抖动（fs）");

  const head = ["论文与通道", "发表值", "线性模型", "时域模型"];
  // only the row labels live here, because they are translations.  Every
  // number comes from presets.benchmark_table() via facts.json, and the
  // linear column of that is recomputed on each call rather than stored.
  const LABELS = [
    "Gao'09  子采样 PLL  2.21 GHz  整数N",
    "Dartizio'23  DTC+BB 数字 PLL  9.25 GHz",
    "Markulic'16  子采样 PLL  10.24 GHz  整数N",
    "Markulic'16  子采样 PLL  10.24 GHz  小数N",
    "Wu'19  采样 PLL  6.25 GHz  小数N",
  ];
  if (F.benchmarks.length !== LABELS.length) {
    console.error(`对标表有 ${F.benchmarks.length} 行，但这里只有 ` +
                  `${LABELS.length} 个标签 —— 加了论文就要加标签`);
    process.exit(1);
  }
  const data = F.benchmarks.map((b, i) => [
    LABELS[i],
    String(b["published [fs]"]).replace("(worst)", "（最差）"),
    String(b["linear [fs]"]),
    String(b["time-domain [fs]"]),
  ]);
  const tRows = [head.map((h, i) => ({
    text: h,
    options: { bold: true, color: "FFFFFF", fill: { color: SLATE },
               fontSize: 13, align: i === 0 ? "left" : "center" },
  }))];
  data.forEach((r, ri) => {
    tRows.push(r.map((c, i) => ({
      text: c,
      options: { fontSize: 12.5, color: INK,
                 align: i === 0 ? "left" : "center",
                 fill: { color: ri % 2 ? "FFFFFF" : CARD },
                 bold: i === 3 },
    })));
  });
  s.addTable(tRows, {
    x: M, y: 1.9, w: W - 2 * M, colW: [6.3, 1.85, 1.85, 1.9],
    rowH: 0.42, fontFace: BODY, valign: "middle",
    border: { type: "solid", color: "D3DBE3", pt: 0.5 },
  });

  card(s, M, 4.82, 5.85, 1.8);
  dot(s, 1, M + 0.3, 5.06, 0.42, TEAL, "FFFFFF");
  s.addText("时域模型全部落在发表值附近", {
    x: M + 0.88, y: 5.07, w: 4.7, h: 0.36,
    fontFace: HEAD, fontSize: 15, bold: true, color: INK, margin: 0 });
  s.addText("未公开的电路参数一律用标注过的工艺合理假设。验证的是架构一致性，不是逐点复现某颗芯片。",
    { x: M + 0.3, y: 5.58, w: 5.25, h: 0.9,
      fontFace: BODY, fontSize: 12.5, color: MUTE, margin: 0 });

  card(s, M + 6.2, 4.82, 5.7, 1.8);
  dot(s, 2, M + 6.5, 5.06, 0.42, AMBER, SLATE);
  s.addText("Dartizio'23 线性模型偏低是已知的", {
    x: M + 7.08, y: 5.07, w: 4.5, h: 0.36,
    fontFace: HEAD, fontSize: 15, bold: true, color: INK, margin: 0 });
  s.addText("线性化会低估 bang-bang 环路 —— 时域模型给出 77 fs，与发表值一致。差异有物理解释，不是拟合失败。",
    { x: M + 6.5, y: 5.58, w: 5.1, h: 0.9,
      fontFace: BODY, fontSize: 12.5, color: MUTE, margin: 0 });
  s.addNotes("这一页回答管理层最关心的问题：凭什么相信这个工具的数字。答案是对着公开发表的五个通道逐条比过，且差异都能解释。");
}

/* ========================= 5. 完备性审计 ========================= */
{
  const s = pres.addSlide(); darkBg(s);
  s.addText("完备性审计：查出了什么", {
    x: M, y: 0.45, w: W - 2 * M, h: 0.75,
    fontFace: HEAD, fontSize: 32, bold: true, color: "FFFFFF", margin: 0 });
  s.addText("把工程对照它自己的说法系统审计一遍，问题分三类", {
    x: M, y: 1.2, w: W - 2 * M, h: 0.4,
    fontFace: BODY, fontSize: 14, color: "8FA3B5", margin: 0 });

  const items = [
    ["静默给出错误数字",
     "参考杂散公式错 38 dB；采样器噪声低 3 dB。使用者拿到一份完全正常的报告，无从察觉。"],
    ["接受了却不起作用的输入",
     "bang-bang 数字 PLL 的两点调制被静默丢弃 —— 返回一份看起来正常、里面却没有任何调制的结果。"],
    ["检查本身在空转",
     "导出的交叉引用检查在电气顶层上匹配到零个实例，所有检查都在对空气通过。"],
  ];
  let y = 1.95;
  items.forEach(([h, d], i) => {
    card(s, M, y, W - 2 * M, 1.35, SLATE2);
    dot(s, i + 1, M + 0.35, y + 0.45);
    s.addText(h, { x: M + 1.0, y: y + 0.24, w: 4.3, h: 0.42,
      fontFace: HEAD, fontSize: 17, bold: true, color: AMBER, margin: 0 });
    s.addText(d, { x: M + 5.35, y: y + 0.24, w: W - 2 * M - 5.75, h: 0.9,
      fontFace: BODY, fontSize: 13, color: "D7E0E8", margin: 0 });
    y += 1.55;
  });
  s.addText("三类都已修复并配了会失败的回归测试 —— 每一处都先确认它在旧代码上确实失败。", {
    x: M, y: 6.6, w: W - 2 * M, h: 0.45,
    fontFace: HEAD, fontSize: 14.5, bold: true, italic: true, color: TEAL, margin: 0 });
  s.addNotes("第二类最危险：结果看起来完全正常。这类问题在没有交叉验证的工具里可以存在很多年。");
}

/* ========================= 6. 关键发现详解 ========================= */
{
  const s = pres.addSlide(); lightBg(s);
  title(s, "一个值得展开的发现：参考杂散",
    "上一版修掉一个 6 dB 错误后，留下一句「时域无法检验这一条」");

  card(s, M, 1.9, 5.75, 4.05);
  s.addText("接受那句话，才是真正的错误", {
    x: M + 0.35, y: 2.12, w: 5.05, h: 0.42,
    fontFace: HEAD, fontSize: 17, bold: true, color: INK, margin: 0 });
  s.addText([
    { text: "时域记录每参考周期只取一个点，fref 处的杂散正好落在记录自身的采样率上、混叠到直流。",
      options: { bullet: true, breakLine: true } },
    { text: "于是解析式可以预测一个「没有任何东西能反驳」的数字。",
      options: { bullet: true, breakLine: true } },
    { text: "增加周期内细采样后，立刻发现式子仍然错 38 dB。",
      options: { bullet: true, breakLine: false } },
  ], { x: M + 0.35, y: 2.68, w: 5.05, h: 1.75,
       fontFace: BODY, fontSize: 13, color: MUTE, paraSpaceAfter: 9, margin: 0 });
  s.addText("测不到的约定，就是会漂的约定。", {
    x: M + 0.35, y: 4.95, w: 5.05, h: 0.75,
    fontFace: HEAD, fontSize: 17, bold: true, italic: true, color: AMBER, margin: 0 });

  card(s, M + 6.1, 1.9, 5.8, 4.05);
  s.addText("物理上是怎么回事", {
    x: M + 6.45, y: 2.12, w: 5.1, h: 0.42,
    fontFace: HEAD, fontSize: 17, bold: true, color: INK, margin: 0 });
  const steps = [
    "锁定时，二型环路已把每周期净电荷拉到零",
    "剩下的是一对反号脉冲（偶极），不是单个冲激",
    "二者面积抵消，基波只靠时间间隔存活",
    "被压低 2·sin(π·fref·Δt) —— 本例正是 38 dB",
  ];
  let sy = 2.72;
  steps.forEach((t, i) => {
    dot(s, i + 1, M + 6.45, sy, 0.34, TEAL, "FFFFFF");
    s.addText(t, { x: M + 6.95, y: sy - 0.03, w: 4.65, h: 0.44,
      fontFace: BODY, fontSize: 12.5, color: MUTE, valign: "middle", margin: 0 });
    sy += 0.62;
  });
  s.addText("修正后：解析与时域吻合到 0.01 dB", {
    x: M + 6.45, y: 5.28, w: 5.1, h: 0.45,
    fontFace: HEAD, fontSize: 15, bold: true, color: TEAL, margin: 0 });

  s.addText("同一次审计还发现：子采样架构的参考杂散在物理上根本不存在 —— 这是该架构的真实优势，不是建模缺陷。",
    { x: M, y: 6.25, w: W - 2 * M, h: 0.5,
      fontFace: BODY, fontSize: 13, color: MUTE, margin: 0 });
  s.addNotes("这一页的价值不在这一个公式，而在方法：任何无法被独立检验的模型断言，都应当视为待验证而不是已验证。");
}

/* ========================= 7. 质量体系 ========================= */
{
  const s = pres.addSlide(); lightBg(s);
  title(s, "质量体系",
    `${F.tests} 项自动化测试，每次代码提交在两个 Python 版本上全量运行`);

  const blocks = [
    ["跨域一致性", "同一份配置，频域与时域各自独立算，结果必须吻合。任何物理建模错误都会表现为两边对不上。"],
    ["单源主导测试", "把一条噪声路径抬到占预算 90% 以上再比较。比「总量」的测试容差宽到能藏住单项 3 dB 的错误 —— 三个物理 bug 就是这样活下来的。"],
    ["变异测试", "故意植入缺陷，验证检查确实会失败。防止出现「只会说没问题」的检查。"],
    ["位真验证", "导出的 RTL 在导出时就用 iverilog 跑向量比对，不是等到进 Cadence 才发现。"],
  ];
  blocks.forEach(([h, d], i) => {
    const x = M + (i % 2) * 6.15;
    const y = 1.95 + Math.floor(i / 2) * 2.05;
    card(s, x, y, 5.75, 1.8);
    dot(s, i + 1, x + 0.32, y + 0.3);
    s.addText(h, { x: x + 0.9, y: y + 0.31, w: 4.6, h: 0.4,
      fontFace: HEAD, fontSize: 16.5, bold: true, color: INK, margin: 0 });
    s.addText(d, { x: x + 0.32, y: y + 0.82, w: 5.1, h: 0.85,
      fontFace: BODY, fontSize: 12.5, color: MUTE, margin: 0 });
  });

  s.addText(`${F.releases} 个版本全部带发布说明：每一个变动的数字都写明「哪个数变了、为什么」，不悄悄改基准。`,
    { x: M, y: 6.3, w: W - 2 * M, h: 0.5,
      fontFace: HEAD, fontSize: 14.5, bold: true, italic: true, color: TEAL, margin: 0 });
  s.addNotes("单源主导测试是这次审计最重要的方法论产出：比总量的测试看起来覆盖率很高，实际上盲区正好在最要命的地方。");
}

/* ========================= 8. 现状与下一步 ========================= */
{
  const s = pres.addSlide(); darkBg(s);
  s.addText("现状与下一步", {
    x: M, y: 0.45, w: W - 2 * M, h: 0.75,
    fontFace: HEAD, fontSize: 32, bold: true, color: "FFFFFF", margin: 0 });
  s.addText(`v${F.version} 功能完整，可交付内部使用`, {
    x: M, y: 1.2, w: W - 2 * M, h: 0.4,
    fontFace: BODY, fontSize: 14, color: "8FA3B5", margin: 0 });

  s.addText("建议投入方向", {
    x: M, y: 1.95, w: 5.6, h: 0.42,
    fontFace: HEAD, fontSize: 18, bold: true, color: AMBER, margin: 0 });
  const next = [
    ["用实测硅数据校准", "目前对标的是公开论文，不是我们自己的流片。有一颗片子的实测相噪，工具的可信度就从「架构一致」升到「工艺一致」。"],
    ["Verilog-AMS 导出的实机验证", "无免费仿真器可 elaborate，目前只做了文本级交叉引用检查。需要一次 Cadence 上的实跑。"],
    ["Windows 打包路径复核", "打包脚本改动未在 Windows 上实测过。"],
  ];
  let y = 2.5;
  next.forEach(([h, d], i) => {
    dot(s, i + 1, M, y + 0.04, 0.38);
    s.addText(h, { x: M + 0.55, y, w: 5.1, h: 0.38,
      fontFace: HEAD, fontSize: 14.5, bold: true, color: "FFFFFF", margin: 0 });
    s.addText(d, { x: M + 0.55, y: y + 0.42, w: 5.1, h: 0.95,
      fontFace: BODY, fontSize: 12, color: "AEBECC", margin: 0 });
    y += 1.5;
  });

  card(s, M + 6.4, 1.95, 5.5, 2.35, SLATE2);
  s.addText("需要决策的一项", {
    x: M + 6.75, y: 2.18, w: 4.8, h: 0.4,
    fontFace: HEAD, fontSize: 17, bold: true, color: AMBER, margin: 0 });
  s.addText("持续集成单次耗时已达 11 分钟，每次提交跑两个 Python 版本。私有仓库的构建分钟数是计量的。",
    { x: M + 6.75, y: 2.68, w: 4.8, h: 0.9,
      fontFace: BODY, fontSize: 12.5, color: "D7E0E8", margin: 0 });
  s.addText("可选：把耗时最长的 GUI 与导出测试改为仅在主干上运行 —— 但分支上的「按钮一按就崩」正是它们该抓的。",
    { x: M + 6.75, y: 3.5, w: 4.8, h: 0.7,
      fontFace: BODY, fontSize: 12.5, color: "8FA3B5", margin: 0 });

  card(s, M + 6.4, 4.55, 5.5, 2.0, TEAL);
  s.addText("一句话总结", {
    x: M + 6.75, y: 4.78, w: 4.8, h: 0.4,
    fontFace: HEAD, fontSize: 16, bold: true, color: "FFFFFF", margin: 0 });
  s.addText("这套工具最有价值的产出不是那些数字，而是一套让错误数字无处藏身的方法 —— 两个域互相校验，加上不让任何检查空转。",
    { x: M + 6.75, y: 5.25, w: 4.8, h: 1.1,
      fontFace: BODY, fontSize: 13, color: "EAF4F6", margin: 0 });
  s.addNotes("下一步的核心是拿实测硅数据把工具从「架构一致」推到「工艺一致」。CI 成本那一项需要管理层给一个取舍方向。");
}

pres.writeFile({ fileName: "pllsim_report.pptx" }).then(() => console.log("written"));
