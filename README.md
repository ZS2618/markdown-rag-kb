# 离线 Markdown 知识库 + 本地 RAG MVP

这是一个 Windows 优先、离线优先的 Markdown 知识库原型。原始文件放在 `raw/`，只有经过 AI 蒸馏并结构化的 Markdown 才进入 `vault/`，SQLite FTS5 是可重建索引，semantic embedding 可作为本地增强索引。问答、蒸馏和内容 proposal 必须调用公司内网 AI；没有 AI 配置时会直接报错，不做规则回退。

## 快速开始

在 PowerShell 中进入项目目录后，先复制 `.env.example` 为 `.env`，填入公司内网 OpenAI 兼容接口：

```powershell
copy .env.example .env
notepad .env
python kb.py demo
```

这会创建 `raw/`、`vault/`、`data/`、`index/` 目录，导入样例实验摘录，蒸馏成结构化知识卡，重建索引，并执行一次“催化剂”检索。

## 常用命令

```powershell
python kb.py init
python kb.py extract raw/literature/example.pdf --kind literature --title "文献标题"
python kb.py ingest data/sample_experiments.csv
python kb.py index
python kb.py embed-index
python kb.py search "催化剂"
python kb.py semantic-search "高镍正极循环衰减"
python kb.py ask "催化剂 A 的推荐条件是什么"
python kb.py propose
python kb.py distill
python kb.py sync
python kb.py update-proposals
python kb.py links
python kb.py apply-proposal vault/proposals/PROP-xxx.md
```

`ask` 会先做本地检索，再调用公司内网 OpenAI 兼容接口生成带来源的回答。如果没有配置 AI，它会报错并停止，不会联网，也不会回退成纯检索答案。
`extract` 会把 PDF、PPTX、DOCX、XLSX 或文本类原始文件转成 `raw/extracts/**/*.extract.md`。
`distill` 会读取 `raw/extracts/` 里的文本摘录，必须调用本地 AI 把实验、文献和小组汇报压缩成可检索的结构化知识卡，并写入 `vault/`。
`embed-index` 会调用本地 embedding 服务或本地 embedding 命令，生成语义检索索引。

`sync`、`update-proposals`、`links`、`apply-proposal` 是增量演化命令。它们不会让 AI 或规则直接改正式库, 而是先生成 `vault/proposals/` 草案, 人工确认后再应用。

## OpenCode Agent

本项目已经包含 OpenCode 项目级配置:

```text
opencode.json
.opencode/agents/kb-curator.md
.opencode/agents/kb-orchestrator.md
.opencode/agents/kb-raw-intake.md
.opencode/agents/kb-distiller.md
.opencode/agents/kb-linker.md
.opencode/agents/kb-auditor.md
.opencode/skills/raw-extract/SKILL.md
.opencode/skills/knowledge-distill/SKILL.md
.opencode/skills/vault-evolve/SKILL.md
```

建议在 OpenCode 中使用 `kb-orchestrator` agent。它是主协调者, 负责把任务分给专职 agent:

- `kb-raw-intake`: 原始文件抽取、CSV/JSON 导入、抽取 warning 检查
- `kb-distiller`: 结构化蒸馏、锂电池模板、add/update proposal
- `kb-linker`: 新旧知识关联、link proposal
- `kb-auditor`: 来源、warning、proposal、索引和检索验证
- `kb-curator`: 兼容保留的单 agent 模式, 适合简单任务

这套结构参考了 Oh My OpenCode/OpenAgent 的“主协调者 + 专职 subagent”思路, 但压缩成适合本项目的 lite 架构。核心规则不变: 原始文件只进 `raw/`, 摘录只进 `raw/extracts/`, 正式结构化知识卡才进 `vault/`, 增量修改必须先进入 `vault/proposals/`。

## 本地 AI 配置

推荐把配置写在项目根目录 `.env`，`kb.py` 会自动加载这个文件，且 `.env` 已被 `.gitignore` 忽略：

```env
LOCAL_OPENAI_BASE_URL=http://127.0.0.1:8000/v1
LOCAL_OPENAI_API_KEY=
LOCAL_OPENAI_CHAT_MODEL=local-chat-model
LOCAL_OPENAI_EMBEDDING_MODEL=local-embedding-model
PDF_EXTRACTOR=auto
```

如果公司更习惯 PowerShell 临时变量，也可以这样设置：

```powershell
$env:LOCAL_OPENAI_BASE_URL="http://127.0.0.1:8000/v1"
$env:LOCAL_OPENAI_API_KEY="local-key-if-required"
$env:LOCAL_OPENAI_CHAT_MODEL="local-model-name"
python kb.py ask "催化剂实验结论是什么"
```

`LOCAL_OPENAI_API_KEY` 可以为空；有些内网模型不要求密钥。

问答、蒸馏、`propose` 和 `update-proposals` 中的内容生成都要求 AI 可用。`sync`、`links`、`index`、`search` 仍是本地规则/索引命令。

## 本地 Embedding

FTS5 适合精确关键词，但对同义词、跨语言、术语变体不够强。可以增加本地 embedding 索引：

```powershell
python tools/setup_embedding.py --backend flagembedding --model-path models\bge-m3
python kb.py index
python kb.py embed-index
python kb.py semantic-search "电解液添加剂改善高温循环"
```

两种接法：

- OpenAI 兼容 `/embeddings`: 设置 `LOCAL_OPENAI_EMBEDDING_MODEL`，默认复用 `LOCAL_OPENAI_BASE_URL`。
- 本地命令: 设置 `LOCAL_EMBEDDING_CMD`，命令从 stdin 读取 `{"input": ["文本1", "文本2"]}`，向 stdout 输出向量数组或 OpenAI 风格 `{"data":[{"embedding":[...]}]}`。项目已提供三种适配脚本:

```powershell
python tools/embed_flagembedding_bgem3.py
python tools/embed_sentence_transformers.py
node tools/embed_transformersjs.mjs
```

办公室如果能批准模型文件，优先考虑多语言/中英混合 embedding，例如 BGE-M3 或 bge-large-zh-v1.5。Python 路线常见是 `sentence-transformers`，Node 路线可用 Transformers.js；本项目通过 OpenAI 兼容服务或 `LOCAL_EMBEDDING_CMD` 接入，避免把主程序绑定到某个包。

本地 embedding 的安装和 `.env` 配置见 `docs/local_embedding_setup.md`。PDF 和 embedding 的离线工具选型见 `docs/offline_pdf_embedding_options.md`。

## 如何引导 Agent 配置

在 OpenCode 里优先选择 `kb-orchestrator`, 并明确要求它使用 `local-config` skill。最稳的提示词是:

```text
请使用 local-config skill，先阅读 docs/agent_configuration_guide.md。
目标：配置本项目在办公室电脑上的本地 AI 和本地 embedding。

要求：
1. 不联网，除非我明确允许。
2. 不要提交 .env、models、.venv-embed、node_modules、raw、vault、index 文件。
3. embedding 默认使用 FlagEmbedding + BGE-M3。
4. 模型路径使用 models/bge-m3。
5. 如果模型目录不存在，运行 setup_embedding.py 时加 --skip-smoke-test，只写好配置并告诉我需要拷贝模型。
6. 如果 pip 安装失败，不要换公网源，告诉我需要内网 pip 镜像或离线 wheel 目录。
7. 配置后运行可执行的验证：python kb.py --help、python tools/setup_embedding.py --help、python kb.py index。
8. 如果 embedding 已可用，再运行 python kb.py embed-index 和 semantic-search。
9. 最后用清单告诉我：已完成、未完成、阻塞点、下一步命令。
```

如果公司有内网 pip 镜像, 可以让 agent 使用:

```text
请使用 local-config skill，先阅读 docs/agent_configuration_guide.md。
用 FlagEmbedding + BGE-M3 配置本地 embedding：
python tools/setup_embedding.py --backend flagembedding --model-path models/bge-m3 --pip-index-url http://你的内网pypi/simple
配置完成后运行 python kb.py index、python kb.py embed-index 和一次 semantic-search。
不要提交 .env、models、raw、vault、node_modules 或 index 文件。
```

如果公司使用离线 wheel 包:

```text
请使用 local-config skill，按 docs/agent_configuration_guide.md 配置本地 embedding。
后端使用 flagembedding，模型路径 models/bge-m3，Python 依赖从 D:\wheels 安装：
--offline-wheel-dir D:\wheels
如果模型或依赖缺失，停止并明确告诉我缺什么，不要尝试公网下载。
```

如果要走 Node + Transformers.js:

```text
请使用 local-config skill，按 docs/agent_configuration_guide.md 配置 Node + Transformers.js embedding。
模型目录是 models/bge-small-zh-v1.5。
运行 python tools/setup_embedding.py --backend node --model-path models/bge-small-zh-v1.5。
配置后验证 embed-index 和 semantic-search。
不要提交 .env、models、node_modules、package.json、package-lock.json、raw、vault 或 index 文件。
```

配置完成后可以让 agent 做一次审计:

```text
现在根据 docs/agent_configuration_guide.md 做一次配置审计。
检查 .env 是否有 LOCAL_EMBEDDING_CMD，运行 index、embed-index、semantic-search。
如果失败，只报告原因和修复命令，不要改 raw/vault。
```

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

主程序仍用 Python 标准库实现 CLI 和索引，但 PDF 提取允许调用办公室已经安装或批准的本地工具。默认 `PDF_EXTRACTOR=auto` 会按顺序尝试:

```text
pdfplumber -> pdfminer -> pypdf -> pdftotext
```

- `.docx`: 读取 Word ZIP/XML 文本
- `.pptx`: 读取 PowerPoint ZIP/XML 幻灯片文本
- `.xlsx`: 读取 Excel ZIP/XML 单元格文本
- `.pdf`: 优先用 `pdfplumber`/`pdfminer`/`pypdf`/`pdftotext`；如需接 Docling、Marker 或公司 OCR，可以设置 `PDF_EXTRACTOR=command` 和 `PDF_EXTRACTOR_CMD`
- `.doc`、`.ppt`、`.xls`: 只能做可打印字符串兜底; 推荐先转成现代 Office 格式

如果所有 PDF 后端都失败或文本过短，命令会报错停止，不会把乱码强行写入 extract。扫描版 PDF 仍需要 OCR 或 Docling/Marker 这类更重的离线工具。

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

它会为新增或变更的 extract 生成 `vault/proposals/PROP-ADD-*.md` 或 `vault/proposals/PROP-UPDATE-*.md`。建议写入内容必须由本地 AI 生成；没有 AI 时命令会失败。

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

所有保留的弱路径都会输出 `warning:`，例如旧 Office/未知文件类型的 printable-string 提取、CSV 缺字段补 `待补充`、缺 ID 生成稳定哈希、FTS5 未命中后使用 LIKE 检索。问答、蒸馏和内容 proposal 没有规则回退；AI 不可用时直接报错。

## 设计边界

- 主程序不依赖 LangChain、FAISS、FastAPI、PyYAML 或前端框架；PDF/embedding 可通过公司批准的本地包、命令或服务外挂。
- SQLite 索引是派生缓存，可以删除后用 `python kb.py index` 重建。
- 第一版保留 `acl` 字段，但不做强制权限过滤。
