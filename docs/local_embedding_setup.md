# Local Embedding Setup

如果公司不提供 embedding API, 就用 `LOCAL_EMBEDDING_CMD`。`kb.py` 会把待向量化文本发给本地命令, 本地命令返回 JSON 向量。

## 推荐选择

锂电池研究资料通常中英文混合, 还有论文长段落、实验条件、材料体系和测试指标。推荐顺序:

1. Python + `FlagEmbedding` + BGE-M3: 最适合 BGE-M3, 中英混合和长文本表现好。
2. Python + `sentence-transformers`: 通用、生态成熟, 适合 BGE 系列或公司已批准的 sentence-transformers 模型。
3. Node + Transformers.js: 办公机 Node 环境更方便时使用, 需要准备 Transformers.js 可加载的本地模型目录。

## 一键配置

推荐先让 IT 把模型目录放到 `models/bge-m3`。然后运行:

```powershell
python tools/setup_embedding.py --backend flagembedding --model-path models\bge-m3
```

这个脚本会:

1. 如果没有 `.env`, 从 `.env.example` 创建。
2. 创建 `.venv-embed` 或 Node 依赖环境。
3. 安装所选后端依赖。
4. 写入 `LOCAL_EMBEDDING_CMD` 和模型路径。
5. 运行一次 embedding smoke test, 确认 stdout 是合法 JSON 向量。

如果公司使用内网 pip 镜像:

```powershell
python tools/setup_embedding.py --backend flagembedding --model-path models\bge-m3 --pip-index-url http://pypi.company/simple
```

如果公司用离线 wheel 包目录:

```powershell
python tools/setup_embedding.py --backend flagembedding --model-path models\bge-m3 --offline-wheel-dir D:\wheels
```

如果模型文件还没拷贝, 但想先写好 `.env`:

```powershell
python tools/setup_embedding.py --backend flagembedding --model-path models\bge-m3 --skip-smoke-test
```

Node 路线:

```powershell
python tools/setup_embedding.py --backend node --model-path models\bge-small-zh-v1.5
```

脚本失败时会保留 stdout/stderr 摘要, 并提示是依赖、模型路径、JSON 输出还是命令超时问题。

## 目录约定

模型文件建议放在:

```text
models/
  bge-m3/
  bge-small-zh-v1.5/
```

`models/` 不需要提交到 Git。可以由 IT 通过内网盘分发。

## 路线 A: FlagEmbedding + BGE-M3

适合重点做中英文论文、锂电池术语、长文本语义检索。

安装:

```powershell
python -m venv .venv-embed
.venv-embed\Scripts\python -m pip install -r requirements-embedding-flagembedding.txt
```

`.env`:

```env
LOCAL_EMBEDDING_CMD=.venv-embed\Scripts\python tools\embed_flagembedding_bgem3.py
LOCAL_EMBEDDING_MODEL_PATH=models\bge-m3
LOCAL_EMBEDDING_BATCH_SIZE=8
LOCAL_EMBEDDING_MAX_SEQ_LENGTH=8192
LOCAL_EMBEDDING_USE_FP16=false
```

运行:

```powershell
python kb.py index
python kb.py embed-index
python kb.py semantic-search "高镍正极循环后阻抗上升的原因"
```

CPU 机器建议 `LOCAL_EMBEDDING_USE_FP16=false`。有支持半精度的 GPU 时再改成 `true`。

## 路线 B: sentence-transformers

适合公司已经批准 `sentence-transformers` 包, 或模型就是 sentence-transformers 格式。

安装:

```powershell
python -m venv .venv-embed
.venv-embed\Scripts\python -m pip install -r requirements-embedding-sentence-transformers.txt
```

`.env`:

```env
LOCAL_EMBEDDING_CMD=.venv-embed\Scripts\python tools\embed_sentence_transformers.py
LOCAL_EMBEDDING_MODEL_PATH=models\bge-m3
LOCAL_EMBEDDING_BATCH_SIZE=16
LOCAL_EMBEDDING_LOCAL_FILES_ONLY=true
LOCAL_EMBEDDING_NORMALIZE=true
```

如果模型需要自定义代码, 只有在软件审核通过后再设置:

```env
LOCAL_EMBEDDING_TRUST_REMOTE_CODE=true
```

## 路线 C: Node + Transformers.js

适合办公室 Node 生态更容易批准时使用。需要准备 Transformers.js 可加载的 ONNX 模型目录。

安装:

```powershell
copy tools\embedding-package.example.json package.json
npm install
```

`.env`:

```env
LOCAL_EMBEDDING_CMD=node tools\embed_transformersjs.mjs
LOCAL_EMBEDDING_MODEL_PATH=models\bge-small-zh-v1.5
LOCAL_EMBEDDING_LOCAL_FILES_ONLY=true
LOCAL_EMBEDDING_NORMALIZE=true
LOCAL_EMBEDDING_POOLING=mean
LOCAL_EMBEDDING_DTYPE=q8
```

如果模型目录不在项目内, 可以额外设置:

```env
TRANSFORMERS_LOCAL_MODEL_PATH=D:\ai-models
TRANSFORMERS_CACHE=D:\ai-model-cache
```

## 测试命令

先测本地命令本身:

```powershell
'{"input":["锂金属负极阻抗上升","电解液添加剂改善循环"]}' | .venv-embed\Scripts\python tools\embed_flagembedding_bgem3.py
```

输出应该包含:

```json
{"data":[{"index":0,"embedding":[...]}]}
```

再接入知识库:

```powershell
python kb.py index
python kb.py embed-index
python kb.py semantic-search "EIS 阻抗增长和 SEI 的关系"
```

## 常见问题

`LOCAL_EMBEDDING_CMD returned invalid JSON`
: 本地命令 stdout 里混入了日志。把日志写到 stderr, stdout 只能输出 JSON。

`No embeddings found for model`
: 改过 `LOCAL_EMBEDDING_CMD` 或模型路径后, 重新运行 `python kb.py embed-index --force`。

`local files only` 找不到模型
: 确认 `LOCAL_EMBEDDING_MODEL_PATH` 指向的是已下载/已拷贝的本地模型目录。

语义检索结果很怪
: 检查模型是否适合中文和科研文本, 再用真实模型重新 `embed-index --force`。测试用假向量只能验证接口, 不能验证效果。
