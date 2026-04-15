# 离线 Markdown 知识库 + 本地 RAG MVP

这是一个 Windows 优先、零第三方 Python 依赖的离线知识库原型。原始文件放在 `raw/`，只有经过蒸馏并结构化的 Markdown 才进入 `vault/`，SQLite FTS5 是可重建索引，本地 AI 只作为可选增强。

## 快速开始

在 PowerShell 中进入项目目录后运行：

```powershell
python kb.py demo
```

这会创建 `raw/`、`vault/`、`data/`、`index/` 目录，导入样例实验摘录，蒸馏成结构化知识卡，重建索引，并执行一次“催化剂”检索。

## 常用命令

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

`ask` 会先做本地检索，再尝试调用公司内网 OpenAI 兼容接口。如果没有配置 AI，它会自动降级为检索结果，不会联网。
`extract` 会把 PDF、PPTX、DOCX、XLSX 或文本类原始文件转成 `raw/extracts/**/*.extract.md`。
`distill` 会读取 `raw/extracts/` 里的文本摘录，把实验、文献和小组汇报压缩成可检索的结构化知识卡，并写入 `vault/`。
如果你后来接入了本地 AI, 可以用 `python kb.py distill --force` 重新生成已有知识卡。

## OpenCode Agent

本项目已经包含 OpenCode 项目级配置:

```text
opencode.json
.opencode/agents/kb-curator.md
.opencode/skills/raw-extract/SKILL.md
.opencode/skills/knowledge-distill/SKILL.md
```

建议在 OpenCode 中使用 `kb-curator` agent。它会遵守 raw/vault 分层规则: 原始文件只进 `raw/`, 摘录只进 `raw/extracts/`, 结构化知识卡才进 `vault/`。

## 本地 AI 配置

如果公司提供的是 OpenAI 兼容接口，在 PowerShell 中设置：

```powershell
$env:LOCAL_OPENAI_BASE_URL="http://127.0.0.1:8000/v1"
$env:LOCAL_OPENAI_API_KEY="local-key-if-required"
$env:LOCAL_OPENAI_CHAT_MODEL="local-model-name"
python kb.py ask "催化剂实验结论是什么"
```

`LOCAL_OPENAI_API_KEY` 可以为空；有些内网模型不要求密钥。

## 数据导入

第一版支持 CSV 和 JSON。CSV 每一行会先生成一篇 `raw/extracts/experiments/*.extract.md`，它还不是正式知识库内容。系统优先识别这些字段：

```text
id, title, summary, result, conclusion, date, source_id, source_system, tags, status
```

其他字段会写入摘录 Markdown 的“原始字段”表格。导入文件路径和 SHA256 会写入 frontmatter，方便审计。

JSON 支持对象数组：

```json
[
  {
    "id": "EXP-2026-0001",
    "title": "催化剂 A 条件筛选",
    "summary": "实验摘要",
    "result": "关键观察",
    "conclusion": "结论"
  }
]
```

也支持 `{ "experiments": [...] }`。

## 原始文件提取

第一版坚持零第三方依赖, 所以提取能力是保守的:

- `.docx`: 读取 Word ZIP/XML 文本
- `.pptx`: 读取 PowerPoint ZIP/XML 幻灯片文本
- `.xlsx`: 读取 Excel ZIP/XML 单元格文本
- `.pdf`: 尽力读取 PDF 字符串和 Flate 压缩流; 扫描版 PDF 需要外部 OCR
- `.doc`、`.ppt`、`.xls`: 只能做可打印字符串兜底; 推荐先转成现代 Office 格式

示例:

```powershell
python kb.py extract raw/literature/paper.pdf --kind literature --title "论文标题"
python kb.py extract raw/reports/weekly.pptx --kind report --title "小组周报"
python kb.py extract raw/experiments/run.xlsx --kind experiment --title "实验记录"
python kb.py distill --force
python kb.py index
```

## 知识库约定

原始文件放在：

```text
raw/experiments/    Excel、PPT、原始导出等实验材料
raw/literature/     PDF 文献
raw/reports/        PDF、PPT 等小组汇报
raw/extracts/       从原始文件摘出的文本, 用于蒸馏
```

正式知识库只放结构化 Markdown：

```text
vault/experiments/
vault/literature/
vault/reports/
vault/concepts/
```

AI 生成的新知识建议只会写到：

```text
vault/proposals/
```

`propose` 不会自动修改正式 Markdown。人工审核通过后，再手动把建议整理到正式知识库。

## 知识蒸馏模板

系统默认按三类模板提取精华:

- 实验: 一句话结论、可复用规则、关键条件、证据摘要、边界与风险、下一步建议
- 文献: 研究问题、核心方法、核心发现、证据摘要、证据强度判断、局限与前提、对我们可用的点、关键词
- 小组汇报: 汇报主题、关键决定、行动项、风险与阻塞、负责人与截止时间、会议结论

如果原文是锂电池研究, 蒸馏会自动增加行业字段:

- 实验: 锂电池体系与研究对象、材料配方与工艺窗口、电化学测试条件、关键性能指标、失效机制与机理线索
- 文献: 锂电材料体系与应用场景、可复现配方或工艺窗口、关键性能数据、机理解释
- 小组汇报: 锂电项目上下文、数据变化与性能信号、材料工艺决策点、待验证机理或风险

这些字段优先保留可追溯的具体数值和条件, 例如正负极体系、电解液、隔膜、面密度、压实密度、电压窗口、倍率、温度、容量、库伦效率、循环保持率、EIS/CV/GITT、产气/膨胀、安全信号和 SEI/CEI/析锂等失效线索。

蒸馏卡保留 raw 来源路径和摘录哈希, 便于追溯原文。

## 设计边界

- 不使用第三方 Python 包，不依赖 pip、make、bash 或外网。
- 不引入 LangChain、FAISS、FastAPI、PyYAML 或前端框架。
- SQLite 索引是派生缓存，可以删除后用 `python kb.py index` 重建。
- 第一版保留 `acl` 字段，但不做强制权限过滤。
