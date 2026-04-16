#!/usr/bin/env node
/*
LOCAL_EMBEDDING_CMD adapter for Transformers.js.

stdin:
  {"input": ["text 1", "text 2"]}

stdout:
  {"data": [{"index": 0, "embedding": [...]}, ...]}
*/

import fs from 'node:fs';
import { env, pipeline } from '@huggingface/transformers';

function envBool(name, fallback) {
  const value = process.env[name];
  if (value === undefined) return fallback;
  return ['1', 'true', 'yes', 'y', 'on'].includes(value.trim().toLowerCase());
}

function readPayload() {
  const raw = fs.readFileSync(0, 'utf8');
  const payload = JSON.parse(raw);
  let texts = payload.input;
  if (typeof texts === 'string') texts = [texts];
  if (!Array.isArray(texts) || !texts.every((item) => typeof item === 'string')) {
    throw new Error('stdin must be {"input": ["text", ...]}');
  }
  return texts;
}

const texts = readPayload();
const modelPath =
  process.env.LOCAL_EMBEDDING_MODEL_PATH ||
  process.env.EMBEDDING_MODEL_PATH ||
  process.env.LOCAL_OPENAI_EMBEDDING_MODEL ||
  'models/bge-small-zh-v1.5';

const localFilesOnly = envBool('LOCAL_EMBEDDING_LOCAL_FILES_ONLY', true);
const normalize = envBool('LOCAL_EMBEDDING_NORMALIZE', true);
const pooling = process.env.LOCAL_EMBEDDING_POOLING || 'mean';
const dtype = process.env.LOCAL_EMBEDDING_DTYPE || 'q8';

env.allowLocalModels = true;
env.allowRemoteModels = !localFilesOnly;
if (process.env.TRANSFORMERS_CACHE) {
  env.cacheDir = process.env.TRANSFORMERS_CACHE;
}
if (process.env.TRANSFORMERS_LOCAL_MODEL_PATH) {
  env.localModelPath = process.env.TRANSFORMERS_LOCAL_MODEL_PATH;
}

const extractor = await pipeline('feature-extraction', modelPath, { dtype });
const output = await extractor(texts, { pooling, normalize });
let vectors = await output.tolist();
if (texts.length === 1 && !Array.isArray(vectors[0])) {
  vectors = [vectors];
}

const response = {
  model: modelPath,
  data: vectors.map((embedding, index) => ({ index, embedding })),
};
process.stdout.write(JSON.stringify(response));
