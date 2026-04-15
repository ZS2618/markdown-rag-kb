# Raw Materials

`raw/` 只放原始材料和从原始材料提取出来的文本摘录。

## 原始文件

把真实原始文件放在这些目录:

```text
raw/experiments/    Excel、PPT、仪器导出、实验系统导出
raw/literature/     PDF 文献
raw/reports/        PDF、PPT、小组汇报材料
```

这些真实原始文件默认被 `.gitignore` 忽略, 避免把内部资料或大文件提交到公开仓库。

## 文本摘录

第一版不依赖第三方包, 不直接解析 PDF、PPT、Excel。请先用公司允许的工具或本地 AI 把原始文件转成文本摘录, 放到:

```text
raw/extracts/experiments/*.extract.md
raw/extracts/literature/*.extract.md
raw/extracts/reports/*.extract.md
```

`python kb.py distill` 只读取这些 `.extract.md` 文件。经过蒸馏并结构化之后, 内容才会进入 `vault/`。
