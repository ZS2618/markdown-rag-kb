---
name: raw-extract
description: Convert raw PDF, Word, PowerPoint, Excel, CSV, JSON, or text-like source files into raw/extracts/*.extract.md files using only the repository's Python standard-library tooling.
compatibility: opencode
metadata:
  project: markdown-rag-kb
  stage: raw-to-extract
---

## What I Do

Use this skill when raw materials need to become `.extract.md` files before distillation.

Supported first-pass extraction:

- PDF: best-effort text extraction from PDF strings and Flate streams.
- Word: `.docx` via ZIP/XML parsing.
- PowerPoint: `.pptx` via ZIP/XML parsing.
- Excel: `.xlsx` via ZIP/XML parsing.
- CSV/JSON experiment exports: use `python kb.py ingest <file>`.
- Legacy `.doc`, `.ppt`, `.xls`: best-effort printable strings only; prefer converting to modern Office formats first.

## Commands

For a raw literature PDF:

```powershell
python kb.py extract raw/literature/example.pdf --kind literature --title "文献标题"
```

For a group report PPTX:

```powershell
python kb.py extract raw/reports/weekly-report.pptx --kind report --title "小组周报"
```

For an experiment Excel file:

```powershell
python kb.py extract raw/experiments/experiment.xlsx --kind experiment --title "实验记录"
```

For CSV/JSON experiment exports:

```powershell
python kb.py ingest data/sample_experiments.csv
```

## Rules

- Never put raw PDFs, PPTs, Word files, or Excel files directly into `vault/`.
- Keep real raw files under `raw/experiments/`, `raw/literature/`, or `raw/reports/`.
- The output should land under `raw/extracts/<kind>/`.
- After extraction, run `python kb.py distill --force` and `python kb.py index`.
- If extraction is weak or empty, leave the generated `.extract.md` in place and manually improve its `## 提取文本` section.
- Any fallback extraction must surface a `warning:` line in CLI output and preserve the warning in the generated `.extract.md`.
