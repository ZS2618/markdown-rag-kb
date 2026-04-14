# Crash Course

这是一份上手指南。目标很简单: 你在办公室克隆这个项目后, 按顺序执行下面的命令, 就能把知识库跑起来、导入数据、搜索、问答, 以及生成待审核草稿。

## 先跑起来

在项目目录里打开 PowerShell, 先跑 demo:

```powershell
python kb.py demo
```

这条命令会自动做四件事:

1. 创建 `vault/`、`data/`、`index/` 这些目录
2. 导入样例实验数据
3. 重建 SQLite FTS5 索引
4. 做一次“催化剂”搜索, 让你看到结果长什么样

如果这一步成功, 说明你的环境已经可以用了。

## 你会看到什么

跑完后, 项目里会多出这些东西:

```text
vault/experiments/    实验 Markdown
vault/concepts/       概念类 Markdown
vault/proposals/      待人工审核的草稿
data/                 样例输入
index/kb.sqlite       派生索引, 可以删除后重建
```

你真正维护的是 `vault/` 里的 Markdown。`index/kb.sqlite` 只是缓存, 不要把它当事实源。

## 最常用的命令

```powershell
python kb.py init
python kb.py ingest data/sample_experiments.csv
python kb.py index
python kb.py search "催化剂"
python kb.py ask "催化剂 A 的推荐条件是什么"
python kb.py propose
```

每个命令的作用:

`init`
: 初始化目录和空索引。适合第一次克隆后执行。

`ingest`
: 把 CSV 或 JSON 实验数据转成 Markdown。

`index`
: 扫描 `vault/**/*.md`, 重新建立 SQLite 索引。

`search`
: 只做本地检索, 不调用 AI。

`ask`
: 先检索, 再尝试调用公司内网的 OpenAI 兼容接口。

`propose`
: 生成 `vault/proposals/` 里的待审核草稿, 不会自动改正式知识库。

## 导入数据

第一版支持 CSV 和 JSON。

CSV 示例:

```csv
id,title,summary,result,conclusion,date,source_id,source_system,tags
EXP-2026-0001,催化剂 A 条件筛选,对催化剂 A 在不同温度下进行筛选,80 摄氏度条件下转化率达到 91%,催化剂 A 的推荐初始条件为 80 摄氏度,2026-04-14,LIMS-12345,LIMS,"催化剂, 条件筛选"
```

导入后, 每一行会生成一篇 Markdown, 放在 `vault/experiments/`。

如果你有自己的导出文件, 直接替换成:

```powershell
python kb.py ingest path\to\your_file.csv
python kb.py index
```

## Markdown 怎么写

每篇正式文档都建议有 frontmatter 和固定章节。最小格式像这样:

```markdown
---
id: EXP-2026-0001
type: experiment
title: 催化剂 A 条件筛选
source_system: LIMS
source_id: LIMS-12345
status: imported
tags: [催化剂, 条件筛选]
updated_at: 2026-04-14
---

# 催化剂 A 条件筛选

## 摘要

## 实验条件

## 关键观察

## 结论
```

你不用一开始就写得很完整, 但最好保留这几个章节名, 这样后面检索和 proposal 都更稳定。

## 搜索和问答

先做纯检索:

```powershell
python kb.py search "催化剂"
```

如果你想问一句完整的话:

```powershell
python kb.py ask "催化剂实验结论是什么"
```

没有配置本地 AI 时, `ask` 会自动降级为本地检索结果, 不会报错也不会联网。

## 接本地 AI

如果公司提供的是 OpenAI 兼容接口, 在 PowerShell 里设置:

```powershell
$env:LOCAL_OPENAI_BASE_URL="http://127.0.0.1:8000/v1"
$env:LOCAL_OPENAI_API_KEY="local-key-if-required"
$env:LOCAL_OPENAI_CHAT_MODEL="local-model-name"
python kb.py ask "催化剂 A 的推荐条件是什么"
```

只要 base URL 可用, 这个项目就会尝试调用本地模型。

## proposal 是什么

`python kb.py propose` 会把每篇正式文档生成一份待审核草稿, 放到 `vault/proposals/`。

它的用途是:

1. 提醒你哪些文档缺摘要、缺结论、缺标签
2. 让本地 AI 或规则系统先写建议稿
3. 人工确认后再把内容合并回正式 Markdown

第一版不会自动改正式知识库, 这是故意的, 这样更适合有审计要求的环境。

## 一个推荐工作流

如果你今天要真正开始用它, 我建议按这个顺序:

1. `python kb.py init`
2. 把你的实验导出成 CSV 或 JSON
3. `python kb.py ingest 你的文件.csv`
4. `python kb.py index`
5. `python kb.py search "你关心的关键词"`
6. `python kb.py ask "完整问题"`
7. `python kb.py propose`

## 常见坑

`search` 没结果
: 先确认跑过 `python kb.py index`。如果你改过 Markdown, 也要重新建索引。

`ask` 只返回检索结果
: 说明没有配置 `LOCAL_OPENAI_BASE_URL`, 或者本地 AI 接口不可达。

导入后看不到新内容
: 大概率是你还没重新执行 `python kb.py index`。

Windows 路径问题
: 尽量在项目根目录里执行命令, 并优先使用相对路径。

## 你真正要记住的一句话

Markdown 是事实源, SQLite 是索引, AI 只负责辅助和提案, 不负责偷偷改正式知识库。
