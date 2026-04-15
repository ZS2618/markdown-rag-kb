---
name: knowledge-distill
description: Distill raw/extracts/*.extract.md files into structured Markdown knowledge cards in vault/ using the project's experiment, literature, and report templates.
compatibility: opencode
metadata:
  project: markdown-rag-kb
  stage: extract-to-vault
---

## What I Do

Use this skill after raw materials have been converted into `.extract.md` files.

This project only indexes `vault/`. `raw/extracts/` is source evidence for distillation, not the searchable knowledge base.

## Distillation Templates

Experiment cards should preserve:

- 一句话结论
- 可复用规则
- 关键条件
- 证据摘要
- 边界与风险
- 下一步建议
- 来源

Literature cards should preserve:

- 研究问题
- 核心方法
- 核心发现
- 证据摘要
- 证据强度判断
- 局限与前提
- 对我们可用的点
- 关键词
- 来源

Report cards should preserve:

- 汇报主题
- 关键决定
- 行动项
- 风险与阻塞
- 负责人与截止时间
- 会议结论
- 来源

## Commands

```powershell
python kb.py distill --force
python kb.py index
python kb.py search "关键词"
```

## Rules

- Distill only from `raw/extracts/**/*.extract.md`.
- Keep `vault/` structured and concise; do not copy entire raw extracts into `vault/`.
- Every distilled card must keep source metadata in frontmatter.
- If local AI is configured through `LOCAL_OPENAI_BASE_URL`, let it fill templates, but do not accept unsupported claims.
- If local AI is not configured, use the deterministic Python fallback and then refine manually.
