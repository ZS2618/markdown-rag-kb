#!/usr/bin/env python3
"""
LOCAL_EMBEDDING_CMD adapter for FlagEmbedding BGEM3FlagModel.

Use this when the approved model is BGE-M3 and the office machine can install
FlagEmbedding.
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


def to_list(vector):
    if hasattr(vector, "tolist"):
        return vector.astype(float).tolist() if hasattr(vector, "astype") else vector.tolist()
    return [float(item) for item in vector]


def main():
    texts = read_payload()
    model_path = (
        os.environ.get("LOCAL_EMBEDDING_MODEL_PATH")
        or os.environ.get("EMBEDDING_MODEL_PATH")
        or os.environ.get("LOCAL_OPENAI_EMBEDDING_MODEL")
        or "models/bge-m3"
    )
    batch_size = int(os.environ.get("LOCAL_EMBEDDING_BATCH_SIZE", "16"))
    max_length = int(os.environ.get("LOCAL_EMBEDDING_MAX_SEQ_LENGTH", "8192"))
    use_fp16 = env_bool("LOCAL_EMBEDDING_USE_FP16", False)

    try:
        from FlagEmbedding import BGEM3FlagModel
    except ImportError as exc:
        raise SystemExit(
            "FlagEmbedding is not installed. "
            "Install optional dependencies from requirements-embedding-flagembedding.txt."
        ) from exc

    model = BGEM3FlagModel(model_path, use_fp16=use_fp16)
    result = model.encode(
        texts,
        batch_size=batch_size,
        max_length=max_length,
        return_dense=True,
        return_sparse=False,
        return_colbert_vecs=False,
    )
    vectors = result["dense_vecs"]
    payload = {
        "model": model_path,
        "data": [
            {"index": idx, "embedding": to_list(vector)}
            for idx, vector in enumerate(vectors)
        ],
    }
    print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))


if __name__ == "__main__":
    main()
