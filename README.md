# 离线 Markdown 知识库 + 本地 RAG MVP

这是一个 Windows 优先、零第三方 Python 依赖的离线知识库原型。Markdown 是事实源，SQLite FTS5 是可重建索引，本地 AI 只作为可选增强。

## 快速开始

在 PowerShell 中进入项目目录后运行：

```powershell
python kb.py demo
```

这会创建 `vault/`、`data/`、`index/` 目录，导入样例实验数据，重建索引，并执行一次“催化剂”检索。

## 常用命令

```powershell
python kb.py init
python kb.py ingest data/sample_experiments.csv
python kb.py index
python kb.py search "催化剂"
python kb.py ask "催化剂 A 的推荐条件是什么"
python kb.py propose
python kb.py distill
```

`ask` 会先做本地检索，再尝试调用公司内网 OpenAI 兼容接口。如果没有配置 AI，它会自动降级为检索结果，不会联网。
`distill` 会把实验、文献和小组汇报压缩成可检索的知识卡，放到 `vault/distilled/`。

## 本地 AI 配置

如果公司提供的是 OpenAI 兼容接口，在 PowerShell 中设置：

```powershell
$env:LOCAL_OPENAI_BASE_URL="http://127.0.0.1:8000/v1"
$env:LOCAL_OPENAI_API_KEY="local-key-if-required"
$env:LOCAL_OPENAI_CHAT_MODEL="local-model-name"
python kb.py ask "催化剂实验结论是什么"
```

`LOCAL_OPENAI_API_KEY` 可以为空；有些内网模型不要求密钥。

## 数据导入

第一版支持 CSV 和 JSON。CSV 每一行会生成一篇 `vault/experiments/*.md`。系统优先识别这些字段：

```text
id, title, summary, result, conclusion, date, source_id, source_system, tags, status
```

其他字段会写入 Markdown 的“原始字段”表格。导入文件路径和 SHA256 会写入 frontmatter，方便审计。

JSON 支持对象数组：

```json
[
  {
    "id": "EXP-2026-0001",
    "title": "催化剂 A 条件筛选",
    "summary": "实验摘要",
    "result": "关键观察",
    "conclusion": "结论"
  }
]
```

也支持 `{ "experiments": [...] }`。

## 知识库约定

正式知识放在：

```text
vault/experiments/
vault/concepts/
```

AI 生成的新知识建议只会写到：

```text
vault/proposals/
```

`propose` 不会自动修改正式 Markdown。人工审核通过后，再手动把建议整理到正式知识库。

## 知识蒸馏模板

系统默认按三类模板提取精华:

- 实验: 一句话结论、可复用规则、关键条件、证据摘要、边界与风险、下一步建议
- 文献: 研究问题、核心方法、核心发现、证据摘要、证据强度判断、局限与前提、对我们可用的点、关键词
- 小组汇报: 汇报主题、关键决定、行动项、风险与阻塞、负责人与截止时间、会议结论

蒸馏卡保留来源路径, 便于追溯原文。

## 设计边界

- 不使用第三方 Python 包，不依赖 pip、make、bash 或外网。
- 不引入 LangChain、FAISS、FastAPI、PyYAML 或前端框架。
- SQLite 索引是派生缓存，可以删除后用 `python kb.py index` 重建。
- 第一版保留 `acl` 字段，但不做强制权限过滤。
