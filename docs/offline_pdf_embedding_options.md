# Offline PDF And Embedding Options

这份说明用于软件审核和办公电脑部署选型。主程序 `kb.py` 不把第三方包写死进依赖, 但可以通过 `.env` 挂载公司批准的离线 PDF 工具和 embedding 模型。

## PDF 提取建议

轻量优先顺序:

1. `pdfplumber`: 适合机器生成 PDF, 可提取文本、字符、线条、矩形和表格信息。项目地址: <https://github.com/jsvine/pdfplumber>
2. `pdfminer.six`: 纯 Python 路线常用工具, 官方文档提供 `extract_text` 高层接口。项目文档: <https://pdfminersix.readthedocs.io/>
3. `pypdf`: 简单、轻量, 适合先尝试普通文本 PDF。
4. `pdftotext`: Poppler 命令行工具, 如果 IT 已经装好, 对很多论文 PDF 很稳。

复杂版式和扫描件:

1. Docling: 支持多格式解析、PDF layout/table/formula/OCR, 文档说明可本地运行并适合敏感数据和隔离环境。项目文档: <https://docling-project.github.io/docling/>
2. Marker: 目标是把 PDF 转成 Markdown/JSON, 对论文、表格、公式更友好, 但依赖更重, 适合审核通过后作为外部命令接入。项目地址: <https://github.com/datalab-to/marker>

本项目默认:

```env
PDF_EXTRACTOR=auto
```

会依次尝试 `pdfplumber`, `pdfminer`, `pypdf`, `pdftotext`。如果你们批准了 Docling、Marker 或公司 OCR, 设置:

```env
PDF_EXTRACTOR=command
PDF_EXTRACTOR_CMD=python tools/pdf_to_text.py {input}
```

要求这个命令把提取后的纯文本或 Markdown 输出到 stdout。提取失败时应返回非 0 退出码。

## Embedding 建议

本项目支持两种本地 embedding 接入。

OpenAI 兼容服务:

```env
LOCAL_OPENAI_BASE_URL=http://127.0.0.1:8000/v1
LOCAL_OPENAI_EMBEDDING_MODEL=local-embedding-model
```

本地命令:

```env
LOCAL_EMBEDDING_CMD=python tools/embed_flagembedding_bgem3.py
```

命令从 stdin 读取:

```json
{"input": ["文本1", "文本2"]}
```

stdout 输出以下任意一种:

```json
[[0.1, 0.2], [0.3, 0.4]]
```

```json
{"data": [{"embedding": [0.1, 0.2]}, {"embedding": [0.3, 0.4]}]}
```

模型选型:

- 中英混合、长文档、锂电池文献优先考虑 BGE-M3。模型卡说明它支持多语言、dense/sparse/multi-vector 多种检索形态, 最大长度到 8192 tokens。模型卡: <https://huggingface.co/BAAI/bge-m3>
- Python 办公机如果允许安装包, 可以用 `sentence-transformers` 或 FlagEmbedding 包一层 `LOCAL_EMBEDDING_CMD`。
- Node 办公机如果允许模型文件和 npm 包, 可以用 Transformers.js 包一层 `LOCAL_EMBEDDING_CMD`。Node 服务端教程: <https://huggingface.co/docs/transformers.js/tutorials/node>

本项目已提供这些命令适配脚本:

- `tools/embed_flagembedding_bgem3.py`
- `tools/embed_sentence_transformers.py`
- `tools/embed_transformersjs.mjs`

详细安装步骤见 `docs/local_embedding_setup.md`。

## 推荐落地路径

第一阶段:

1. `.env` 配好本地 chat AI。
2. PDF 先用 `PDF_EXTRACTOR=auto`。
3. 关键词检索用 `python kb.py search`。

第二阶段:

1. IT 审核通过 `pdfplumber/pdfminer/pypdf` 环境。
2. 接入公司 embedding 服务或 `LOCAL_EMBEDDING_CMD`。
3. 跑 `python kb.py embed-index` 和 `python kb.py semantic-search`。

第三阶段:

1. 对扫描件、复杂表格和公式, 审核 Docling 或 Marker。
2. 通过 `PDF_EXTRACTOR_CMD` 接入, 保持 raw/extract/vault 流程不变。
