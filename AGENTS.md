# Agent Guide

This repository is an offline Markdown knowledge-base MVP.

Question answering, distillation, and content proposal generation must use the local AI configured in project `.env` or environment variables. Do not create deterministic fallback answers or fallback distilled cards when AI is unavailable.

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
6. Run `python kb.py embed-index` if semantic retrieval is configured.
7. Verify with `python kb.py search "<keyword>"` and optionally `python kb.py semantic-search "<question>"`.
8. For vault evolution, run `python kb.py sync`, then `python kb.py update-proposals` or `python kb.py links`.
9. Apply only reviewed proposals with `python kb.py apply-proposal <proposal>`.

CSV/JSON experiment exports can use:

```powershell
python kb.py ingest data/sample_experiments.csv
```

## Safety

- Do not commit real internal raw files. They are ignored by `.gitignore`.
- Do not put unstructured source material directly into `vault/`.
- Do not invent facts during distillation.
- Stop and report the `.env`/local AI error if AI-required commands cannot call the model.
- Keep source paths and hashes in frontmatter for traceability.
- For lithium battery materials, preserve exact source-backed cell chemistry, electrode/electrolyte/separator details, process window, test protocol, performance metrics, and failure-mechanism clues.
- Do not directly edit formal vault cards for incremental evolution unless applying a reviewed proposal.
- New/update/link proposals must stay in `vault/proposals/` until reviewed.
- `index/kb.sqlite` is a rebuildable cache.
- When no company embedding API exists, use `LOCAL_EMBEDDING_CMD` with one of the scripts under `tools/`.

## OpenCode Agent Architecture

Use `kb-orchestrator` as the primary project agent for multi-step work.

Specialist agents:

- `kb-raw-intake`: raw file extraction, CSV/JSON ingest, extract warnings.
- `kb-distiller`: add/update proposals and lithium-battery distillation quality.
- `kb-linker`: candidate relationships between vault cards.
- `kb-auditor`: provenance, warning, proposal, and final verification checks.
- `kb-curator`: legacy all-in-one curator for simple single-agent sessions.

Project skills:

- `raw-extract`: convert raw files into `.extract.md`.
- `knowledge-distill`: convert extracts into structured `vault/` cards.
- `vault-evolve`: manage `sync`, `update-proposals`, `links`, and `apply-proposal`.

Coordinator pattern:

1. `kb-orchestrator` scopes the task and chooses the specialist path.
2. Specialists produce extracts, proposals, or audit findings.
3. Formal vault changes wait in `vault/proposals/`.
4. `apply-proposal` is used only after human review.
5. `kb-auditor` verifies `python kb.py sync`, `python kb.py index`, and focused search output.
