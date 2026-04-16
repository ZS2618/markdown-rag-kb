# Agent Configuration Guide

这份文档是给 AI agent 看的。目标是让 agent 在用户要求“配置本项目”“接本地 AI”“接 embedding”“修复配置问题”时，可以自主完成检查、配置、验证和报告。

## 核心原则

- 不联网，除非用户明确允许且公司环境允许。
- 不把 `.env`、模型文件、venv、node_modules、raw 原始材料、测试 extract、测试 vault 卡提交到 Git。
- 问答、蒸馏、内容 proposal 必须使用本地 AI；不能用规则 fallback 冒充 AI 结果。
- Markdown `vault/` 是事实库；SQLite 和 embedding 是派生索引，可重建。
- 如果某一步失败，要报告具体失败点、保留关键 stdout/stderr 摘要，并给出下一步修复命令。

## 配置入口

优先使用项目自带脚本:

```powershell
python tools/setup_embedding.py --backend flagembedding --model-path models\bge-m3
```

常用后端:

```text
flagembedding          推荐。适合 BGE-M3, 中英混合和长文本。
sentence-transformers  通用。适合 sentence-transformers 格式模型。
node                   Node + Transformers.js, 需要本地 ONNX/Transformers.js 模型目录。
```

如果模型文件尚未放好, 只先写 `.env`:

```powershell
python tools/setup_embedding.py --backend flagembedding --model-path models\bge-m3 --skip-smoke-test
```

如果公司使用内网 pip 镜像:

```powershell
python tools/setup_embedding.py --backend flagembedding --model-path models\bge-m3 --pip-index-url http://pypi.company/simple
```

如果公司使用离线 wheel 目录:

```powershell
python tools/setup_embedding.py --backend flagembedding --model-path models\bge-m3 --offline-wheel-dir D:\wheels
```

Node 路线:

```powershell
python tools/setup_embedding.py --backend node --model-path models\bge-small-zh-v1.5
```

## Agent 决策流程

1. 读取当前状态:

```powershell
python kb.py --help
python tools/setup_embedding.py --help
git status --short --branch
```

2. 判断用户是否已经提供模型路径。

- 如果提供了模型路径, 使用该路径。
- 如果未提供, 默认 `models\bge-m3` 和 `--backend flagembedding`。
- 如果模型路径不存在, 运行配置时加 `--skip-smoke-test`, 并明确告诉用户需要把模型文件放入该目录。

3. 判断依赖来源。

- 用户给了内网 pip: 使用 `--pip-index-url`。
- 用户给了 wheel 目录: 使用 `--offline-wheel-dir`。
- 用户没有说明: 直接运行默认命令；如果 pip 失败, 报告需要内网镜像或 wheel 包。

4. 写入 `.env` 后做验证。

```powershell
python kb.py index
python kb.py embed-index
python kb.py semantic-search "EIS 阻抗增长和 SEI 的关系"
```

5. 如果本地 AI 也需要验证:

```powershell
python kb.py ask "资料中有没有关于阻抗增长的结论"
```

`ask` 失败且报 `AI is required` 时, 说明 chat AI 没配好。不要回退成检索结果。

## `.env` 必备字段

本地 chat AI:

```env
LOCAL_OPENAI_BASE_URL=http://127.0.0.1:8000/v1
LOCAL_OPENAI_API_KEY=
LOCAL_OPENAI_CHAT_MODEL=local-chat-model
```

本地 embedding 命令:

```env
LOCAL_EMBEDDING_CMD=.venv-embed\Scripts\python tools\embed_flagembedding_bgem3.py
LOCAL_EMBEDDING_MODEL_PATH=models\bge-m3
LOCAL_EMBEDDING_BATCH_SIZE=8
LOCAL_EMBEDDING_MAX_SEQ_LENGTH=8192
LOCAL_EMBEDDING_USE_FP16=false
LOCAL_EMBEDDING_LOCAL_FILES_ONLY=true
LOCAL_EMBEDDING_NORMALIZE=true
```

PDF 提取:

```env
PDF_EXTRACTOR=auto
PDF_EXTRACT_TIMEOUT=300
PDF_MIN_TEXT_CHARS=80
```

如果公司批准 Docling、Marker 或 OCR 命令:

```env
PDF_EXTRACTOR=command
PDF_EXTRACTOR_CMD=python tools\pdf_to_text.py {input}
```

## 验证标准

配置成功至少满足:

- `python tools/setup_embedding.py ...` 退出码为 0。
- `.env` 存在且包含 `LOCAL_EMBEDDING_CMD`。
- `python kb.py index` 成功。
- `python kb.py embed-index` 成功或明确说明模型文件尚未就位。
- `python kb.py semantic-search "EIS 阻抗增长和 SEI 的关系"` 能返回结果。
- 如果验证 chat AI, `python kb.py ask ...` 必须调用 AI 成功；不能只返回检索 fallback。

## 常见失败和处理

`Model path is missing`
: 模型目录不存在。让用户或 IT 把模型拷贝到 `LOCAL_EMBEDDING_MODEL_PATH`, 或先用 `--skip-smoke-test` 写配置。

`pip install` 失败
: 询问或使用公司内网 pip 镜像 `--pip-index-url`, 或离线 wheel 目录 `--offline-wheel-dir`。不要擅自切换公网源。

`Node executable not found`
: Node 后端不可用。改用 Python 后端, 或让用户安装/暴露 node 和 npm。

`LOCAL_EMBEDDING_CMD returned invalid JSON`
: 本地 embedding 命令 stdout 混入日志。要求脚本只把 JSON 写 stdout, 其他日志写 stderr。

`No embeddings found for model`
: 改过模型路径或命令后, 运行 `python kb.py embed-index --force`。

`AI is required for this command`
: chat AI 没配置或不可达。检查 `LOCAL_OPENAI_BASE_URL`, `LOCAL_OPENAI_CHAT_MODEL`, API key 和内网服务状态。不要生成 fallback 答案。

PDF 抽取乱码或过短
: 设置 `PDF_EXTRACTOR=pdfplumber,pdfminer,pypdf,pdftotext` 或接 `PDF_EXTRACTOR=command`。扫描件需要 OCR。

## Git 安全

配置任务完成后, agent 应检查:

```powershell
git status --short
```

可以提交的通常是:

- `kb.py`
- `README.md`
- `crashcourse.md`
- `AGENTS.md`
- `.env.example`
- `.gitignore`
- `docs/*.md`
- `tools/*.py`
- `tools/*.mjs`
- `requirements-embedding-*.txt`
- `.opencode/agents/*.md`
- `.opencode/skills/*.md`
- `opencode.json`

不能提交:

- `.env`
- `.venv-embed/`
- `models/`
- `node_modules/`
- `index/*.sqlite`
- `raw/experiments/*`
- `raw/literature/*`
- `raw/reports/*`
- 测试生成的 `raw/extracts/**/*.extract.md`
- 未经用户明确确认的 `vault/**/*.md` 内容改动

如果工作区混有测试 raw/vault 文件, 只 stage 明确属于配置能力的文件。

## Agent 最终汇报模板

配置成功时:

```text
已完成本地 embedding 配置。
- 后端: flagembedding
- 模型路径: models\bge-m3
- .env 已写入 LOCAL_EMBEDDING_CMD
- 验证: embed-index 通过, semantic-search 有结果
- 未提交/未修改: raw、vault、models、.env
```

配置未完全成功时:

```text
配置已写入, 但验证未完成。
- 阻塞点: 模型目录 models\bge-m3 不存在
- 已完成: .env 写入, venv 创建, 依赖安装
- 下一步: 将 BGE-M3 模型文件拷贝到 models\bge-m3, 然后运行 python kb.py embed-index
```
