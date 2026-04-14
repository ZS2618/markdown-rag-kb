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
    for path in (VAULT_DIR, EXPERIMENTS_DIR, CONCEPTS_DIR, PROPOSALS_DIR, DATA_DIR, INDEX_DIR):
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
