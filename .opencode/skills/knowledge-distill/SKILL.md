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
- 锂电池体系与研究对象, when the source is battery research
- 材料配方与工艺窗口, when the source is battery research
- 电化学测试条件, when the source is battery research
- 关键性能指标, when the source is battery research
- 失效机制与机理线索, when the source is battery research
- 证据摘要
- 边界与风险
- 下一步建议
- 来源

Literature cards should preserve:

- 研究问题
- 核心方法
- 核心发现
- 锂电材料体系与应用场景, when the source is battery research
- 可复现配方或工艺窗口, when the source is battery research
- 关键性能数据, when the source is battery research
- 机理解释, when the source is battery research
- 证据摘要
- 证据强度判断
- 局限与前提
- 对我们可用的点
- 关键词
- 来源

Report cards should preserve:

- 汇报主题
- 关键决定
- 锂电项目上下文, when the source is battery research
- 数据变化与性能信号, when the source is battery research
- 材料工艺决策点, when the source is battery research
- 待验证机理或风险, when the source is battery research
- 行动项
- 风险与阻塞
- 负责人与截止时间
- 会议结论
- 来源

## Lithium Battery Extraction Focus

For lithium battery research, always preserve exact source-backed details when present:

- Cell chemistry and format: cathode, anode, electrolyte, separator, coin cell, pouch cell, cylindrical cell, N/P ratio.
- Materials and process: synthesis, slurry ratio, solid content, coating, areal loading, calendering, drying, electrolyte volume, formation.
- Test protocol: voltage window, C-rate, cycle count, temperature, rest time, EIS, CV, GITT, safety or abuse-test conditions.
- Performance data: capacity, first-cycle efficiency, coulombic efficiency, retention, rate capability, impedance, gas, swelling, safety signal.
- Mechanism and failure: SEI/CEI, lithium plating, dendrites, cracks, transition-metal dissolution, gas generation, impedance growth.

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
- Any deterministic fallback, heuristic proposal, or placeholder generation must surface a `warning:` line in CLI output.
