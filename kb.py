#!/usr/bin/env python3
"""
Offline Markdown knowledge base + local RAG CLI.

The project intentionally uses only Python's standard library so it can run in
restricted office environments after a plain clone.
"""

import argparse
import csv
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
import urllib.error
import urllib.request


ROOT = Path(__file__).resolve().parent
VAULT_DIR = ROOT / "vault"
EXPERIMENTS_DIR = VAULT_DIR / "experiments"
CONCEPTS_DIR = VAULT_DIR / "concepts"
PROPOSALS_DIR = VAULT_DIR / "proposals"
DISTILLED_DIR = VAULT_DIR / "distilled"
LITERATURE_DIR = VAULT_DIR / "literature"
REPORTS_DIR = VAULT_DIR / "reports"
DATA_DIR = ROOT / "data"
INDEX_DIR = ROOT / "index"
DB_PATH = INDEX_DIR / "kb.sqlite"
SAMPLE_CSV = DATA_DIR / "sample_experiments.csv"

KNOWN_FIELDS = {
    "id",
    "title",
    "summary",
    "result",
    "conclusion",
    "date",
    "source_id",
    "source_system",
    "tags",
    "status",
}


def now_iso():
    return dt.datetime.now(dt.timezone.utc).astimezone().replace(microsecond=0).isoformat()


def ensure_dirs():
    for path in (
        VAULT_DIR,
        EXPERIMENTS_DIR,
        CONCEPTS_DIR,
        PROPOSALS_DIR,
        DISTILLED_DIR,
        LITERATURE_DIR,
        REPORTS_DIR,
        DATA_DIR,
        INDEX_DIR,
    ):
        path.mkdir(parents=True, exist_ok=True)


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def sha256_file(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def stable_id(prefix, value):
    digest = sha256_bytes(value.encode("utf-8")).upper()[:12]
    return f"{prefix}-{digest}"


def slugify(value, fallback):
    text = str(value or "").strip()
    if not text:
        text = fallback
    text = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "-", text)
    text = re.sub(r"\s+", "-", text)
    text = text.strip(".- ")
    return (text or fallback)[:90]


def read_text(path):
    return path.read_text(encoding="utf-8")


def write_text(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="\n")


def parse_scalar(value):
    value = value.strip()
    if value.startswith("[") and value.endswith("]"):
        inner = value[1:-1].strip()
        if not inner:
            return []
        return [part.strip().strip('"').strip("'") for part in inner.split(",")]
    return value.strip('"').strip("'")


def parse_markdown(text):
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---\n", 4)
    if end == -1:
        return {}, text
    frontmatter = text[4:end]
    body = text[end + 5 :]
    meta = {}
    for line in frontmatter.splitlines():
        if not line.strip() or line.lstrip().startswith("#") or ":" not in line:
            continue
        key, value = line.split(":", 1)
        meta[key.strip()] = parse_scalar(value)
    return meta, body.lstrip("\n")


def emit_frontmatter(meta):
    lines = ["---"]
    for key, value in meta.items():
        if isinstance(value, (list, tuple)):
            safe_items = [str(item).replace(",", " ").strip() for item in value if str(item).strip()]
            lines.append(f"{key}: [{', '.join(safe_items)}]")
        else:
            clean = str(value if value is not None else "").replace("\n", " ").strip()
            lines.append(f"{key}: {clean}")
    lines.append("---")
    return "\n".join(lines) + "\n\n"


def extract_title(meta, body, path):
    if meta.get("title"):
        return str(meta["title"])
    match = re.search(r"^#\s+(.+)$", body, flags=re.MULTILINE)
    if match:
        return match.group(1).strip()
    return path.stem


def tags_from_value(value):
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if not value:
        return []
    return [part.strip() for part in re.split(r"[,;，；]", str(value)) if part.strip()]


def markdown_table(rows):
    if not rows:
        return "无\n"
    out = ["| 字段 | 值 |", "| --- | --- |"]
    for key, value in rows:
        safe_value = str(value).replace("|", "\\|").replace("\n", " ").strip()
        out.append(f"| {key} | {safe_value} |")
    return "\n".join(out) + "\n"


def extract_sections(body):
    matches = list(re.finditer(r"(?m)^(#{1,6})\s+(.+?)\s*$", body))
    sections = {}
    for idx, match in enumerate(matches):
        heading = match.group(2).strip()
        start = match.end()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(body)
        sections[heading] = body[start:end].strip()
    return sections


def section_text(body, *names):
    sections = extract_sections(body)
    for name in names:
        if name in sections and sections[name].strip():
            return sections[name].strip()
    lowered = {key.lower(): value for key, value in sections.items()}
    for name in names:
        value = lowered.get(name.lower())
        if value and value.strip():
            return value.strip()
    return ""


def first_paragraph(text):
    cleaned = [line.strip() for line in text.splitlines()]
    chunks = []
    current = []
    for line in cleaned:
        if not line:
            if current:
                chunks.append(" ".join(current).strip())
                current = []
            continue
        if line.startswith("|") or line.startswith("- ") or line.startswith("* "):
            continue
        current.append(line)
    if current:
        chunks.append(" ".join(current).strip())
    return chunks[0] if chunks else ""


def bullet_list(text):
    items = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith(("- ", "* ", "+ ")):
            item = stripped[2:].strip()
            if item:
                items.append(item)
    return items


def truncate_text(text, limit=180):
    compact = re.sub(r"\s+", " ", text).strip()
    if len(compact) <= limit:
        return compact
    return compact[: max(0, limit - 1)].rstrip() + "…"


def doc_kind(meta, path):
    type_hint = str(meta.get("type") or "").lower()
    try:
        rel_parts = [part.lower() for part in path.relative_to(VAULT_DIR).parts]
    except ValueError:
        rel_parts = [part.lower() for part in path.parts]
    first_part = rel_parts[0] if rel_parts else ""
    if first_part == "distilled":
        return "general"
    if "experiment" in type_hint or first_part == "experiments":
        return "experiment"
    if any(token in type_hint for token in ("literature", "paper", "article", "paper-note")) or first_part == "literature":
        return "literature"
    if any(token in type_hint for token in ("report", "meeting", "review")) or first_part == "reports":
        return "report"
    if "concept" in type_hint or first_part == "concepts":
        return "concept"
    return "general"


def distill_source_path(source_doc, kind):
    source_id = source_doc["id"]
    if kind == "experiment":
        return DISTILLED_DIR / "experiments" / f"{slugify(source_id, 'experiment')}.md"
    if kind == "literature":
        return DISTILLED_DIR / "literature" / f"{slugify(source_id, 'literature')}.md"
    if kind == "report":
        return DISTILLED_DIR / "reports" / f"{slugify(source_id, 'report')}.md"
    return DISTILLED_DIR / "general" / f"{slugify(source_id, 'document')}.md"


def extract_experiment_atoms(meta, body):
    return {
        "summary": section_text(body, "摘要") or str(meta.get("summary") or "").strip(),
        "conditions": section_text(body, "实验条件"),
        "observations": section_text(body, "关键观察"),
        "conclusion": section_text(body, "结论") or str(meta.get("conclusion") or "").strip(),
        "raw_tags": tags_from_value(meta.get("tags")),
    }


def extract_literature_atoms(meta, body):
    sections = extract_sections(body)
    abstract = section_text(body, "摘要", "Abstract", "概述") or str(meta.get("summary") or "").strip()
    return {
        "problem": section_text(body, "研究问题", "问题", "目的", "Objective"),
        "method": section_text(body, "方法", "Method", "Approach"),
        "findings": section_text(body, "结果", "结论", "Findings", "Results"),
        "limitations": section_text(body, "局限", "局限性", "Limitations"),
        "abstract": abstract or first_paragraph(body),
        "keywords": tags_from_value(meta.get("tags")) or bullet_list(sections.get("关键词", "")),
    }


def extract_report_atoms(meta, body):
    actions = section_text(body, "行动项", "Action Items", "待办")
    decisions = section_text(body, "决定事项", "关键决定", "结论", "Decisions")
    risks = section_text(body, "风险", "阻塞项", "Issues", "Blockers")
    return {
        "topic": section_text(body, "主题", "会议主题", "项目背景") or str(meta.get("title") or "").strip(),
        "decisions": decisions,
        "actions": actions,
        "risks": risks,
        "owner": str(meta.get("owner") or "").strip(),
        "deadline": str(meta.get("deadline") or "").strip(),
    }


def experiment_distillation_body(meta, path, source_path, atoms):
    title = str(meta.get("title") or path.stem)
    conclusion = atoms["conclusion"] or "待补充。"
    summary = atoms["summary"] or "待补充。"
    conditions = atoms["conditions"] or "未抽取到结构化实验条件。"
    observations = atoms["observations"] or "待补充。"
    reusable_rule = conclusion if conclusion != "待补充。" else summary
    next_step = "复现推荐条件并补充对照组。"
    caveat = "注意区分单次结果和稳定规律，正式结论需结合更多批次验证。"
    return (
        f"# 蒸馏卡：{title}\n\n"
        "## 一句话结论\n\n"
        f"{truncate_text(conclusion or summary or '待补充。', 220)}\n\n"
        "## 可复用规则\n\n"
        f"{truncate_text(reusable_rule, 260)}\n\n"
        "## 关键条件\n\n"
        f"{conditions}\n\n"
        "## 证据摘要\n\n"
        f"{observations}\n\n"
        "## 边界与风险\n\n"
        f"{caveat}\n\n"
        "## 下一步建议\n\n"
        f"{next_step}\n\n"
        "## 来源\n\n"
        f"- {source_path}\n"
    )


def literature_distillation_body(meta, path, source_path, atoms):
    title = str(meta.get("title") or path.stem)
    abstract = atoms["abstract"] or "待补充。"
    problem = atoms["problem"] or "未明确指出研究问题。"
    method = atoms["method"] or "未明确指出方法。"
    findings = atoms["findings"] or "未明确给出结论。"
    limitations = atoms["limitations"] or "未明确给出局限。"
    keywords = ", ".join(atoms["keywords"]) if atoms["keywords"] else "待补充"
    applicable = "把研究方法或核心机制映射到我们当前的实验条件，再判断是否需要本地复现。"
    evidence = "先按证据来源和样本规模判断可迁移性，再决定是否直接采用。"
    return (
        f"# 文献蒸馏：{title}\n\n"
        "## 研究问题\n\n"
        f"{problem}\n\n"
        "## 核心方法\n\n"
        f"{method}\n\n"
        "## 核心发现\n\n"
        f"{findings}\n\n"
        "## 证据摘要\n\n"
        f"{abstract}\n\n"
        "## 证据强度判断\n\n"
        f"{evidence}\n\n"
        "## 局限与前提\n\n"
        f"{limitations}\n\n"
        "## 对我们可用的点\n\n"
        f"{applicable}\n\n"
        "## 关键词\n\n"
        f"{keywords}\n\n"
        "## 来源\n\n"
        f"- {source_path}\n"
    )


def report_distillation_body(meta, path, source_path, atoms):
    title = str(meta.get("title") or path.stem)
    topic = atoms["topic"] or "待补充。"
    decisions = atoms["decisions"] or "未抽取到明确决定事项。"
    actions = atoms["actions"] or "未抽取到行动项。"
    risks = atoms["risks"] or "未抽取到阻塞项或风险。"
    owner = atoms["owner"] or "待补充"
    deadline = atoms["deadline"] or "待补充"
    return (
        f"# 小组汇报蒸馏：{title}\n\n"
        "## 汇报主题\n\n"
        f"{topic}\n\n"
        "## 关键决定\n\n"
        f"{decisions}\n\n"
        "## 行动项\n\n"
        f"{actions}\n\n"
        "## 风险与阻塞\n\n"
        f"{risks}\n\n"
        "## 负责人与截止时间\n\n"
        f"- 负责人: {owner}\n"
        f"- 截止时间: {deadline}\n\n"
        "## 会议结论\n\n"
        "把决策、行动项和风险压缩成三件事: 现在要做什么, 谁来做, 什么时候复盘。\n\n"
        "## 来源\n\n"
        f"- {source_path}\n"
    )


def general_distillation_body(meta, path, source_path, body):
    title = str(meta.get("title") or path.stem)
    lead = first_paragraph(body) or "待补充。"
    return (
        f"# 蒸馏卡：{title}\n\n"
        "## 一句话结论\n\n"
        f"{truncate_text(lead, 220)}\n\n"
        "## 可复用规则\n\n"
        "待人工补充。\n\n"
        "## 风险与边界\n\n"
        "待人工补充。\n\n"
        "## 来源\n\n"
        f"- {source_path}\n"
    )


def generate_distillation(meta, body, path, source_path):
    kind = doc_kind(meta, path)
    if kind == "experiment":
        return experiment_distillation_body(meta, path, source_path, extract_experiment_atoms(meta, body)), kind
    if kind == "literature":
        return literature_distillation_body(meta, path, source_path, extract_literature_atoms(meta, body)), kind
    if kind == "report":
        return report_distillation_body(meta, path, source_path, extract_report_atoms(meta, body)), kind
    return general_distillation_body(meta, path, source_path, body), kind


def distill_target_meta(source_doc, source_sha, kind):
    source_path = source_doc["path"]
    source_id = source_doc["id"]
    return {
        "id": f"DIST-{source_id}",
        "type": f"distilled-{kind}",
        "title": f"蒸馏卡：{source_doc['title']}",
        "status": "draft",
        "source_document_id": source_id,
        "source_path": source_path,
        "source_sha256": source_sha,
        "template_kind": kind,
        "updated_at": now_iso(),
    }


def row_identity(row):
    for key in ("id", "source_id"):
        if row.get(key):
            return str(row[key]).strip()
    encoded = json.dumps(row, ensure_ascii=False, sort_keys=True)
    return stable_id("EXP", encoded)


def normalize_row(row):
    return {str(k).strip(): "" if v is None else str(v).strip() for k, v in row.items()}


def experiment_markdown(row, source_path, source_sha):
    row = normalize_row(row)
    experiment_id = row_identity(row)
    title = row.get("title") or f"实验 {experiment_id}"
    tags = tags_from_value(row.get("tags"))
    meta = {
        "id": experiment_id,
        "type": "experiment",
        "title": title,
        "source_system": row.get("source_system") or "file-import",
        "source_id": row.get("source_id") or experiment_id,
        "status": row.get("status") or "imported",
        "tags": tags,
        "acl": "",
        "raw_data_path": str(source_path),
        "raw_data_sha256": source_sha,
        "updated_at": row.get("date") or now_iso(),
    }
    other_rows = [(k, v) for k, v in row.items() if k not in KNOWN_FIELDS and v]
    condition_rows = [(k, v) for k, v in row.items() if k in KNOWN_FIELDS and k not in {"summary", "result", "conclusion"} and v]
    summary = row.get("summary") or "待补充。"
    result = row.get("result") or "待补充。"
    conclusion = row.get("conclusion") or "待补充。"
    body = (
        f"# {title}\n\n"
        "## 摘要\n\n"
        f"{summary}\n\n"
        "## 实验条件\n\n"
        f"{markdown_table(condition_rows)}\n"
        "## 关键观察\n\n"
        f"{result}\n\n"
        "## 结论\n\n"
        f"{conclusion}\n\n"
        "## 原始字段\n\n"
        f"{markdown_table(other_rows)}"
    )
    return emit_frontmatter(meta) + body


def load_records(source_path):
    suffix = source_path.suffix.lower()
    if suffix == ".csv":
        with source_path.open("r", encoding="utf-8-sig", newline="") as f:
            return [dict(row) for row in csv.DictReader(f)]
    if suffix == ".json":
        data = json.loads(read_text(source_path))
        if isinstance(data, list):
            return data
        if isinstance(data, dict) and isinstance(data.get("experiments"), list):
            return data["experiments"]
        if isinstance(data, dict):
            return [data]
    raise ValueError("Only CSV and JSON imports are supported in v1.")


def connect_db():
    ensure_dirs()
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    return con


def init_db(con):
    con.executescript(
        """
        CREATE TABLE IF NOT EXISTS documents (
            id TEXT PRIMARY KEY,
            path TEXT NOT NULL UNIQUE,
            title TEXT,
            type TEXT,
            status TEXT,
            tags_json TEXT,
            acl TEXT,
            sha256 TEXT NOT NULL,
            updated_at TEXT,
            body TEXT
        );

        CREATE TABLE IF NOT EXISTS chunks (
            id TEXT PRIMARY KEY,
            document_id TEXT NOT NULL,
            chunk_index INTEGER NOT NULL,
            text TEXT NOT NULL,
            FOREIGN KEY(document_id) REFERENCES documents(id) ON DELETE CASCADE
        );

        CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
            text,
            document_id UNINDEXED,
            chunk_index UNINDEXED,
            title UNINDEXED,
            path UNINDEXED
        );

        CREATE TABLE IF NOT EXISTS proposals (
            id TEXT PRIMARY KEY,
            source_document_id TEXT NOT NULL,
            path TEXT NOT NULL,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        """
    )
    con.commit()


def init_project(args):
    ensure_dirs()
    with connect_db() as con:
        init_db(con)
    if not SAMPLE_CSV.exists():
        create_sample_data()
    create_sample_source_docs()
    env_example = ROOT / "local_ai.env.example"
    if not env_example.exists():
        write_text(
            env_example,
            (
                "# PowerShell example:\n"
                '# $env:LOCAL_OPENAI_BASE_URL="http://127.0.0.1:8000/v1"\n'
                '# $env:LOCAL_OPENAI_API_KEY="local-key-if-required"\n'
                '# $env:LOCAL_OPENAI_CHAT_MODEL="local-model-name"\n'
            ),
        )
    print(f"Initialized knowledge base at {ROOT}")
    print(f"SQLite index: {DB_PATH}")


def create_sample_data():
    rows = [
        {
            "id": "EXP-2026-0001",
            "title": "催化剂 A 条件筛选",
            "summary": "对催化剂 A 在不同温度下进行筛选，目标是提高转化率并控制副产物。",
            "result": "80 摄氏度条件下转化率达到 91%，副产物低于 3%。60 摄氏度反应较慢。",
            "conclusion": "催化剂 A 的推荐初始条件为 80 摄氏度、2 小时、低水分体系。",
            "date": "2026-04-14",
            "source_id": "LIMS-12345",
            "source_system": "LIMS",
            "tags": "催化剂, 条件筛选",
            "temperature_c": "80",
            "yield_percent": "91",
        },
        {
            "id": "EXP-2026-0002",
            "title": "催化剂 B 对照实验",
            "summary": "以催化剂 B 作为对照，比较同一底物下的反应表现。",
            "result": "催化剂 B 在 80 摄氏度下转化率为 72%，副产物约 8%。",
            "conclusion": "在当前底物上催化剂 B 不优于催化剂 A，但可以作为低成本备选。",
            "date": "2026-04-14",
            "source_id": "LIMS-12346",
            "source_system": "LIMS",
            "tags": "催化剂, 对照实验",
            "temperature_c": "80",
            "yield_percent": "72",
        },
    ]
    SAMPLE_CSV.parent.mkdir(parents=True, exist_ok=True)
    with SAMPLE_CSV.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def create_sample_source_docs():
    literature_path = LITERATURE_DIR / "LIT-2026-0001-催化剂筛选方法综述.md"
    if not literature_path.exists():
        write_text(
            literature_path,
            """---
id: LIT-2026-0001
type: literature
title: 催化剂筛选方法综述
source_system: internal-reading
source_id: DOI-10.1000/example
status: imported
tags: [催化剂, 文献, 筛选]
updated_at: 2026-04-14
---

# 催化剂筛选方法综述

## 摘要

本文总结了催化剂筛选中常见的条件设计方法，强调单因素筛选、对照组设置和重复实验的重要性。

## 研究问题

如何在有限实验次数下尽快找到可放大的催化条件。

## 方法

通过文献对比和案例归纳，总结温度、溶剂、浓度、时间和含水量对结果的影响。

## 结果

低水分环境通常更稳定，温度过高会增加副产物，需要通过对照组验证。

## 局限

该综述偏重经验总结，缺少统一统计标准，部分结论依赖具体底物。

## 关键词

催化剂, 条件筛选, 对照组, 放大, 副产物
""",
        )

    report_path = REPORTS_DIR / "REP-2026-0001-催化剂筛选周报.md"
    if not report_path.exists():
        write_text(
            report_path,
            """---
id: REP-2026-0001
type: report
title: 催化剂筛选周报
source_system: team-meeting
source_id: WEEKLY-2026-16
owner: 研发小组A
deadline: 2026-04-18
status: imported
tags: [周报, 催化剂, 行动项]
updated_at: 2026-04-14
---

# 催化剂筛选周报

## 会议主题

本周重点讨论催化剂 A 和 B 的对照结果，以及下周的验证计划。

## 关键决定

- 继续以催化剂 A 作为主线方案。
- 对催化剂 B 仅保留低成本备选路线。

## 行动项

- 复现催化剂 A 的 80 摄氏度条件。
- 补充底物更换后的对照组。
- 整理 LIMS 数据和原始记录。

## 风险

- 数据批次较少，稳定性还需验证。
- 低水分控制需要流程固化。

## 需要支持

需要实验平台协助加快重复批次安排。
""",
        )


def cmd_ingest(args):
    ensure_dirs()
    source_path = (ROOT / args.source).resolve() if not Path(args.source).is_absolute() else Path(args.source)
    if not source_path.exists():
        raise FileNotFoundError(f"Import source not found: {source_path}")
    records = load_records(source_path)
    source_sha = sha256_file(source_path)
    count = 0
    for raw_row in records:
        if not isinstance(raw_row, dict):
            continue
        row = normalize_row(raw_row)
        experiment_id = row_identity(row)
        title = row.get("title") or experiment_id
        filename = f"{slugify(experiment_id, 'experiment')}-{slugify(title, 'untitled')}.md"
        target = EXPERIMENTS_DIR / filename
        write_text(target, experiment_markdown(row, source_path, source_sha))
        count += 1
    print(f"Imported {count} experiment record(s) from {source_path}")


def list_markdown_documents():
    if not VAULT_DIR.exists():
        return []
    docs = []
    for path in sorted(VAULT_DIR.rglob("*.md")):
        try:
            path.relative_to(PROPOSALS_DIR)
            continue
        except ValueError:
            docs.append(path)
    return docs


def chunk_text(body, max_chars=1200):
    sections = re.split(r"(?m)(?=^#{1,6}\s+)", body)
    chunks = []
    for section in sections:
        section = section.strip()
        if not section:
            continue
        if len(section) <= max_chars:
            chunks.append(section)
            continue
        paragraphs = [p.strip() for p in re.split(r"\n\s*\n", section) if p.strip()]
        current = ""
        for paragraph in paragraphs:
            if current and len(current) + len(paragraph) + 2 > max_chars:
                chunks.append(current)
                current = paragraph
            else:
                current = paragraph if not current else current + "\n\n" + paragraph
        if current:
            chunks.append(current)
    return chunks or [body.strip()]


def index_documents(args):
    ensure_dirs()
    with connect_db() as con:
        init_db(con)
        con.execute("DELETE FROM chunks_fts")
        con.execute("DELETE FROM chunks")
        con.execute("DELETE FROM documents")
        indexed = 0
        for path in list_markdown_documents():
            content = read_text(path)
            meta, body = parse_markdown(content)
            rel_path = str(path.relative_to(ROOT))
            doc_id = str(meta.get("id") or stable_id("DOC", rel_path))
            title = extract_title(meta, body, path)
            tags = tags_from_value(meta.get("tags"))
            con.execute(
                """
                INSERT OR REPLACE INTO documents
                (id, path, title, type, status, tags_json, acl, sha256, updated_at, body)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    doc_id,
                    rel_path,
                    title,
                    str(meta.get("type") or ""),
                    str(meta.get("status") or ""),
                    json.dumps(tags, ensure_ascii=False),
                    str(meta.get("acl") or ""),
                    sha256_bytes(content.encode("utf-8")),
                    str(meta.get("updated_at") or ""),
                    body,
                ),
            )
            for chunk_index, text in enumerate(chunk_text(body)):
                chunk_id = f"{doc_id}:{chunk_index}"
                con.execute(
                    "INSERT INTO chunks (id, document_id, chunk_index, text) VALUES (?, ?, ?, ?)",
                    (chunk_id, doc_id, chunk_index, text),
                )
                con.execute(
                    """
                    INSERT INTO chunks_fts (text, document_id, chunk_index, title, path)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (text, doc_id, chunk_index, title, rel_path),
                )
            indexed += 1
        con.commit()
    print(f"Indexed {indexed} Markdown document(s) into {DB_PATH}")


def fts_query(query):
    terms = re.findall(r"[\w\u4e00-\u9fff]+", query, flags=re.UNICODE)
    if not terms:
        cleaned = query.replace('"', '""')
        return f'"{cleaned}"'
    return " AND ".join(f'"{term.replace(chr(34), chr(34) * 2)}"' for term in terms)


def expand_like_terms(query):
    terms = []
    for term in [query] + re.findall(r"[\w\u4e00-\u9fff]+", query, flags=re.UNICODE):
        term = term.strip()
        if term and term not in terms:
            terms.append(term)
        cjk_runs = re.findall(r"[\u4e00-\u9fff]{2,}", term)
        for run in cjk_runs:
            for size in (3, 2):
                if len(run) < size:
                    continue
                for idx in range(0, len(run) - size + 1):
                    piece = run[idx : idx + size]
                    if piece not in terms:
                        terms.append(piece)
    return terms


def short_snippet(text, query, width=180):
    compact = re.sub(r"\s+", " ", text).strip()
    if not compact:
        return ""
    idx = compact.lower().find(query.lower())
    if idx == -1:
        idx = 0
    start = max(0, idx - width // 3)
    end = min(len(compact), start + width)
    snippet = compact[start:end]
    if start > 0:
        snippet = "..." + snippet
    if end < len(compact):
        snippet += "..."
    return snippet


def search_chunks(query, limit=5):
    with connect_db() as con:
        init_db(con)
        match = fts_query(query)
        try:
            rows = con.execute(
                """
                SELECT document_id, chunk_index, title, path, text, bm25(chunks_fts) AS rank
                FROM chunks_fts
                WHERE chunks_fts MATCH ?
                ORDER BY rank
                LIMIT ?
                """,
                (match, limit),
            ).fetchall()
        except sqlite3.Error:
            rows = []
        if rows:
            return [dict(row) for row in rows]

        like_terms = expand_like_terms(query)
        fallback = {}
        for term in like_terms:
            pattern = f"%{term}%"
            rows = con.execute(
                """
                SELECT c.document_id, c.chunk_index, d.title, d.path, c.text, 1000.0 AS rank
                FROM chunks c
                JOIN documents d ON d.id = c.document_id
                WHERE c.text LIKE ? OR d.title LIKE ?
                ORDER BY d.title, c.chunk_index
                LIMIT ?
                """,
                (pattern, pattern, max(limit * 20, 50)),
            ).fetchall()
            for row in rows:
                key = (row["document_id"], row["chunk_index"])
                item = fallback.setdefault(key, dict(row))
                text_hits = min(row["text"].count(term), 3)
                title_hits = min(row["title"].count(term), 1)
                section_boost = 0
                if "结论" in query and re.search(r"(?m)^#{1,6}\s*结论", row["text"]):
                    section_boost += 100
                if "摘要" in query and re.search(r"(?m)^#{1,6}\s*摘要", row["text"]):
                    section_boost += 60
                item["_score"] = item.get("_score", 0) + max(len(term), 1) * (text_hits + title_hits + 1) + section_boost
        ranked = sorted(
            fallback.values(),
            key=lambda row: (-row.get("_score", 0), row["path"], row["chunk_index"]),
        )
        return ranked[:limit]


def print_results(query, results):
    if not results:
        print("No results found. Try running: python kb.py index")
        return
    for idx, row in enumerate(results, 1):
        print(f"[{idx}] {row['title']}")
        print(f"    path: {row['path']}")
        print(f"    chunk: {row['chunk_index']}")
        print(f"    snippet: {short_snippet(row['text'], query)}")


def cmd_search(args):
    results = search_chunks(args.query, args.limit)
    print_results(args.query, results)


def local_ai_config():
    return {
        "base_url": os.environ.get("LOCAL_OPENAI_BASE_URL", "").rstrip("/"),
        "api_key": os.environ.get("LOCAL_OPENAI_API_KEY", ""),
        "model": os.environ.get("LOCAL_OPENAI_CHAT_MODEL", "local-model"),
    }


def chat_completion(messages, temperature=0.1):
    config = local_ai_config()
    if not config["base_url"]:
        return None, "LOCAL_OPENAI_BASE_URL is not configured."
    url = config["base_url"]
    if not url.endswith("/chat/completions"):
        url = url + "/chat/completions"
    payload = json.dumps(
        {
            "model": config["model"],
            "messages": messages,
            "temperature": temperature,
        },
        ensure_ascii=False,
    ).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if config["api_key"]:
        headers["Authorization"] = f"Bearer {config['api_key']}"
    request = urllib.request.Request(url, data=payload, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.URLError as exc:
        return None, f"Local AI request failed: {exc}"
    except json.JSONDecodeError as exc:
        return None, f"Local AI returned invalid JSON: {exc}"
    try:
        return data["choices"][0]["message"]["content"], None
    except (KeyError, IndexError, TypeError):
        return None, "Local AI response did not match OpenAI-compatible chat format."


def context_from_results(results):
    parts = []
    for idx, row in enumerate(results, 1):
        parts.append(
            f"[source {idx}]\n"
            f"title: {row['title']}\n"
            f"path: {row['path']}\n"
            f"chunk: {row['chunk_index']}\n"
            f"text:\n{row['text']}"
        )
    return "\n\n---\n\n".join(parts)


def cmd_ask(args):
    results = search_chunks(args.query, args.limit)
    if not results:
        print("No local context found. Try importing documents and running: python kb.py index")
        return
    answer, error = chat_completion(
        [
            {
                "role": "system",
                "content": (
                    "你是公司内网离线知识库助手。只能基于用户提供的检索片段回答。"
                    "如果片段不足以回答，就明确说资料不足。每个关键结论都要标注来源 path。"
                    "不要把没有来源的推测写成事实。"
                ),
            },
            {
                "role": "user",
                "content": (
                    f"问题：{args.query}\n\n"
                    "检索片段：\n"
                    f"{context_from_results(results)}\n\n"
                    "请用中文回答，并在末尾列出“来源”。"
                ),
            },
        ]
    )
    if error:
        print(f"AI not used: {error}")
        print("\nLocal retrieval results:")
        print_results(args.query, results)
        return
    print(answer)


def distillation_prompt(kind, title, meta, body, source_path):
    if kind == "experiment":
        instruction = (
            "请把实验内容蒸馏成可复用知识卡，必须输出以下小节：\n"
            "1. 一句话结论\n2. 可复用规则\n3. 关键条件\n4. 证据摘要\n5. 边界与风险\n6. 下一步建议\n7. 来源\n"
            "要求只基于原文，不要编造。"
        )
    elif kind == "literature":
        instruction = (
            "请把文献内容蒸馏成可用于内部检索的知识卡，必须输出以下小节：\n"
            "1. 研究问题\n2. 核心方法\n3. 核心发现\n4. 证据摘要\n5. 证据强度判断\n6. 局限与前提\n7. 对我们可用的点\n8. 关键词\n9. 来源\n"
            "要求只基于原文，不要编造。"
        )
    elif kind == "report":
        instruction = (
            "请把小组汇报蒸馏成行动卡，必须输出以下小节：\n"
            "1. 汇报主题\n2. 关键决定\n3. 行动项\n4. 风险与阻塞\n5. 负责人与截止时间\n6. 会议结论\n7. 来源\n"
            "要求只基于原文，不要编造。"
        )
    else:
        instruction = (
            "请把文档蒸馏成简洁知识卡，必须输出以下小节：\n"
            "1. 一句话结论\n2. 可复用规则\n3. 风险与边界\n4. 来源\n"
            "要求只基于原文，不要编造。"
        )
    return [
        {
            "role": "system",
            "content": (
                "你是离线知识蒸馏助手。你的任务是把原始材料压缩成可检索、可复用、可审计的 Markdown 知识卡。"
                "不要假装你读过原始材料之外的信息。"
            ),
        },
        {
            "role": "user",
            "content": (
                f"文档类型: {kind}\n"
                f"标题: {title}\n"
                f"路径: {source_path}\n"
                f"元数据: {json.dumps(meta, ensure_ascii=False)}\n\n"
                f"原文:\n{body[:7000]}\n\n"
                f"{instruction}"
            ),
        },
    ]


def ai_distillation(kind, title, meta, body, source_path):
    answer, error = chat_completion(distillation_prompt(kind, title, meta, body, source_path), temperature=0.2)
    if answer:
        return answer, None
    return None, error


def save_distillation(source_doc, kind, body):
    target = distill_source_path(source_doc, kind)
    meta = distill_target_meta(source_doc, source_doc["sha256"], kind)
    write_text(target, emit_frontmatter(meta) + body)
    return target


def cmd_distill(args):
    ensure_dirs()
    created = 0
    updated = 0
    with connect_db() as con:
        init_db(con)
        for path in list_markdown_documents():
            if path.is_relative_to(PROPOSALS_DIR) or path.is_relative_to(DISTILLED_DIR):
                continue
            content = read_text(path)
            meta, body = parse_markdown(content)
            rel_path = str(path.relative_to(ROOT))
            doc_id = str(meta.get("id") or stable_id("DOC", rel_path))
            title = extract_title(meta, body, path)
            source_doc = {
                "id": doc_id,
                "path": rel_path,
                "title": title,
                "sha256": sha256_bytes(content.encode("utf-8")),
            }
            kind = doc_kind(meta, path)
            if kind not in {"experiment", "literature", "report"}:
                continue
            target = distill_source_path(source_doc, kind)
            distilled_body = None
            ai_body, ai_error = ai_distillation(kind, title, meta, body, rel_path)
            if ai_body:
                distilled_body = ai_body
            else:
                distilled_body, _ = generate_distillation(meta, body, path, rel_path)
            if target.exists():
                old_meta, _ = parse_markdown(read_text(target))
                if old_meta.get("source_sha256") == source_doc["sha256"]:
                    continue
                updated += 1
            else:
                created += 1
            save_distillation(source_doc, kind, distilled_body)
        con.commit()
    print(f"Created {created} distilled note(s); updated {updated} distilled note(s).")


def heuristic_proposal(meta, body, title, path):
    tags = tags_from_value(meta.get("tags"))
    missing = []
    for field in ("summary", "conclusion"):
        if field == "summary" and "## 摘要" not in body:
            missing.append("缺少“摘要”章节")
        if field == "conclusion" and "## 结论" not in body:
            missing.append("缺少“结论”章节")
    possible_tags = ", ".join(tags) if tags else "待 AI 或人工补充"
    return (
        f"# 待审核建议：{title}\n\n"
        "## 建议摘要\n\n"
        f"请审核并完善文档 `{path}`。当前系统在无 AI 配置时只能生成结构化检查建议。\n\n"
        "## 可能标签\n\n"
        f"{possible_tags}\n\n"
        "## 冲突/缺失信息提示\n\n"
        + ("\n".join(f"- {item}" for item in missing) if missing else "- 未发现明显结构缺失。")
        + "\n\n"
        "## 引用来源\n\n"
        f"- {path}\n"
    )


def ai_proposal(meta, body, title, path):
    answer, error = chat_completion(
        [
            {
                "role": "system",
                "content": (
                    "你是离线知识库维护助手。请只基于提供的 Markdown 生成待人工审核的建议，"
                    "不要声称已经修改正式知识库。输出必须包含：建议摘要、可能标签、相关文档、"
                    "冲突/缺失信息提示、引用来源。"
                ),
            },
            {
                "role": "user",
                "content": f"文档路径：{path}\n标题：{title}\n元数据：{json.dumps(meta, ensure_ascii=False)}\n\n正文：\n{body[:6000]}",
            },
        ],
        temperature=0.2,
    )
    if answer:
        return answer
    return heuristic_proposal(meta, body, title, path) + f"\n\n_AI 未使用原因：{error}_\n"


def cmd_propose(args):
    ensure_dirs()
    created = 0
    skipped = 0
    with connect_db() as con:
        init_db(con)
        for path in list_markdown_documents():
            if path.is_relative_to(DISTILLED_DIR):
                continue
            content = read_text(path)
            source_sha = sha256_bytes(content.encode("utf-8"))
            meta, body = parse_markdown(content)
            rel_path = str(path.relative_to(ROOT))
            doc_id = str(meta.get("id") or stable_id("DOC", rel_path))
            title = extract_title(meta, body, path)
            proposal_id = f"PROP-{doc_id}"
            proposal_path = PROPOSALS_DIR / f"{slugify(proposal_id, 'proposal')}.md"
            if proposal_path.exists():
                old_meta, _ = parse_markdown(read_text(proposal_path))
                if old_meta.get("source_sha256") == source_sha:
                    skipped += 1
                    continue
            proposal_meta = {
                "id": proposal_id,
                "type": "proposal",
                "title": f"待审核建议：{title}",
                "source_document_id": doc_id,
                "source_path": rel_path,
                "source_sha256": source_sha,
                "status": "pending-review",
                "updated_at": now_iso(),
            }
            proposal_body = ai_proposal(meta, body, title, rel_path)
            write_text(proposal_path, emit_frontmatter(proposal_meta) + proposal_body)
            con.execute(
                """
                INSERT OR REPLACE INTO proposals (id, source_document_id, path, status, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (proposal_id, doc_id, str(proposal_path.relative_to(ROOT)), "pending-review", now_iso()),
            )
            created += 1
        con.commit()
    print(f"Created or updated {created} proposal(s); skipped {skipped} unchanged proposal(s).")


def cmd_demo(args):
    init_project(args)
    cmd_ingest(argparse.Namespace(source=str(SAMPLE_CSV)))
    index_documents(args)
    cmd_distill(args)
    index_documents(args)
    print("\nDemo search: 催化剂")
    print_results("催化剂", search_chunks("催化剂", 5))


def build_parser():
    parser = argparse.ArgumentParser(
        description="Offline Markdown knowledge base + local RAG CLI.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    init_cmd = sub.add_parser("init", help="Create folders, sample config, and empty SQLite index.")
    init_cmd.set_defaults(func=init_project)

    ingest_cmd = sub.add_parser("ingest", help="Import CSV/JSON experiment data into Markdown.")
    ingest_cmd.add_argument("source", help="Path to a CSV or JSON file.")
    ingest_cmd.set_defaults(func=cmd_ingest)

    index_cmd = sub.add_parser("index", help="Rebuild SQLite FTS index from Markdown.")
    index_cmd.set_defaults(func=index_documents)

    search_cmd = sub.add_parser("search", help="Search the local FTS index.")
    search_cmd.add_argument("query")
    search_cmd.add_argument("--limit", type=int, default=5)
    search_cmd.set_defaults(func=cmd_search)

    ask_cmd = sub.add_parser("ask", help="Answer with retrieved context and optional local AI.")
    ask_cmd.add_argument("query")
    ask_cmd.add_argument("--limit", type=int, default=5)
    ask_cmd.set_defaults(func=cmd_ask)

    propose_cmd = sub.add_parser("propose", help="Generate review-only proposal Markdown files.")
    propose_cmd.set_defaults(func=cmd_propose)

    distill_cmd = sub.add_parser("distill", help="Generate distilled knowledge cards from source Markdown.")
    distill_cmd.set_defaults(func=cmd_distill)

    demo_cmd = sub.add_parser("demo", help="Create sample data, index it, and run a search.")
    demo_cmd.set_defaults(func=cmd_demo)

    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        args.func(args)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
