# Agent Guide

This repository is an offline Markdown knowledge-base MVP.

## Core Rule

Only distilled, structured Markdown belongs in `vault/`.

Raw files and text extracts belong in `raw/`:

```text
raw/experiments/      Excel, PPT, instrument exports, experiment system exports
raw/literature/       PDF papers
raw/reports/          PDF, PPT, and meeting/report materials
raw/extracts/         Text extracts produced from raw files
vault/                Structured knowledge cards only
```

## Preferred Workflow

1. Put original files under `raw/experiments/`, `raw/literature/`, or `raw/reports/`.
2. Run `python kb.py extract <raw-file> --kind <experiment|literature|report>`.
3. Manually improve weak `.extract.md` files when extraction is incomplete.
4. Run `python kb.py distill --force`.
5. Run `python kb.py index`.
6. Verify with `python kb.py search "<keyword>"`.

CSV/JSON experiment exports can use:

```powershell
python kb.py ingest data/sample_experiments.csv
```

## Safety

- Do not commit real internal raw files. They are ignored by `.gitignore`.
- Do not put unstructured source material directly into `vault/`.
- Do not invent facts during distillation.
- Keep source paths and hashes in frontmatter for traceability.
- For lithium battery materials, preserve exact source-backed cell chemistry, electrode/electrolyte/separator details, process window, test protocol, performance metrics, and failure-mechanism clues.
- `index/kb.sqlite` is a rebuildable cache.

## OpenCode

Use the project agent `kb-curator`.

Project skills:

- `raw-extract`: convert raw files into `.extract.md`.
- `knowledge-distill`: convert extracts into structured `vault/` cards.
