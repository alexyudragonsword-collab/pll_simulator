# 汇报材料 / Reports

`pllsim-项目总结-v0.9.0.pptx` —— 面向管理层的 8 页中文总结，覆盖工具定位、
文献对标、完备性审计的发现、质量体系与后续投入建议。

生成脚本一并提交，因为幻灯片里的数字（架构数、预设数、测试数、对标表）
会随代码变化，而一个没有源的二进制文件只会悄悄过期。

## 重新生成

```bash
cd docs/reports
npm install pptxgenjs           # 若尚未安装
node build_deck.js              # 产出 pllsim_report.pptx
python qa_deck.py pllsim_report.pptx
```

对标表的数字来自 `pllsim.presets.benchmark_table()`，测试数来自
`pytest --collect-only`；改动代码后请核对这两处再重新生成。

## qa_deck.py 是做什么的

常规做法是把 pptx 转成 PDF 再逐页看图，用来抓文字溢出。本仓库的开发容器里
LibreOffice 无法加载任何 pptx（连空白文件也不行），所以这个脚本做两件事替代：

1. **溢出检测** —— 用真实 CJK 字体度量每个文本框换行后的高度，与它自己的框
   比较。这是渲染预览主要用来抓的那一类缺陷，而度量是它真正的判据。
2. **近似渲染** —— 从图形几何画出每页的位图（`qa-N.png`），用于肉眼检查重叠、
   间距与对齐。

第 2 项是近似而非 PowerPoint 的真实排版，不要用它判断最终外观；第 1 项的
数字则是可信的，因为它拿同一个字号、同一个字符串、同一个框去量。

已知限制：字体写的是 Microsoft YaHei（中文 Windows Office 的标准字体），
其真实渲染宽度无法在本环境验证，各文本框均已留余量。
