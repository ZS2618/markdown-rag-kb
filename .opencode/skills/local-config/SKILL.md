---
name: local-config
description: Configure local AI, PDF extraction, and local embedding backends for this offline knowledge-base project, with safe validation and no raw/model commits.
compatibility: opencode
metadata:
  project: markdown-rag-kb
  stage: local-configuration
---

## What I Do

Use this skill when the user asks to configure the project, local AI, local embedding, PDF extraction, or office-machine setup.

Primary guide:

```text
docs/agent_configuration_guide.md
```

## Default Embedding Setup

Prefer FlagEmbedding + BGE-M3 unless the user requests another backend:

```powershell
python tools/setup_embedding.py --backend flagembedding --model-path models\bge-m3
```

If model files are not present yet:

```powershell
python tools/setup_embedding.py --backend flagembedding --model-path models\bge-m3 --skip-smoke-test
```

## Validation

Run the smallest useful checks:

```powershell
python3 -m py_compile kb.py tools/setup_embedding.py tools/embed_sentence_transformers.py tools/embed_flagembedding_bgem3.py
python kb.py index
python kb.py embed-index
python kb.py semantic-search "EIS 阻抗增长和 SEI 的关系"
```

## Rules

- Read `docs/agent_configuration_guide.md` before changing configuration.
- Do not print secrets from `.env`.
- Do not commit `.env`, `.venv-embed/`, `models/`, `node_modules/`, SQLite indexes, raw files, or generated test vault cards.
- If local AI is unavailable, stop and report the `.env`/service error; do not create fallback answers or distilled cards.
- If dependency installation fails, report whether it needs an intranet pip mirror, offline wheel directory, npm cache, or model files.
- Keep stdout of embedding adapter commands valid JSON; send logs to stderr.
