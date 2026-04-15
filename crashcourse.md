# Crash Course

这是一份上手指南。目标很简单: 你在办公室克隆这个项目后, 按顺序执行下面的命令, 就能把 raw 原始材料、蒸馏结构化知识库、搜索问答和待审核草稿跑起来。

## 先跑起来

在项目目录里打开 PowerShell, 先跑 demo:

```powershell
python kb.py demo
```

这条命令会自动做四件事:

1. 创建 `raw/`、`vault/`、`data/`、`index/` 这些目录
2. 导入样例实验摘录, 并准备文献和汇报摘录
3. 蒸馏出结构化 Markdown 知识卡
4. 重建 SQLite FTS5 索引
5. 做一次“催化剂”搜索, 让你看到结果长什么样

如果这一步成功, 说明你的环境已经可以用了。

## 你会看到什么

跑完后, 项目里会多出这些东西:

```text
raw/experiments/      Excel、PPT、原始导出等实验材料
raw/literature/       PDF 文献
raw/reports/          PDF、PPT 等小组汇报
raw/extracts/         从原始文件摘出的文本
vault/experiments/    蒸馏后的实验知识卡
vault/literature/     蒸馏后的文献知识卡
vault/reports/        蒸馏后的小组汇报知识卡
vault/concepts/       概念类结构化知识
vault/proposals/      待人工审核的草稿
data/                 样例输入
index/kb.sqlite       派生索引, 可以删除后重建
```

原始文件不要直接进知识库。`vault/` 只放蒸馏并结构化后的 Markdown。`index/kb.sqlite` 只是缓存, 不要把它当事实源。

## 最常用的命令

```powershell
python kb.py init
python kb.py extract raw/literature/example.pdf --kind literature --title "文献标题"
python kb.py ingest data/sample_experiments.csv
python kb.py index
python kb.py search "催化剂"
python kb.py ask "催化剂 A 的推荐条件是什么"
python kb.py propose
python kb.py distill
```

每个命令的作用:

`init`
: 初始化目录和空索引。适合第一次克隆后执行。

`ingest`
: 把 CSV 或 JSON 实验数据转成 Markdown。

`extract`
: 把 PDF、PPTX、DOCX、XLSX 或文本类原始文件转成 `raw/extracts/**/*.extract.md`。

`index`
: 扫描 `vault/**/*.md`, 重新建立 SQLite 索引。

`search`
: 只做本地检索, 不调用 AI。

`ask`
: 先检索, 再尝试调用公司内网的 OpenAI 兼容接口。

`propose`
: 生成 `vault/proposals/` 里的待审核草稿, 不会自动改正式知识库。

`distill`
: 读取 `raw/extracts/`, 把实验、文献和小组汇报压缩成可检索的知识卡, 放到 `vault/`。

## 导入数据

第一版支持 CSV 和 JSON。

CSV 示例:

```csv
id,title,summary,result,conclusion,date,source_id,source_system,tags
EXP-2026-0001,催化剂 A 条件筛选,对催化剂 A 在不同温度下进行筛选,80 摄氏度条件下转化率达到 91%,催化剂 A 的推荐初始条件为 80 摄氏度,2026-04-14,LIMS-12345,LIMS,"催化剂, 条件筛选"
```

导入后, 每一行会生成一篇摘录 Markdown, 放在 `raw/extracts/experiments/`。这还不是正式知识库内容。

如果你有自己的导出文件, 直接替换成:

```powershell
python kb.py ingest path\to\your_file.csv
python kb.py distill
python kb.py index
```

## Raw 和 Vault 怎么分工

原始文件放在 `raw/`, 比如:

```text
raw/experiments/    Excel、PPT、仪器导出
raw/literature/     PDF 文献
raw/reports/        PDF、PPT、会议材料
```

因为第一版零第三方依赖, PDF/PPT/Word/Excel 提取是保守能力。你可以先运行内置提取命令:

```powershell
python kb.py extract raw/literature/paper.pdf --kind literature --title "论文标题"
python kb.py extract raw/reports/weekly.pptx --kind report --title "小组周报"
python kb.py extract raw/experiments/run.xlsx --kind experiment --title "实验记录"
```

`.docx/.pptx/.xlsx` 会通过 ZIP/XML 读取文本。PDF 是 best-effort 提取, 扫描版 PDF 需要外部 OCR。旧 `.doc/.ppt/.xls` 建议先转成现代 Office 格式。

你也可以用公司允许的工具或本地 AI 把原始文件摘成文本, 放到 `raw/extracts/`。

摘录文件的最小格式像这样:

```markdown
---
id: EXP-2026-0001
type: raw-extract
raw_kind: experiment
title: 催化剂 A 条件筛选
source_system: LIMS
source_id: LIMS-12345
status: extracted
tags: [催化剂, 条件筛选]
raw_file_path: raw/experiments/EXP-2026-0001.xlsx
updated_at: 2026-04-14
---

# 催化剂 A 条件筛选

## 摘要

## 实验条件

## 关键观察

## 结论
```

`python kb.py distill` 会把这些摘录压缩成 `vault/` 里的结构化知识卡。只有这些卡片会进入检索库。

## 搜索和问答

先做纯检索:

```powershell
python kb.py search "催化剂"
```

如果你想问一句完整的话:

```powershell
python kb.py ask "催化剂实验结论是什么"
```

没有配置本地 AI 时, `ask` 会自动降级为本地检索结果, 不会报错也不会联网。

## 接本地 AI

如果公司提供的是 OpenAI 兼容接口, 在 PowerShell 里设置:

```powershell
$env:LOCAL_OPENAI_BASE_URL="http://127.0.0.1:8000/v1"
$env:LOCAL_OPENAI_API_KEY="local-key-if-required"
$env:LOCAL_OPENAI_CHAT_MODEL="local-model-name"
python kb.py ask "催化剂 A 的推荐条件是什么"
```

只要 base URL 可用, 这个项目就会尝试调用本地模型。

## proposal 是什么

`python kb.py propose` 会把每篇正式文档生成一份待审核草稿, 放到 `vault/proposals/`。

它的用途是:

1. 提醒你哪些文档缺摘要、缺结论、缺标签
2. 让本地 AI 或规则系统先写建议稿
3. 人工确认后再把内容合并回正式 Markdown

第一版不会自动改正式知识库, 这是故意的, 这样更适合有审计要求的环境。

## 知识蒸馏模板

默认有三种提取方式:

1. 实验卡: 一句话结论、可复用规则、关键条件、证据摘要、边界与风险、下一步建议
2. 文献卡: 研究问题、核心方法、核心发现、证据摘要、证据强度判断、局限与前提、对我们可用的点、关键词
3. 汇报卡: 汇报主题、关键决定、行动项、风险与阻塞、负责人与截止时间、会议结论

锂电池资料会自动增加更细的行业字段:

1. 实验卡: 锂电池体系与研究对象、材料配方与工艺窗口、电化学测试条件、关键性能指标、失效机制与机理线索
2. 文献卡: 锂电材料体系与应用场景、可复现配方或工艺窗口、关键性能数据、机理解释
3. 汇报卡: 锂电项目上下文、数据变化与性能信号、材料工艺决策点、待验证机理或风险

录入时尽量保留这些词后面的原始数值: 正极、负极、电解液、隔膜、N/P、面密度、压实、涂布、烘干、化成、电压窗口、倍率、温度、容量、库伦效率、循环保持率、阻抗、EIS、CV、GITT、膨胀、产气、SEI、CEI、析锂。

如果有本地 AI, `distill` 会尽量把这些模板填满；没有 AI 时, 它会用规则和章节提取生成可读版本。无论哪种方式, raw 原始材料都不会直接进入 `vault/`。

如果你先用无 AI 模式生成过一版, 后来接好了本地 AI, 可以运行:

```powershell
python kb.py distill --force
python kb.py index
```

## 一个推荐工作流

如果你今天要真正开始用它, 我建议按这个顺序:

1. `python kb.py init`
2. 把原始 PDF、PPT、Excel 放进 `raw/` 对应目录
3. 用 `python kb.py extract 原始文件 --kind 类型` 生成摘录
4. 把自动提取不准的地方人工补进 `raw/extracts/**/*.extract.md`
5. 如果是 CSV 或 JSON 实验导出, 可以用 `python kb.py ingest 你的文件.csv` 自动生成实验摘录
6. `python kb.py distill`
7. `python kb.py index`
8. `python kb.py search "你关心的关键词"`
9. `python kb.py ask "完整问题"`
10. `python kb.py propose`

## 常见坑

`search` 没结果
: 先确认跑过 `python kb.py index`。如果你改过 Markdown, 也要重新建索引。

`ask` 只返回检索结果
: 说明没有配置 `LOCAL_OPENAI_BASE_URL`, 或者本地 AI 接口不可达。

导入后看不到新内容
: 大概率是你还没执行 `python kb.py distill` 和 `python kb.py index`。

Windows 路径问题
: 尽量在项目根目录里执行命令, 并优先使用相对路径。

## 你真正要记住的一句话

raw 是原始证据, vault 是结构化知识库, SQLite 是索引, AI 只负责辅助蒸馏和提案。
