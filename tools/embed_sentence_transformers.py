#!/usr/bin/env python3
"""
LOCAL_EMBEDDING_CMD adapter for sentence-transformers.

stdin:
  {"input": ["text 1", "text 2"]}

stdout:
  {"data": [{"index": 0, "embedding": [...]}, ...]}
"""

import json
import os
import sys


def env_bool(name, default):
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def read_payload():
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"invalid JSON on stdin: {exc}") from exc
    texts = payload.get("input")
    if isinstance(texts, str):
        texts = [texts]
    if not isinstance(texts, list) or not all(isinstance(item, str) for item in texts):
        raise SystemExit('stdin must be {"input": ["text", ...]}')
    return texts


def main():
    texts = read_payload()
    model_path = (
        os.environ.get("LOCAL_EMBEDDING_MODEL_PATH")
        or os.environ.get("EMBEDDING_MODEL_PATH")
        or os.environ.get("LOCAL_OPENAI_EMBEDDING_MODEL")
        or "models/bge-m3"
    )
    batch_size = int(os.environ.get("LOCAL_EMBEDDING_BATCH_SIZE", "16"))
    normalize = env_bool("LOCAL_EMBEDDING_NORMALIZE", True)
    local_files_only = env_bool("LOCAL_EMBEDDING_LOCAL_FILES_ONLY", True)
    trust_remote_code = env_bool("LOCAL_EMBEDDING_TRUST_REMOTE_CODE", False)
    device = os.environ.get("LOCAL_EMBEDDING_DEVICE") or None
    max_seq_length = os.environ.get("LOCAL_EMBEDDING_MAX_SEQ_LENGTH")

    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as exc:
        raise SystemExit(
            "sentence-transformers is not installed. "
            "Install optional dependencies from requirements-embedding-sentence-transformers.txt."
        ) from exc

    model = SentenceTransformer(
        model_path,
        device=device,
        local_files_only=local_files_only,
        trust_remote_code=trust_remote_code,
    )
    if max_seq_length:
        model.max_seq_length = int(max_seq_length)
    vectors = model.encode(
        texts,
        batch_size=batch_size,
        normalize_embeddings=normalize,
        convert_to_numpy=True,
        show_progress_bar=False,
    )
    payload = {
        "model": model_path,
        "data": [
            {"index": idx, "embedding": vector.astype(float).tolist()}
            for idx, vector in enumerate(vectors)
        ],
    }
    print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))


if __name__ == "__main__":
    main()
