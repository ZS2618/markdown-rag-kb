---
name: vault-evolve
description: Manage incremental vault evolution through sync, add/update proposals, link proposals, human review, and apply-proposal.
compatibility: opencode
metadata:
  project: markdown-rag-kb
  stage: vault-evolution
---

## What I Do

Use this skill when knowledge has to evolve after new or changed extracts arrive.

This skill protects the formal knowledge base:

- `sync` diagnoses state.
- `update-proposals` creates AI-generated add/update drafts.
- `links` creates relationship drafts.
- `apply-proposal` writes reviewed proposals into `vault/`.

## Commands

```powershell
python kb.py sync
python kb.py update-proposals --limit 5
python kb.py links --min-score 6 --limit 20
python kb.py apply-proposal vault/proposals/PROP-xxx.md
python kb.py index
```

## Proposal Types

- `PROP-ADD-*`: new extract has no matching vault card.
- `PROP-UPDATE-*`: source extract changed and the existing vault card is stale.
- `PROP-LINK-*`: two existing vault cards look related.

## Review Checklist

- Source extract path is present.
- Source SHA256 is present for add/update proposals.
- `warning:` messages are not hidden.
- Proposed content is inside `BEGIN_PROPOSED_MARKDOWN` / `END_PROPOSED_MARKDOWN`.
- Add/update proposed content was generated with local AI, not deterministic fallback text.
- `related` links are plausible and source-backed.
- `supports`, `contradicts`, and `supersedes` are only added by human judgment.
- After applying, run `python kb.py index` and one focused `python kb.py search`.
- If semantic retrieval is configured, run `python kb.py embed-index` after `index`.

## Rules

- Do not apply a proposal unless the user clearly approves it.
- Do not silently edit reviewed vault cards outside the proposal flow.
- Do not treat SQLite as source of truth.
- Do not invent relations beyond the available source text.
- Stop if `.env`/local AI is not configured for content proposals.
- If no embedding API exists, use `LOCAL_EMBEDDING_CMD` with `tools/embed_flagembedding_bgem3.py`, `tools/embed_sentence_transformers.py`, or `tools/embed_transformersjs.mjs`; follow `docs/agent_configuration_guide.md` for setup details.
