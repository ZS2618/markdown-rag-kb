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
import unicodedata
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
import zlib


ROOT = Path(__file__).resolve().parent
VAULT_DIR = ROOT / "vault"
EXPERIMENTS_DIR = VAULT_DIR / "experiments"
CONCEPTS_DIR = VAULT_DIR / "concepts"
PROPOSALS_DIR = VAULT_DIR / "proposals"
LITERATURE_DIR = VAULT_DIR / "literature"
REPORTS_DIR = VAULT_DIR / "reports"
RAW_DIR = ROOT / "raw"
RAW_EXPERIMENTS_DIR = RAW_DIR / "experiments"
RAW_LITERATURE_DIR = RAW_DIR / "literature"
RAW_REPORTS_DIR = RAW_DIR / "reports"
RAW_EXTRACTS_DIR = RAW_DIR / "extracts"
DATA_DIR = ROOT / "data"
INDEX_DIR = ROOT / "index"
DB_PATH = INDEX_DIR / "kb.sqlite"
SAMPLE_CSV = DATA_DIR / "sample_experiments.csv"
MAX_PDF_SCAN_BYTES = 1_500_000
MAX_PDF_TEXT_CHARS = 200_000

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


def warn(message):
    print(f"warning: {message}")


def ensure_dirs():
    for path in (
        VAULT_DIR,
        EXPERIMENTS_DIR,
        CONCEPTS_DIR,
        PROPOSALS_DIR,
        LITERATURE_DIR,
        REPORTS_DIR,
        RAW_EXPERIMENTS_DIR,
        RAW_LITERATURE_DIR,
        RAW_REPORTS_DIR,
        RAW_EXTRACTS_DIR / "experiments",
        RAW_EXTRACTS_DIR / "literature",
        RAW_EXTRACTS_DIR / "reports",
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


def list_from_meta(meta, key):
    return tags_from_value(meta.get(key))


def add_unique(items, value):
    value = str(value or "").strip()
    if value and value not in items:
        items.append(value)
    return items


def markdown_table(rows):
    if not rows:
        return "无\n"
    out = ["| 字段 | 值 |", "| --- | --- |"]
    for key, value in rows:
        safe_value = str(value).replace("|", "\\|").replace("\n", " ").strip()
        out.append(f"| {key} | {safe_value} |")
    return "\n".join(out) + "\n"


def clean_extracted_text(text):
    text = text.replace("\x00", " ")
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def xml_texts(xml_bytes, tag_suffixes):
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return []
    values = []
    for node in root.iter():
        if any(node.tag.endswith(suffix) for suffix in tag_suffixes) and node.text:
            value = node.text.strip()
            if value:
                values.append(value)
    return values


def extract_docx_text(path):
    parts = []
    with zipfile.ZipFile(path) as archive:
        names = sorted(
            name
            for name in archive.namelist()
            if name == "word/document.xml"
            or name.startswith("word/header")
            or name.startswith("word/footer")
        )
        for name in names:
            texts = xml_texts(archive.read(name), ("}t", "}instrText"))
            if texts:
                parts.append("\n".join(texts))
    return clean_extracted_text("\n\n".join(parts))


def extract_pptx_text(path):
    slides = []
    with zipfile.ZipFile(path) as archive:
        names = sorted(name for name in archive.namelist() if name.startswith("ppt/slides/slide") and name.endswith(".xml"))
        for idx, name in enumerate(names, 1):
            texts = xml_texts(archive.read(name), ("}t",))
            if texts:
                slides.append(f"## Slide {idx}\n\n" + "\n".join(texts))
    return clean_extracted_text("\n\n".join(slides))


def extract_xlsx_text(path):
    with zipfile.ZipFile(path) as archive:
        shared_strings = []
        if "xl/sharedStrings.xml" in archive.namelist():
            shared_strings = xml_texts(archive.read("xl/sharedStrings.xml"), ("}t",))
        rows = []
        sheet_names = sorted(name for name in archive.namelist() if name.startswith("xl/worksheets/sheet") and name.endswith(".xml"))
        for sheet_idx, name in enumerate(sheet_names, 1):
            try:
                root = ET.fromstring(archive.read(name))
            except ET.ParseError:
                continue
            rows.append(f"## Sheet {sheet_idx}")
            for row in root.iter():
                if not row.tag.endswith("}row"):
                    continue
                cells = []
                for cell in row:
                    if not cell.tag.endswith("}c"):
                        continue
                    cell_type = cell.attrib.get("t", "")
                    value = ""
                    for child in cell:
                        if child.tag.endswith("}v") and child.text:
                            value = child.text.strip()
                        elif child.tag.endswith("}is"):
                            inline = " ".join(xml_texts(ET.tostring(child), ("}t",)))
                            if inline:
                                value = inline
                    if cell_type == "s" and value.isdigit():
                        idx = int(value)
                        if 0 <= idx < len(shared_strings):
                            value = shared_strings[idx]
                    if value:
                        cells.append(value)
                if cells:
                    rows.append(" | ".join(cells))
    return clean_extracted_text("\n".join(rows))


def pdf_text_quality(text):
    compact = text.strip()
    if not compact:
        return -100
    chars = [ch for ch in compact if not ch.isspace()]
    if not chars:
        return -100
    letters = sum(1 for ch in chars if ch.isalpha())
    digits = sum(1 for ch in chars if ch.isdigit())
    cjk = sum(1 for ch in chars if "\u4e00" <= ch <= "\u9fff")
    controls = sum(1 for ch in chars if unicodedata.category(ch)[0] == "C")
    nonchars = sum(1 for ch in chars if ch in ("\ufffe", "\uffff", "\ufffd"))
    weird = sum(1 for ch in chars if not (ch.isalnum() or ch in NOISE_ALLOWED_PUNCT))
    value = letters * 2 + digits + cjk * 3
    value -= controls * 8 + weird * 2 + nonchars * 40
    if re.search(r"[A-Za-z]{3,}", compact):
        value += 8
    if re.search(r"[\u4e00-\u9fff]", compact):
        value += 8
    if len(chars) > 200:
        value -= 20
    return value


def unescape_pdf_literal(value):
    out = bytearray()
    idx = 0
    while idx < len(value):
        byte = value[idx]
        if byte != 0x5C:
            out.append(byte)
            idx += 1
            continue
        idx += 1
        if idx >= len(value):
            break
        esc = value[idx]
        idx += 1
        escapes = {
            ord("n"): ord("\n"),
            ord("r"): ord("\r"),
            ord("t"): ord("\t"),
            ord("b"): ord("\b"),
            ord("f"): ord("\f"),
            ord("("): ord("("),
            ord(")"): ord(")"),
            ord("\\"): ord("\\"),
        }
        if esc in escapes:
            out.append(escapes[esc])
            continue
        if ord("0") <= esc <= ord("7"):
            octal = bytes([esc])
            for _ in range(2):
                if idx < len(value) and ord("0") <= value[idx] <= ord("7"):
                    octal += bytes([value[idx]])
                    idx += 1
                else:
                    break
            out.append(int(octal, 8))
            continue
        if esc in (ord("\n"), ord("\r")):
            if esc == ord("\r") and idx < len(value) and value[idx] == ord("\n"):
                idx += 1
            continue
        out.append(esc)
    return bytes(out)


def decode_pdf_hex(value):
    raw = re.sub(rb"\s+", b"", value)
    if len(raw) % 2:
        raw += b"0"
    try:
        return bytes.fromhex(raw.decode("ascii"))
    except ValueError:
        return b""


def likely_utf16_bytes(value):
    if value.startswith((b"\xfe\xff", b"\xff\xfe")):
        return True
    if len(value) < 4:
        return False
    sample = value[:200]
    even_nulls = sum(1 for idx in range(0, len(sample), 2) if sample[idx] == 0)
    odd_nulls = sum(1 for idx in range(1, len(sample), 2) if sample[idx] == 0)
    slots = max(len(sample) // 2, 1)
    return even_nulls / slots > 0.25 or odd_nulls / slots > 0.25


def decode_with_cmap(value, cmap):
    if not cmap:
        return ""
    max_len = max((len(key) for key in cmap), default=0)
    if not max_len:
        return ""
    out = []
    idx = 0
    while idx < len(value):
        matched = False
        for size in range(max_len, 0, -1):
            token = value[idx : idx + size]
            if token in cmap:
                out.append(cmap[token])
                idx += size
                matched = True
                break
        if matched:
            continue
        byte = value[idx]
        if 32 <= byte <= 126:
            out.append(chr(byte))
        idx += 1
    return "".join(out)


def decode_pdf_string(value, cmap=None):
    value = unescape_pdf_literal(value)
    candidates = []
    mapped = decode_with_cmap(value, cmap or {})
    if mapped:
        candidates.append(mapped)
    encodings = []
    if value.startswith((b"\xfe\xff", b"\xff\xfe")):
        encodings.extend(("utf-16", "utf-16-be", "utf-16-le"))
    elif likely_utf16_bytes(value):
        encodings.extend(("utf-16-be", "utf-16-le"))
    encodings.extend(("utf-8", "latin-1"))
    for encoding in encodings:
        try:
            decoded = value.decode(encoding)
            if decoded.strip():
                candidates.append(decoded)
        except UnicodeDecodeError:
            continue
    if not candidates:
        return ""
    best = max(candidates, key=pdf_text_quality)
    return best if pdf_text_quality(best) > 0 else ""


def extract_pdf_strings(data, cmap=None):
    data = data[:MAX_PDF_SCAN_BYTES]
    chunks = []
    for match in re.finditer(rb"\((?:\\.|[^\\)]){2,}\)", data, flags=re.DOTALL):
        text = decode_pdf_string(match.group(0)[1:-1], cmap)
        if re.search(r"[\w\u4e00-\u9fff]", text):
            chunks.append(text)
    for match in re.finditer(rb"<([0-9A-Fa-f\s]{8,})>", data):
        raw = decode_pdf_hex(match.group(1))
        mapped = decode_with_cmap(raw, cmap or {})
        candidates = [mapped] if mapped else []
        encodings = ("utf-16-be", "utf-16-le", "utf-8", "latin-1") if likely_utf16_bytes(raw) else ("utf-8", "latin-1")
        for encoding in encodings:
            try:
                candidates.append(raw.decode(encoding))
            except UnicodeDecodeError:
                pass
        text = max(candidates, key=pdf_text_quality) if candidates else ""
        if re.search(r"[\w\u4e00-\u9fff]", text):
            chunks.append(text)
        if sum(len(chunk) for chunk in chunks) > MAX_PDF_TEXT_CHARS:
            break
    return chunks


def iter_pdf_objects(data):
    offset = 0
    while True:
        stream_start = data.find(b"stream", offset)
        if stream_start < 0:
            break
        stream_data_start = stream_start + len(b"stream")
        if data[stream_data_start : stream_data_start + 2] == b"\r\n":
            stream_data_start += 2
        elif data[stream_data_start : stream_data_start + 1] in (b"\n", b"\r"):
            stream_data_start += 1
        stream_end = data.find(b"endstream", stream_data_start)
        if stream_end < 0:
            break
        dictionary_start = max(0, stream_start - 5000)
        obj_start = data.rfind(b"obj", dictionary_start, stream_start)
        dictionary = data[obj_start + 3 : stream_start] if obj_start >= 0 else data[dictionary_start:stream_start]
        yield 0, dictionary, data[stream_data_start:stream_end]
        offset = stream_end + len(b"endstream")


def decode_pdf_stream(dictionary, stream):
    if stream is None:
        return b""
    if any(marker in dictionary for marker in (b"/DCTDecode", b"/JPXDecode", b"/JBIG2Decode", b"/CCITTFaxDecode")):
        return b""
    if b"/Subtype" in dictionary and b"/Image" in dictionary:
        return b""
    if b"/FlateDecode" not in dictionary:
        return b""
    stream = stream.strip(b"\r\n")
    for payload in (stream, stream.strip()):
        try:
            return zlib.decompress(payload)
        except zlib.error:
            pass
        for wbits in (15, -15):
            try:
                return zlib.decompress(payload, wbits)
            except zlib.error:
                pass
    return b""


def parse_cmap_text(data):
    text = data.decode("latin-1", errors="ignore")
    cmap = {}
    for block in re.findall(r"beginbfchar(.*?)endbfchar", text, flags=re.DOTALL):
        for src, dst in re.findall(r"<([0-9A-Fa-f]+)>\s+<([0-9A-Fa-f]+)>", block):
            src_bytes = decode_pdf_hex(src.encode("ascii"))
            dst_bytes = decode_pdf_hex(dst.encode("ascii"))
            if src_bytes and dst_bytes:
                try:
                    cmap[src_bytes] = dst_bytes.decode("utf-16-be")
                except UnicodeDecodeError:
                    pass
    for start, end, first in re.findall(r"<([0-9A-Fa-f]+)>\s+<([0-9A-Fa-f]+)>\s+<([0-9A-Fa-f]+)>", text):
        start_int = int(start, 16)
        end_int = int(end, 16)
        first_int = int(first, 16)
        width = max(len(start), len(end)) // 2
        for offset, code in enumerate(range(start_int, min(end_int, start_int + 512) + 1)):
            src_bytes = code.to_bytes(width, "big")
            try:
                cmap[src_bytes] = chr(first_int + offset)
            except ValueError:
                pass
    for start, end, array_body in re.findall(r"<([0-9A-Fa-f]+)>\s+<([0-9A-Fa-f]+)>\s+\[(.*?)\]", text, flags=re.DOTALL):
        start_int = int(start, 16)
        width = len(start) // 2
        for offset, dst in enumerate(re.findall(r"<([0-9A-Fa-f]+)>", array_body)):
            src_bytes = (start_int + offset).to_bytes(width, "big")
            dst_bytes = decode_pdf_hex(dst.encode("ascii"))
            try:
                cmap[src_bytes] = dst_bytes.decode("utf-16-be")
            except UnicodeDecodeError:
                pass
    return cmap


def extract_pdf_text_operands(data, cmap):
    chunks = []
    for match in re.finditer(rb"\[(.*?)\]\s*TJ", data, flags=re.DOTALL):
        parts = extract_pdf_strings(match.group(1), cmap)
        if parts:
            chunks.append("".join(parts))
    for match in re.finditer(rb"(\((?:\\.|[^\\)]){1,}\)|<[0-9A-Fa-f\s]{2,}>)\s*(?:Tj|'|\")", data, flags=re.DOTALL):
        operand = match.group(1)
        if operand.startswith(b"("):
            text = decode_pdf_string(operand[1:-1], cmap)
        else:
            raw = decode_pdf_hex(operand[1:-1])
            text = decode_with_cmap(raw, cmap) or decode_pdf_string(raw, cmap)
        if text:
            chunks.append(text)
    return chunks


def extract_pdf_text(path):
    data = path.read_bytes()
    decoded_streams = []
    cmap = {}
    non_stream = re.sub(rb"stream\r?\n.*?\r?\nendstream", b"", data, flags=re.DOTALL)
    for obj_id, dictionary, stream in iter_pdf_objects(data):
        decoded = decode_pdf_stream(dictionary, stream)
        if not decoded:
            continue
        decoded = decoded[:MAX_PDF_SCAN_BYTES]
        decoded_streams.append((dictionary, decoded))
        if b"beginbfchar" in decoded or b"beginbfrange" in decoded:
            cmap.update(parse_cmap_text(decoded))

    chunks = []
    for dictionary, stream in decoded_streams:
        if b"beginbfchar" in stream or b"beginbfrange" in stream:
            continue
        if not any(token in stream for token in (b"BT", b"Tj", b"TJ", b"Tf", b"ET")):
            continue
        chunks.extend(extract_pdf_text_operands(stream, cmap))
        if sum(len(chunk) for chunk in chunks) > MAX_PDF_TEXT_CHARS:
            break

    cleaned = clean_extracted_text("\n".join(chunks))
    lines = list(meaningful_text_lines(cleaned, min_chars=4))
    return clean_extracted_text("\n".join(lines))


def extract_printable_strings(path, min_len=6):
    data = path.read_bytes()
    text = data.decode("latin-1", errors="ignore")
    strings = re.findall(r"[ -~\u00a0-\u00ff]{%d,}" % min_len, text)
    filtered = [item.strip() for item in strings if re.search(r"[A-Za-z0-9]", item)]
    return clean_extracted_text("\n".join(filtered[:300]))


def extract_raw_file_text(path):
    suffix = path.suffix.lower()
    if suffix == ".docx":
        return extract_docx_text(path), []
    if suffix == ".pptx":
        return extract_pptx_text(path), []
    if suffix == ".xlsx":
        return extract_xlsx_text(path), []
    if suffix == ".pdf":
        text = extract_pdf_text(path)
        warnings = [
            "PDF extraction is best-effort with Python stdlib; review output for custom-font spacing, ads, headers, and scanned pages."
        ]
        if len(text) < 80:
            warnings.append("PDF text extraction was weak; used printable-string fallback where possible.")
            text = text or extract_printable_strings(path)
        if not text:
            warnings.append("No text was extracted from this PDF; provide OCR text manually in the generated extract.")
        return text, warnings
    if suffix in {".doc", ".ppt", ".xls"}:
        text = extract_printable_strings(path)
        warnings = [f"Legacy {suffix} extraction used printable-string fallback; convert to .docx/.pptx/.xlsx for better results."]
        if not text:
            warnings.append(f"No text was extracted from legacy {suffix}; provide converted or OCR text manually.")
        return text, warnings
    if suffix in {".txt", ".md", ".csv", ".json"}:
        return read_text(path), []
    text = extract_printable_strings(path)
    warnings = ["Unknown file type; used printable-string fallback only."]
    if not text:
        warnings.append("No text was extracted from the unknown file type; provide text manually in the generated extract.")
    return text, warnings


def infer_raw_kind(path, explicit_kind=None):
    if explicit_kind:
        return explicit_kind
    try:
        rel_parts = [part.lower() for part in path.relative_to(RAW_DIR).parts]
    except ValueError:
        rel_parts = [part.lower() for part in path.parts]
    if "literature" in rel_parts:
        return "literature"
    if "reports" in rel_parts or "report" in rel_parts:
        return "report"
    if "experiments" in rel_parts or "experiment" in rel_parts:
        return "experiment"
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return "literature"
    if suffix in {".ppt", ".pptx", ".doc", ".docx"}:
        return "report"
    if suffix in {".xls", ".xlsx", ".csv", ".json"}:
        return "experiment"
    return "report"


def raw_kind_extract_dir(kind):
    if kind == "literature":
        return RAW_EXTRACTS_DIR / "literature"
    if kind == "report":
        return RAW_EXTRACTS_DIR / "reports"
    return RAW_EXTRACTS_DIR / "experiments"


def raw_extract_markdown(path, kind, title, text, warnings):
    source_sha = sha256_file(path)
    source_id = stable_id(kind.upper(), f"{path.name}:{source_sha}")
    meta = {
        "id": source_id,
        "type": "raw-extract",
        "raw_kind": kind,
        "title": title,
        "source_system": "raw-file",
        "source_id": source_id,
        "status": "extracted",
        "tags": [],
        "raw_file_path": str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path),
        "raw_file_sha256": source_sha,
        "updated_at": now_iso(),
    }
    warning_text = "\n".join(f"- {item}" for item in warnings) if warnings else "- 无"
    body = (
        f"# {title}\n\n"
        "## 摘要\n\n"
        "待蒸馏。\n\n"
        "## 提取文本\n\n"
        f"{text or '未能自动提取文本，请人工补充。'}\n\n"
        "## 提取警告\n\n"
        f"{warning_text}\n"
    )
    return source_id, emit_frontmatter(meta) + body


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
    chunks = []
    current = []
    for line in meaningful_text_lines(text):
        if line.startswith("- ") or line.startswith("* ") or line.startswith("+ "):
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
            if item and not is_noise_line(item):
                items.append(item)
    return items


def truncate_text(text, limit=180):
    compact = re.sub(r"\s+", " ", text).strip()
    if len(compact) <= limit:
        return compact
    return compact[: max(0, limit - 1)].rstrip() + "…"


NOISE_LINE_MARKERS = (
    "xmp",
    "itext",
    "adobe",
    "stream",
    "endstream",
    "endobj",
    "obj",
    "exif",
    "icc_profile",
    "photoshop",
    "instanceid",
    "bm_fig",
    "bm_cr",
    "xmlns",
)

NOISE_ALLOWED_PUNCT = set("-–—.,;:()[]{}<>/%+*#&_=/\\·•'\"“”‘’|~@$")


def is_noise_line(line):
    text = line.strip()
    if not text:
        return True
    lower = text.lower()
    if any(marker in lower for marker in NOISE_LINE_MARKERS):
        return True
    if any(marker in text for marker in ("\ufffe", "\uffff", "\ufffd")):
        return True
    if re.fullmatch(r"[\W_]+", text):
        return True
    if re.search(r"(.)\1{7,}", text):
        return True
    chars = [ch for ch in text if not ch.isspace()]
    if len(chars) < 4:
        return True
    control = sum(1 for ch in chars if unicodedata.category(ch)[0] == "C")
    if control / len(chars) > 0.1:
        return True
    non_word = sum(1 for ch in chars if not (ch.isalnum() or ch in NOISE_ALLOWED_PUNCT))
    if non_word / len(chars) > 0.45:
        return True
    if not re.search(r"[\u4e00-\u9fffA-Za-z0-9]", text):
        return True
    return False


def meaningful_text_lines(text, min_chars=12):
    for raw_line in text.splitlines():
        line = raw_line.strip().strip("|").strip()
        if len(line) < min_chars or line.startswith("#"):
            continue
        if is_noise_line(line):
            continue
        yield re.sub(r"\s+", " ", line)


def paragraph_candidates(text):
    chunks = []
    current = []
    for line in meaningful_text_lines(clean_extracted_text(text), min_chars=8):
        if not line:
            if current:
                chunks.append(" ".join(current).strip())
                current = []
            continue
        current.append(line)
    if current:
        chunks.append(" ".join(current).strip())
    return [chunk for chunk in chunks if len(chunk) >= 20]


def best_paragraph(text):
    candidates = paragraph_candidates(text)
    if not candidates:
        return ""

    def score(paragraph):
        lower = paragraph.lower()
        value = min(len(paragraph), 500) / 20.0
        if re.search(r"[.!?。！？]", paragraph):
            value += 4
        if len(paragraph.split()) > 12:
            value += 2
        if any(token in lower for token in ("this paper", "we propose", "we present", "we show", "method", "demonstrate", "introduce")):
            value += 3
        if any(marker in lower for marker in NOISE_LINE_MARKERS):
            value -= 10
        return value

    return max(candidates, key=score)


def pick_sentence(text, needles):
    sentences = [part.strip() for part in re.split(r"(?<=[。！？.!?])\s+", text) if part.strip()]
    for sentence in sentences:
        lower = sentence.lower()
        if any(needle in lower for needle in needles):
            return sentence
    return sentences[0] if sentences else ""


def doc_kind(meta, path):
    type_hint = str(meta.get("type") or "").lower()
    raw_kind = str(meta.get("raw_kind") or "").lower()
    if raw_kind in {"experiment", "literature", "report"}:
        return raw_kind
    try:
        rel_parts = [part.lower() for part in path.relative_to(RAW_EXTRACTS_DIR).parts]
    except ValueError:
        try:
            rel_parts = [part.lower() for part in path.relative_to(VAULT_DIR).parts]
        except ValueError:
            rel_parts = [part.lower() for part in path.parts]
    first_part = rel_parts[0] if rel_parts else ""
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
        return EXPERIMENTS_DIR / f"{slugify(source_id, 'experiment')}.md"
    if kind == "literature":
        return LITERATURE_DIR / f"{slugify(source_id, 'literature')}.md"
    if kind == "report":
        return REPORTS_DIR / f"{slugify(source_id, 'report')}.md"
    return CONCEPTS_DIR / f"{slugify(source_id, 'document')}.md"


def extract_experiment_atoms(meta, body):
    return {
        "summary": section_text(body, "摘要") or str(meta.get("summary") or "").strip(),
        "conditions": section_text(body, "实验条件"),
        "observations": section_text(body, "关键观察"),
        "conclusion": section_text(body, "结论") or str(meta.get("conclusion") or "").strip(),
        "raw_tags": tags_from_value(meta.get("tags")),
        "battery": extract_battery_atoms(meta, body),
    }


def extract_literature_atoms(meta, body):
    sections = extract_sections(body)
    abstract = section_text(body, "摘要", "Abstract", "概述") or str(meta.get("summary") or "").strip() or best_paragraph(body)
    abstract = abstract.strip()
    abstract_sentences = [part.strip() for part in re.split(r"(?<=[。！？.!?])\s+", abstract) if part.strip()]
    problem = section_text(body, "研究问题", "问题", "目的", "Objective")
    method = section_text(body, "方法", "Method", "Approach")
    findings = section_text(body, "结果", "结论", "Findings", "Results")
    if abstract_sentences:
        if not problem:
            problem = pick_sentence(abstract, ("challenge", "question", "understand", "interpret", "analy", "aim"))
        if not method:
            method = pick_sentence(abstract, ("method", "we propose", "we present", "combine", "use", "measure", "model"))
        if not findings:
            findings = pick_sentence(abstract, ("show", "demonstrate", "find", "result", "conclude", "allow", "enable"))
    return {
        "problem": problem,
        "method": method,
        "findings": findings,
        "limitations": section_text(body, "局限", "局限性", "Limitations"),
        "abstract": abstract or first_paragraph(body),
        "keywords": tags_from_value(meta.get("tags")) or bullet_list(sections.get("关键词", "")),
        "battery": extract_battery_atoms(meta, body),
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
        "battery": extract_battery_atoms(meta, body),
    }


BATTERY_TERMS = (
    "锂电", "锂离子", "电池", "电芯", "扣电", "软包", "圆柱", "方壳",
    "正极", "负极", "电解液", "隔膜", "集流体", "粘结剂", "导电剂",
    "ncm", "lfp", "lmfp", "lco", "lmo", "石墨", "硅碳", "硬碳", "金属锂",
    "sei", "cei", "soc", "soh", "容量", "库伦效率", "循环", "倍率", "内阻",
    "阻抗", "eis", "cv", "gitt", "xrd", "sem", "tem", "xps", "dsc",
    "lithium", "battery", "cell", "cathode", "anode", "electrolyte",
    "separator", "capacity", "retention", "impedance", "coulombic",
)


BATTERY_CATEGORIES = {
    "system": (
        "锂电", "锂离子", "电池", "电芯", "扣电", "软包", "圆柱", "方壳", "正极", "负极",
        "电解液", "隔膜", "ncm", "lfp", "lmfp", "lco", "lmo", "石墨", "硅碳", "硬碳",
        "金属锂", "cell", "cathode", "anode", "electrolyte", "separator",
    ),
    "recipe_process": (
        "配方", "比例", "浆料", "固含", "涂布", "辊压", "面密度", "压实", "烘干", "真空",
        "注液", "化成", "分容", "老化", "工艺", "synthesis", "slurry", "coating",
        "calender", "drying", "formation",
    ),
    "test_protocol": (
        "电压", "倍率", "c-rate", "循环", "充放电", "温度", "截止", "静置", "eis", "cv",
        "gitt", "测试", "voltage", "cycle", "temperature", "protocol",
    ),
    "performance": (
        "容量", "首效", "库伦效率", "保持率", "倍率性能", "能量密度", "功率", "内阻", "阻抗",
        "膨胀", "产气", "安全", "mAh", "retention", "coulombic", "impedance",
        "energy density", "swelling",
    ),
    "mechanism": (
        "sei", "cei", "枝晶", "副反应", "析锂", "裂纹", "溶解", "过渡金属", "气体",
        "失效", "机理", "界面", "阻抗增长", "dendrite", "degradation", "failure",
        "interface",
    ),
}


def extract_battery_atoms(meta, body):
    meta_text = " ".join(str(meta.get(key) or "") for key in ("title", "tags", "summary"))
    haystack = f"{meta_text}\n{body}".lower()
    is_relevant = any(term.lower() in haystack for term in BATTERY_TERMS)
    if not is_relevant:
        return {"is_relevant": False}
    return {
        "is_relevant": True,
        "system": matching_lines(body, BATTERY_CATEGORIES["system"], "原文未明确电池体系、材料对象或电芯形态。"),
        "recipe_process": matching_lines(body, BATTERY_CATEGORIES["recipe_process"], "原文未明确配方、制备或电芯工艺窗口。"),
        "test_protocol": matching_lines(body, BATTERY_CATEGORIES["test_protocol"], "原文未明确电化学测试条件。"),
        "performance": matching_lines(body, BATTERY_CATEGORIES["performance"], "原文未明确容量、效率、循环、倍率、阻抗或安全指标。"),
        "mechanism": matching_lines(body, BATTERY_CATEGORIES["mechanism"], "原文未明确失效模式或机理解释。"),
    }


def matching_lines(body, terms, fallback, limit=6):
    seen = set()
    lines = []
    for line in meaningful_text_lines(clean_extracted_text(body)):
        lower = line.lower()
        if not any(term.lower() in lower for term in terms):
            continue
        if line in seen:
            continue
        seen.add(line)
        lines.append(f"- {truncate_text(line, 180)}")
        if len(lines) >= limit:
            break
    return "\n".join(lines) if lines else fallback


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
        f"{lithium_experiment_block(atoms.get('battery'))}"
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
        f"{lithium_literature_block(atoms.get('battery'))}"
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
        f"{lithium_report_block(atoms.get('battery'))}"
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


def lithium_experiment_block(battery):
    if not battery or not battery.get("is_relevant"):
        return ""
    return (
        "## 锂电池体系与研究对象\n\n"
        f"{battery['system']}\n\n"
        "## 材料配方与工艺窗口\n\n"
        f"{battery['recipe_process']}\n\n"
        "## 电化学测试条件\n\n"
        f"{battery['test_protocol']}\n\n"
        "## 关键性能指标\n\n"
        f"{battery['performance']}\n\n"
        "## 失效机制与机理线索\n\n"
        f"{battery['mechanism']}\n\n"
    )


def lithium_literature_block(battery):
    if not battery or not battery.get("is_relevant"):
        return ""
    return (
        "## 锂电材料体系与应用场景\n\n"
        f"{battery['system']}\n\n"
        "## 可复现配方或工艺窗口\n\n"
        f"{battery['recipe_process']}\n\n"
        "## 关键性能数据\n\n"
        f"{battery['performance']}\n\n"
        "## 机理解释\n\n"
        f"{battery['mechanism']}\n\n"
    )


def lithium_report_block(battery):
    if not battery or not battery.get("is_relevant"):
        return ""
    return (
        "## 锂电项目上下文\n\n"
        f"{battery['system']}\n\n"
        "## 数据变化与性能信号\n\n"
        f"{battery['performance']}\n\n"
        "## 材料工艺决策点\n\n"
        f"{battery['recipe_process']}\n\n"
        "## 待验证机理或风险\n\n"
        f"{battery['mechanism']}\n\n"
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
        "type": kind,
        "title": f"蒸馏卡：{source_doc['title']}",
        "status": "structured-draft",
        "source_document_id": source_id,
        "source_path": source_path,
        "source_sha256": source_sha,
        "template_kind": kind,
        "supersedes": [],
        "supports": [],
        "contradicts": [],
        "related": [],
        "derived_from": [source_path],
        "version": 1,
        "review_status": "structured-draft",
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
        "type": "raw-extract",
        "raw_kind": "experiment",
        "title": title,
        "source_system": row.get("source_system") or "file-import",
        "source_id": row.get("source_id") or experiment_id,
        "status": row.get("status") or "extracted",
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


def ingest_warnings(row):
    warnings = []
    if not row.get("id") and not row.get("source_id"):
        warnings.append("missing id/source_id; generated stable hash ID")
    if not row.get("title"):
        warnings.append("missing title; used generated experiment title")
    for field in ("summary", "result", "conclusion"):
        if not row.get(field):
            warnings.append(f"missing {field}; wrote 待补充 placeholder")
    return warnings


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
    literature_path = RAW_EXTRACTS_DIR / "literature" / "LIT-2026-0001-催化剂筛选方法综述.extract.md"
    if not literature_path.exists():
        write_text(
            literature_path,
            """---
id: LIT-2026-0001
type: raw-extract
raw_kind: literature
title: 催化剂筛选方法综述
source_system: internal-reading
source_id: DOI-10.1000/example
status: extracted
tags: [催化剂, 文献, 筛选]
raw_file_path: raw/literature/LIT-2026-0001.pdf
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

    report_path = RAW_EXTRACTS_DIR / "reports" / "REP-2026-0001-催化剂筛选周报.extract.md"
    if not report_path.exists():
        write_text(
            report_path,
            """---
id: REP-2026-0001
type: raw-extract
raw_kind: report
title: 催化剂筛选周报
source_system: team-meeting
source_id: WEEKLY-2026-16
owner: 研发小组A
deadline: 2026-04-18
status: extracted
tags: [周报, 催化剂, 行动项]
raw_file_path: raw/reports/REP-2026-0001.pptx
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
        filename = f"{slugify(experiment_id, 'experiment')}-{slugify(title, 'untitled')}.extract.md"
        target = RAW_EXTRACTS_DIR / "experiments" / filename
        write_text(target, experiment_markdown(row, source_path, source_sha))
        for item in ingest_warnings(row):
            warn(f"ingest {target.relative_to(ROOT)}: {item}")
        count += 1
    print(f"Imported {count} experiment extract(s) from {source_path}")


def cmd_extract(args):
    ensure_dirs()
    source_path = (ROOT / args.source).resolve() if not Path(args.source).is_absolute() else Path(args.source)
    if not source_path.exists():
        raise FileNotFoundError(f"Raw source not found: {source_path}")
    kind = infer_raw_kind(source_path, args.kind)
    title = args.title or source_path.stem
    text, warnings = extract_raw_file_text(source_path)
    source_id, content = raw_extract_markdown(source_path, kind, title, text, warnings)
    filename = f"{slugify(source_id, 'raw')}-{slugify(title, 'untitled')}.extract.md"
    target = raw_kind_extract_dir(kind) / filename
    write_text(target, content)
    print(f"Extracted {source_path} -> {target.relative_to(ROOT)}")
    if warnings:
        for item in warnings:
            warn(item)


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


def list_raw_extract_documents():
    if not RAW_EXTRACTS_DIR.exists():
        return []
    return sorted(RAW_EXTRACTS_DIR.rglob("*.extract.md"))


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
            if not meta:
                warn(f"index {rel_path}: missing frontmatter; used path-derived metadata fallback")
            if not meta.get("id"):
                warn(f"index {rel_path}: missing id; used stable path hash fallback")
            if not meta.get("title") and not re.search(r"(?m)^#\s+(.+)$", body):
                warn(f"index {rel_path}: missing title and H1; used filename fallback")
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
        results = ranked[:limit]
        for row in results:
            row["_fallback_warning"] = "FTS5 returned no rows; used SQLite LIKE fallback search."
        return results


def print_results(query, results):
    if not results:
        print("No results found. Try running: python kb.py index")
        return
    fallback_warnings = sorted({row.get("_fallback_warning") for row in results if row.get("_fallback_warning")})
    for item in fallback_warnings:
        warn(item)
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
        warn(f"ask used local retrieval fallback because AI was not used: {error}")
        print("\nLocal retrieval results:")
        print_results(args.query, results)
        return
    fallback_warnings = sorted({row.get("_fallback_warning") for row in results if row.get("_fallback_warning")})
    for item in fallback_warnings:
        warn(item)
    print(answer)


def distillation_prompt(kind, title, meta, body, source_path):
    if kind == "experiment":
        instruction = (
            "请把实验内容蒸馏成可复用知识卡，必须输出以下小节：\n"
            "1. 一句话结论\n2. 可复用规则\n3. 关键条件\n"
            "4. 如果是锂电池研究，补充：锂电池体系与研究对象、材料配方与工艺窗口、电化学测试条件、关键性能指标、失效机制与机理线索\n"
            "5. 证据摘要\n6. 边界与风险\n7. 下一步建议\n8. 来源\n"
            "要求只基于原文，不要编造。"
        )
    elif kind == "literature":
        instruction = (
            "请把文献内容蒸馏成可用于内部检索的知识卡，必须输出以下小节：\n"
            "1. 研究问题\n2. 核心方法\n3. 核心发现\n"
            "4. 如果是锂电池文献，补充：锂电材料体系与应用场景、可复现配方或工艺窗口、关键性能数据、机理解释\n"
            "5. 证据摘要\n6. 证据强度判断\n7. 局限与前提\n8. 对我们可用的点\n9. 关键词\n10. 来源\n"
            "要求只基于原文，不要编造。"
        )
    elif kind == "report":
        instruction = (
            "请把小组汇报蒸馏成行动卡，必须输出以下小节：\n"
            "1. 汇报主题\n2. 关键决定\n"
            "3. 如果是锂电池项目汇报，补充：锂电项目上下文、数据变化与性能信号、材料工艺决策点、待验证机理或风险\n"
            "4. 行动项\n5. 风险与阻塞\n6. 负责人与截止时间\n7. 会议结论\n8. 来源\n"
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


def markdown_record(path, root=ROOT):
    content = read_text(path)
    meta, body = parse_markdown(content)
    return {
        "path": path,
        "rel_path": str(path.relative_to(root)),
        "content": content,
        "meta": meta,
        "body": body,
        "id": str(meta.get("id") or stable_id("DOC", str(path))),
        "title": extract_title(meta, body, path),
        "sha256": sha256_bytes(content.encode("utf-8")),
        "kind": doc_kind(meta, path),
    }


def raw_extract_record(path):
    record = markdown_record(path)
    record["source_doc"] = {
        "id": record["id"],
        "path": record["rel_path"],
        "title": record["title"],
        "sha256": record["sha256"],
    }
    record["target_path"] = distill_source_path(record["source_doc"], record["kind"])
    return record


def vault_records():
    return [markdown_record(path) for path in list_markdown_documents()]


def sync_plan():
    raw_records = [raw_extract_record(path) for path in list_raw_extract_documents()]
    vault_by_source = {}
    vault_by_path = {}
    for record in vault_records():
        source_id = str(record["meta"].get("source_document_id") or "")
        if source_id:
            vault_by_source[source_id] = record
        vault_by_path[record["rel_path"]] = record

    new_extracts = []
    changed_extracts = []
    unchanged_extracts = []
    stale_vault_cards = []
    raw_source_ids = {record["id"] for record in raw_records}
    for record in raw_records:
        target_rel = str(record["target_path"].relative_to(ROOT))
        target = vault_by_source.get(record["id"]) or vault_by_path.get(target_rel)
        record["target_record"] = target
        if not target:
            new_extracts.append(record)
        elif target["meta"].get("source_sha256") != record["sha256"]:
            changed_extracts.append(record)
        else:
            unchanged_extracts.append(record)

    for record in vault_records():
        source_id = str(record["meta"].get("source_document_id") or "")
        if source_id and source_id not in raw_source_ids:
            stale_vault_cards.append(record)

    return {
        "raw_records": raw_records,
        "vault_records": vault_records(),
        "new_extracts": new_extracts,
        "changed_extracts": changed_extracts,
        "unchanged_extracts": unchanged_extracts,
        "stale_vault_cards": stale_vault_cards,
    }


def relation_terms(record):
    text = f"{record['title']}\n{' '.join(tags_from_value(record['meta'].get('tags')))}\n{record['body']}"
    lower = text.lower()
    terms = set()
    for term in re.findall(r"[A-Za-z][A-Za-z0-9+./-]{2,}|[\u4e00-\u9fff]{2,}", lower):
        if len(term) >= 2:
            terms.add(term)
    for term in BATTERY_TERMS:
        if term.lower() in lower:
            terms.add(term.lower())
    return terms


def relation_score(left, right):
    left_terms = relation_terms(left)
    right_terms = relation_terms(right)
    overlap = left_terms & right_terms
    score = 0
    score += min(len(overlap), 12)
    if left["kind"] == right["kind"]:
        score += 1
    left_source = str(left["meta"].get("source_document_id") or left["id"])
    right_source = str(right["meta"].get("source_document_id") or right["id"])
    if left_source and right_source and left_source == right_source:
        score += 10
    for token in ("doi", "ncm", "lfp", "lmfp", "graphite", "石墨", "电解液", "impedance", "eis", "sei", "cei"):
        if token in overlap:
            score += 2
    return score, sorted(overlap)[:12]


def existing_relation_ids(record):
    ids = set()
    for key in ("related", "supports", "contradicts", "supersedes"):
        ids.update(list_from_meta(record["meta"], key))
    return ids


def find_related_records(record, candidates, limit=5, min_score=3):
    related = []
    existing = existing_relation_ids(record)
    for candidate in candidates:
        if candidate["id"] == record["id"] or candidate["id"] in existing:
            continue
        score, overlap = relation_score(record, candidate)
        if score >= min_score:
            related.append((score, overlap, candidate))
    related.sort(key=lambda item: (-item[0], item[2]["rel_path"]))
    return related[:limit]


def relation_section(related):
    if not related:
        return ""
    lines = ["## 关联知识", ""]
    for score, overlap, record in related:
        why = ", ".join(overlap[:6]) if overlap else "标题或主题相近"
        lines.append(f"- related: `{record['id']}` - {record['title']} (`{record['rel_path']}`), score={score}, overlap={why}")
    return "\n".join(lines) + "\n\n"


def proposed_distilled_markdown(raw_record, related):
    source_doc = raw_record["source_doc"]
    body, kind = generate_distillation(raw_record["meta"], raw_record["body"], raw_record["path"], raw_record["rel_path"])
    target = raw_record.get("target_record")
    meta = distill_target_meta(source_doc, raw_record["sha256"], kind)
    if target:
        old_meta = target["meta"]
        meta["id"] = old_meta.get("id") or meta["id"]
        meta["status"] = old_meta.get("status") or meta["status"]
        meta["review_status"] = old_meta.get("review_status") or meta["review_status"]
        meta["version"] = int(str(old_meta.get("version") or "1")) + 1
        for key in ("supersedes", "supports", "contradicts", "related"):
            meta[key] = list_from_meta(old_meta, key)
    for _, _, record in related:
        add_unique(meta["related"], record["id"])
    body = body.rstrip() + "\n\n" + relation_section(related)
    body += "## 更新记录\n\n"
    if target:
        body += f"- {now_iso()}: 根据 `{raw_record['rel_path']}` 生成更新草案, 旧版本为 v{target['meta'].get('version') or 1}。\n"
    else:
        body += f"- {now_iso()}: 根据 `{raw_record['rel_path']}` 生成新增草案。\n"
    return emit_frontmatter(meta) + body


def proposal_path_for(action, key):
    proposal_id = f"PROP-{action.upper()}-{stable_id('', key).lstrip('-')}"
    return proposal_id, PROPOSALS_DIR / f"{slugify(proposal_id, 'proposal')}.md"


def write_update_proposal(raw_record, related, force=False):
    target = raw_record.get("target_record")
    action = "update" if target else "add"
    target_path = str(raw_record["target_path"].relative_to(ROOT))
    proposal_id, proposal_path = proposal_path_for(action, f"{raw_record['rel_path']}->{target_path}")
    if proposal_path.exists() and not force:
        return False, proposal_path
    proposed = proposed_distilled_markdown(raw_record, related)
    meta = {
        "id": proposal_id,
        "type": "update-proposal",
        "action": action,
        "target_path": target_path,
        "source_extract": raw_record["rel_path"],
        "source_sha256": raw_record["sha256"],
        "status": "pending-review",
        "related": [record["id"] for _, _, record in related],
        "created_at": now_iso(),
    }
    body = (
        f"# {'更新' if action == 'update' else '新增'}建议：{raw_record['title']}\n\n"
        "## 为什么建议处理\n\n"
        + (
            f"- 源摘录 `{raw_record['rel_path']}` 的哈希不同于现有 vault 卡, 建议更新 `{target_path}`。\n"
            if action == "update"
            else f"- 源摘录 `{raw_record['rel_path']}` 还没有对应 vault 卡, 建议新增 `{target_path}`。\n"
        )
        + "- 此 proposal 只生成草案, 不会自动修改正式知识库。\n"
        + "- warning: 请人工复核来源摘录和关联关系后再 apply。\n\n"
        "## 候选关联\n\n"
        + (
            "\n".join(f"- `{record['id']}`: {record['title']} (`{record['rel_path']}`), overlap={', '.join(overlap[:6])}" for _, overlap, record in related)
            if related
            else "- 未找到高置信候选关联。"
        )
        + "\n\n## 建议写入内容\n\n"
        "<!-- BEGIN_PROPOSED_MARKDOWN -->\n"
        f"{proposed}"
        "<!-- END_PROPOSED_MARKDOWN -->\n"
    )
    write_text(proposal_path, emit_frontmatter(meta) + body)
    return True, proposal_path


def write_link_proposal(left, right, score, overlap, force=False):
    proposal_id, proposal_path = proposal_path_for("link", f"{left['id']}->{right['id']}")
    if proposal_path.exists() and not force:
        return False, proposal_path
    meta = {
        "id": proposal_id,
        "type": "link-proposal",
        "action": "link",
        "target_path": left["rel_path"],
        "related_document_id": right["id"],
        "related_path": right["rel_path"],
        "status": "pending-review",
        "created_at": now_iso(),
    }
    body = (
        f"# 关联建议：{left['title']} -> {right['title']}\n\n"
        "## 为什么建议关联\n\n"
        f"- 规则匹配分数: {score}\n"
        f"- 重叠关键词: {', '.join(overlap) if overlap else '标题或主题相近'}\n"
        f"- 目标卡: `{left['rel_path']}`\n"
        f"- 关联卡: `{right['rel_path']}`\n\n"
        "## 建议修改\n\n"
        f"- 在 `{left['rel_path']}` frontmatter 的 `related` 中加入 `{right['id']}`。\n"
        "- 在正文追加或更新 `## 关联知识` 小节。\n\n"
        "## 审核提示\n\n"
        "- warning: 这是规则生成的候选关系, 请人工确认不是误关联。\n"
    )
    write_text(proposal_path, emit_frontmatter(meta) + body)
    return True, proposal_path


def cmd_distill(args):
    ensure_dirs()
    created = 0
    updated = 0
    with connect_db() as con:
        init_db(con)
        for path in list_raw_extract_documents():
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
            target_exists = target.exists()
            if target_exists:
                old_meta, _ = parse_markdown(read_text(target))
                if old_meta.get("source_sha256") == source_doc["sha256"] and not getattr(args, "force", False):
                    continue
            distilled_body = None
            ai_body, ai_error = ai_distillation(kind, title, meta, body, rel_path)
            if ai_body:
                distilled_body = ai_body
            else:
                warn(f"distill {rel_path}: used deterministic Python fallback because local AI was not used: {ai_error}")
                distilled_body, _ = generate_distillation(meta, body, path, rel_path)
            if target_exists:
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
        return answer, None
    return heuristic_proposal(meta, body, title, path) + f"\n\n_AI 未使用原因：{error}_\n", error


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
            proposal_body, ai_error = ai_proposal(meta, body, title, rel_path)
            if ai_error:
                warn(f"propose {rel_path}: used heuristic fallback because local AI was not used: {ai_error}")
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


def print_sync_plan(plan):
    print("Sync plan")
    print(f"  raw extracts: {len(plan['raw_records'])}")
    print(f"  vault cards: {len(plan['vault_records'])}")
    print(f"  new extracts: {len(plan['new_extracts'])}")
    print(f"  changed extracts: {len(plan['changed_extracts'])}")
    print(f"  unchanged extracts: {len(plan['unchanged_extracts'])}")
    print(f"  stale vault cards: {len(plan['stale_vault_cards'])}")
    if plan["new_extracts"]:
        print("\nNew extracts:")
        for record in plan["new_extracts"]:
            print(f"  + {record['rel_path']} -> {record['target_path'].relative_to(ROOT)}")
    if plan["changed_extracts"]:
        print("\nChanged extracts:")
        for record in plan["changed_extracts"]:
            target = record.get("target_record")
            target_path = target["rel_path"] if target else str(record["target_path"].relative_to(ROOT))
            print(f"  * {record['rel_path']} -> {target_path}")
    if plan["stale_vault_cards"]:
        print("\nStale vault cards:")
        for record in plan["stale_vault_cards"]:
            warn(f"sync {record['rel_path']}: source extract is missing; review before keeping or deprecating")


def cmd_sync(args):
    ensure_dirs()
    plan = sync_plan()
    print_sync_plan(plan)
    candidates = 0
    for record in plan["new_extracts"] + plan["changed_extracts"]:
        related = find_related_records(record, plan["vault_records"], limit=args.limit)
        candidates += len(related)
    print(f"\nPossible related cards: {candidates}")
    print("Next: python kb.py update-proposals")


def cmd_update_proposals(args):
    ensure_dirs()
    plan = sync_plan()
    created = 0
    skipped = 0
    for record in plan["new_extracts"] + plan["changed_extracts"]:
        related = find_related_records(record, plan["vault_records"], limit=args.limit)
        did_create, path = write_update_proposal(record, related, force=args.force)
        if did_create:
            created += 1
            print(f"Created {path.relative_to(ROOT)}")
        else:
            skipped += 1
            print(f"Skipped existing {path.relative_to(ROOT)}")
    print(f"Created {created} update proposal(s); skipped {skipped}.")
    if plan["stale_vault_cards"]:
        warn(f"{len(plan['stale_vault_cards'])} stale vault card(s) have missing source extracts; inspect `python kb.py sync` output.")


def cmd_links(args):
    ensure_dirs()
    records = vault_records()
    created = 0
    skipped = 0
    checked = 0
    for idx, left in enumerate(records):
        existing = existing_relation_ids(left)
        for right in records[idx + 1 :]:
            if right["id"] in existing:
                continue
            score, overlap = relation_score(left, right)
            checked += 1
            if score < args.min_score:
                continue
            did_create, path = write_link_proposal(left, right, score, overlap, force=args.force)
            if did_create:
                created += 1
                print(f"Created {path.relative_to(ROOT)}")
            else:
                skipped += 1
            if created >= args.limit:
                print(f"Created {created} link proposal(s); checked {checked} pair(s); skipped {skipped}.")
                return
    print(f"Created {created} link proposal(s); checked {checked} pair(s); skipped {skipped}.")


def extract_proposed_markdown(body):
    start = "<!-- BEGIN_PROPOSED_MARKDOWN -->"
    end = "<!-- END_PROPOSED_MARKDOWN -->"
    start_idx = body.find(start)
    end_idx = body.find(end)
    if start_idx == -1 or end_idx == -1 or end_idx <= start_idx:
        return ""
    return body[start_idx + len(start) : end_idx].strip() + "\n"


def append_relation_body(body, related_id, related_path):
    entry = f"- related: `{related_id}` (`{related_path}`)"
    if entry in body:
        return body
    if re.search(r"(?m)^## 关联知识\s*$", body):
        return re.sub(r"(?m)^## 关联知识\s*$", f"## 关联知识\n\n{entry}", body, count=1)
    return body.rstrip() + "\n\n## 关联知识\n\n" + entry + "\n"


def apply_link_proposal(meta):
    target = ROOT / str(meta.get("target_path") or "")
    related_id = str(meta.get("related_document_id") or "").strip()
    related_path = str(meta.get("related_path") or "").strip()
    if not target.exists():
        raise FileNotFoundError(f"Target vault card not found: {target}")
    content = read_text(target)
    target_meta, body = parse_markdown(content)
    related = list_from_meta(target_meta, "related")
    add_unique(related, related_id)
    target_meta["related"] = related
    target_meta["updated_at"] = now_iso()
    body = append_relation_body(body, related_id, related_path)
    write_text(target, emit_frontmatter(target_meta) + body)
    return target


def mark_proposal_applied(path, meta, body):
    meta["status"] = "applied"
    meta["applied_at"] = now_iso()
    write_text(path, emit_frontmatter(meta) + body)


def cmd_apply_proposal(args):
    proposal_path = (ROOT / args.proposal).resolve() if not Path(args.proposal).is_absolute() else Path(args.proposal)
    if not proposal_path.exists():
        raise FileNotFoundError(f"Proposal not found: {proposal_path}")
    content = read_text(proposal_path)
    meta, body = parse_markdown(content)
    action = str(meta.get("action") or "").strip()
    if str(meta.get("status") or "") == "applied" and not args.force:
        warn(f"proposal {proposal_path.relative_to(ROOT)} is already applied; use --force to reapply")
        return
    if action in {"add", "update"}:
        target = ROOT / str(meta.get("target_path") or "")
        proposed = extract_proposed_markdown(body)
        if not proposed:
            raise ValueError("Proposal does not contain BEGIN/END proposed Markdown markers.")
        if target.exists() and action == "add" and not args.force:
            raise FileExistsError(f"Target already exists: {target}")
        write_text(target, proposed)
        mark_proposal_applied(proposal_path, meta, body)
        print(f"Applied {action} proposal -> {target.relative_to(ROOT)}")
    elif action == "link":
        target = apply_link_proposal(meta)
        mark_proposal_applied(proposal_path, meta, body)
        print(f"Applied link proposal -> {target.relative_to(ROOT)}")
    else:
        raise ValueError(f"Unsupported proposal action: {action}")


def cmd_demo(args):
    init_project(args)
    cmd_ingest(argparse.Namespace(source=str(SAMPLE_CSV)))
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

    ingest_cmd = sub.add_parser("ingest", help="Import CSV/JSON experiment data into raw extract Markdown.")
    ingest_cmd.add_argument("source", help="Path to a CSV or JSON file.")
    ingest_cmd.set_defaults(func=cmd_ingest)

    extract_cmd = sub.add_parser("extract", help="Extract raw PDF/Office/text files into raw extract Markdown.")
    extract_cmd.add_argument("source", help="Path to a raw PDF, DOCX, PPTX, XLSX, or text-like file.")
    extract_cmd.add_argument("--kind", choices=("experiment", "literature", "report"), help="Override inferred raw kind.")
    extract_cmd.add_argument("--title", help="Override extracted note title.")
    extract_cmd.set_defaults(func=cmd_extract)

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

    sync_cmd = sub.add_parser("sync", help="Compare raw extracts with vault cards and report incremental changes.")
    sync_cmd.add_argument("--limit", type=int, default=5, help="Max related candidates to count per changed/new extract.")
    sync_cmd.set_defaults(func=cmd_sync)

    update_cmd = sub.add_parser("update-proposals", help="Generate add/update proposals from new or changed raw extracts.")
    update_cmd.add_argument("--limit", type=int, default=5, help="Max related vault cards to include per proposal.")
    update_cmd.add_argument("--force", action="store_true", help="Overwrite existing update proposal files.")
    update_cmd.set_defaults(func=cmd_update_proposals)

    links_cmd = sub.add_parser("links", help="Generate relationship proposals between existing vault cards.")
    links_cmd.add_argument("--limit", type=int, default=20, help="Max link proposals to create.")
    links_cmd.add_argument("--min-score", type=int, default=5, help="Minimum rule score needed to propose a link.")
    links_cmd.add_argument("--force", action="store_true", help="Overwrite existing link proposal files.")
    links_cmd.set_defaults(func=cmd_links)

    apply_cmd = sub.add_parser("apply-proposal", help="Apply one reviewed add/update/link proposal to vault.")
    apply_cmd.add_argument("proposal", help="Path to a proposal Markdown file.")
    apply_cmd.add_argument("--force", action="store_true", help="Reapply or overwrite when the target already exists.")
    apply_cmd.set_defaults(func=cmd_apply_proposal)

    distill_cmd = sub.add_parser("distill", help="Generate distilled knowledge cards from raw extract Markdown.")
    distill_cmd.add_argument("--force", action="store_true", help="Regenerate cards even when source extracts are unchanged.")
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
