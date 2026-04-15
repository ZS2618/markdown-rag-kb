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
python kb.py sync
python kb.py update-proposals
python kb.py links
python kb.py apply-proposal vault/proposals/PROP-xxx.md
```

`ask` 会先做本地检索，再尝试调用公司内网 OpenAI 兼容接口。如果没有配置 AI，它会自动降级为检索结果，不会联网。
`extract` 会把 PDF、PPTX、DOCX、XLSX 或文本类原始文件转成 `raw/extracts/**/*.extract.md`。
`distill` 会读取 `raw/extracts/` 里的文本摘录，把实验、文献和小组汇报压缩成可检索的结构化知识卡，并写入 `vault/`。
如果你后来接入了本地 AI, 可以用 `python kb.py distill --force` 重新生成已有知识卡。

`sync`、`update-proposals`、`links`、`apply-proposal` 是增量演化命令。它们不会让 AI 或规则直接改正式库, 而是先生成 `vault/proposals/` 草案, 人工确认后再应用。

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
- `.pdf`: 尽力读取 PDF 文本流、ToUnicode 字体映射和 Flate 压缩流; 仍需人工复核自定义字体空格、页眉页脚、广告链接和扫描页
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

## 增量更新和知识演化

全量索引用 `python kb.py index` 重建, 但 `vault/` 本身的增量演化使用 proposal 流程:

```text
raw/extracts/*.extract.md
  -> python kb.py sync
  -> python kb.py update-proposals
  -> 人工审核 vault/proposals/*.md
  -> python kb.py apply-proposal vault/proposals/PROP-xxx.md
  -> python kb.py index
```

### 1. 查看 raw 和 vault 是否同步

```powershell
python kb.py sync
```

输出会列出:

- `new extracts`: 有新的 `raw/extracts/**/*.extract.md`, 但还没有对应 vault 卡
- `changed extracts`: raw 摘录哈希变了, 对应 vault 卡需要更新
- `unchanged extracts`: raw 摘录和 vault 卡的 `source_sha256` 一致
- `stale vault cards`: vault 卡记录的来源 extract 不存在, 需要人工判断保留、迁移或废弃
- `Possible related cards`: 新内容和旧 vault 卡的候选关联数量

### 2. 为新增和变更生成更新草案

```powershell
python kb.py update-proposals
```

它会为新增或变更的 extract 生成 `vault/proposals/PROP-ADD-*.md` 或 `vault/proposals/PROP-UPDATE-*.md`。

proposal 里包含:

- 为什么建议新增或更新
- 目标 vault 路径
- 来源 extract 路径和 SHA256
- 候选关联旧卡
- 完整的建议 Markdown, 包在 `BEGIN_PROPOSED_MARKDOWN` 和 `END_PROPOSED_MARKDOWN` 之间

不会自动改 `vault/experiments/`、`vault/literature/` 或 `vault/reports/`。

### 3. 为旧卡之间生成关联草案

```powershell
python kb.py links
```

`links` 会扫描现有 vault 卡, 用标题、标签、正文关键词和锂电池术语做规则匹配, 生成 `PROP-LINK-*.md`。它适合在批量导入文献后运行, 用来发现“同一材料体系”“同一测试方法”“同一失效机理”等候选关系。

可调参数:

```powershell
python kb.py links --min-score 6 --limit 20
```

分数越高越保守。`limit` 控制最多生成多少个关联 proposal。

### 4. 人工审核后应用 proposal

```powershell
python kb.py apply-proposal vault/proposals/PROP-ADD-xxxx.md
python kb.py apply-proposal vault/proposals/PROP-UPDATE-xxxx.md
python kb.py apply-proposal vault/proposals/PROP-LINK-xxxx.md
```

`apply-proposal` 只处理已经存在的 proposal 文件:

- `add`: 写入新的 vault 卡
- `update`: 覆盖目标 vault 卡为 proposal 中审核过的建议 Markdown
- `link`: 给目标 vault 卡 frontmatter 的 `related` 增加关联 ID, 并在正文追加 `## 关联知识`

应用后 proposal 的 `status` 会改成 `applied`, 并写入 `applied_at`。

### 5. vault 关系字段

新生成的知识卡会保留这些关系字段:

```yaml
supersedes: []
supports: []
contradicts: []
related: []
derived_from: [raw/extracts/...]
version: 1
review_status: structured-draft
```

含义:

- `supersedes`: 替代哪些旧结论
- `supports`: 支持哪些旧结论
- `contradicts`: 和哪些旧结论冲突
- `related`: 普通相关
- `derived_from`: 来源 extract
- `version`: 卡片版本, update proposal 会递增
- `review_status`: 人工审核状态

注意: 第一版 `supports/contradicts/supersedes` 不自动判定, 只自动生成 `related` 候选。涉及支持、反驳、替代的判断需要人工在 proposal 或 vault 卡里明确编辑。

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

所有回退路径都会输出 `warning:`。例如 PDF/旧 Office 弱抽取、未知文件类型、CSV 缺字段补 `待补充`、缺 ID 生成稳定哈希、FTS5 未命中后使用 LIKE 检索、未配置本地 AI 时使用规则蒸馏或规则 proposal，都会在命令行明确提示。

## 设计边界

- 不使用第三方 Python 包，不依赖 pip、make、bash 或外网。
- 不引入 LangChain、FAISS、FastAPI、PyYAML 或前端框架。
- SQLite 索引是派生缓存，可以删除后用 `python kb.py index` 重建。
- 第一版保留 `acl` 字段，但不做强制权限过滤。
