#!/usr/bin/env python3
"""
One-command local embedding setup.

Examples:
  python tools/setup_embedding.py --backend flagembedding --model-path models/bge-m3
  python tools/setup_embedding.py --backend sentence-transformers --model-path models/bge-m3
  python tools/setup_embedding.py --backend node --model-path models/bge-small-zh-v1.5
"""

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"


class SetupError(RuntimeError):
    pass


def rel(path):
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def tail(text, limit=1600):
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return "..." + text[-limit:]


def command_text(cmd):
    return " ".join(str(part) for part in cmd)


def run(cmd, *, cwd=ROOT, input_text=None, timeout=900, dry_run=False):
    print(f"> {command_text(cmd)}")
    if dry_run:
        return subprocess.CompletedProcess(cmd, 0, "", "")
    try:
        proc = subprocess.run(
            [str(part) for part in cmd],
            cwd=str(cwd),
            input=input_text,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as exc:
        raise SetupError(f"Command not found: {cmd[0]}") from exc
    except subprocess.TimeoutExpired as exc:
        raise SetupError(f"Command timed out after {timeout}s: {command_text(cmd)}") from exc
    if proc.returncode != 0:
        details = []
        if proc.stdout.strip():
            details.append("stdout:\n" + tail(proc.stdout))
        if proc.stderr.strip():
            details.append("stderr:\n" + tail(proc.stderr))
        detail_text = "\n\n".join(details) or "no output"
        raise SetupError(f"Command failed with exit code {proc.returncode}: {command_text(cmd)}\n\n{detail_text}")
    return proc


def ensure_repo_root():
    if not (ROOT / "kb.py").exists():
        raise SetupError(f"Cannot find kb.py at expected repo root: {ROOT}")


def venv_python(venv_dir):
    if os.name == "nt":
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


def env_command_path(path):
    value = rel(path)
    if os.name == "nt":
        return value.replace("/", "\\")
    return value


def copy_env_if_missing(dry_run=False):
    env_path = ROOT / ".env"
    example = ROOT / ".env.example"
    if env_path.exists():
        print("ok: .env already exists")
        return
    if not example.exists():
        raise SetupError(".env does not exist and .env.example is missing.")
    print("Creating .env from .env.example")
    if not dry_run:
        shutil.copyfile(example, env_path)


def read_env_lines():
    env_path = ROOT / ".env"
    if not env_path.exists():
        return []
    return env_path.read_text(encoding="utf-8").splitlines()


def upsert_env(values, dry_run=False):
    env_path = ROOT / ".env"
    lines = read_env_lines()
    output = []
    seen = set()
    for line in lines:
        stripped = line.strip()
        candidate = stripped[1:].lstrip() if stripped.startswith("#") else stripped
        key = candidate.split("=", 1)[0].strip() if "=" in candidate else ""
        if key in values:
            if key not in seen:
                output.append(f"{key}={values[key]}")
                seen.add(key)
        else:
            output.append(line)
    if output and output[-1].strip():
        output.append("")
    for key, value in values.items():
        if key not in seen:
            output.append(f"{key}={value}")
    print("Updating .env")
    for key in values:
        print(f"  {key}={values[key]}")
    if not dry_run:
        env_path.write_text("\n".join(output).rstrip() + "\n", encoding="utf-8", newline="\n")


def install_python_backend(args, requirement_file):
    venv_dir = ROOT / args.venv
    py = venv_python(venv_dir)
    if not py.exists():
        run([args.python, "-m", "venv", venv_dir], dry_run=args.dry_run)
    else:
        print(f"ok: virtualenv already exists at {rel(venv_dir)}")
    if args.no_install:
        print("skip: dependency installation disabled by --no-install")
        return py
    pip_cmd = [py, "-m", "pip", "install"]
    if args.pip_index_url:
        pip_cmd.extend(["-i", args.pip_index_url])
    if args.offline_wheel_dir:
        wheel_dir = Path(args.offline_wheel_dir)
        pip_cmd.extend(["--no-index", "--find-links", wheel_dir])
    pip_cmd.extend(["-r", ROOT / requirement_file])
    run(pip_cmd, timeout=args.install_timeout, dry_run=args.dry_run)
    return py


def configure_flagembedding(args):
    py = install_python_backend(args, "requirements-embedding-flagembedding.txt")
    cmd = f"{env_command_path(py)} tools\\embed_flagembedding_bgem3.py" if os.name == "nt" else f"{env_command_path(py)} tools/embed_flagembedding_bgem3.py"
    return {
        "LOCAL_EMBEDDING_CMD": cmd,
        "LOCAL_EMBEDDING_MODEL_PATH": args.model_path,
        "LOCAL_EMBEDDING_BATCH_SIZE": str(args.batch_size or 8),
        "LOCAL_EMBEDDING_MAX_SEQ_LENGTH": str(args.max_seq_length or 8192),
        "LOCAL_EMBEDDING_USE_FP16": "true" if args.use_fp16 else "false",
        "LOCAL_EMBEDDING_LOCAL_FILES_ONLY": "true",
        "LOCAL_EMBEDDING_NORMALIZE": "true",
    }


def configure_sentence_transformers(args):
    py = install_python_backend(args, "requirements-embedding-sentence-transformers.txt")
    cmd = f"{env_command_path(py)} tools\\embed_sentence_transformers.py" if os.name == "nt" else f"{env_command_path(py)} tools/embed_sentence_transformers.py"
    return {
        "LOCAL_EMBEDDING_CMD": cmd,
        "LOCAL_EMBEDDING_MODEL_PATH": args.model_path,
        "LOCAL_EMBEDDING_BATCH_SIZE": str(args.batch_size or 16),
        "LOCAL_EMBEDDING_LOCAL_FILES_ONLY": "true",
        "LOCAL_EMBEDDING_NORMALIZE": "true",
    }


def configure_node(args):
    node = shutil.which(args.node)
    npm = shutil.which(args.npm)
    if not node:
        raise SetupError(f"Node executable not found: {args.node}")
    if not npm:
        raise SetupError(f"npm executable not found: {args.npm}")
    package_json = ROOT / "package.json"
    if not package_json.exists():
        print("Creating package.json from tools/embedding-package.example.json")
        if not args.dry_run:
            shutil.copyfile(TOOLS / "embedding-package.example.json", package_json)
    else:
        print("ok: package.json already exists")
    if args.no_install:
        print("skip: npm install disabled by --no-install")
    else:
        npm_cmd = [npm, "install"]
        if args.npm_offline:
            npm_cmd.append("--offline")
        run(npm_cmd, timeout=args.install_timeout, dry_run=args.dry_run)
    return {
        "LOCAL_EMBEDDING_CMD": f"{args.node} tools\\embed_transformersjs.mjs" if os.name == "nt" else f"{args.node} tools/embed_transformersjs.mjs",
        "LOCAL_EMBEDDING_MODEL_PATH": args.model_path,
        "LOCAL_EMBEDDING_LOCAL_FILES_ONLY": "true",
        "LOCAL_EMBEDDING_NORMALIZE": "true",
        "LOCAL_EMBEDDING_POOLING": args.pooling,
        "LOCAL_EMBEDDING_DTYPE": args.dtype,
    }


def check_model_path(model_path):
    path = ROOT / model_path
    if path.exists():
        print(f"ok: model path exists: {model_path}")
        return True
    print(f"warning: model path does not exist yet: {model_path}")
    print("warning: copy the approved model files there before running embed-index.")
    return False


def smoke_test(env_values, args):
    if args.skip_smoke_test:
        print("skip: smoke test disabled by --skip-smoke-test")
        return
    command = env_values["LOCAL_EMBEDDING_CMD"]
    payload = json.dumps({"input": ["锂金属负极阻抗上升"]}, ensure_ascii=False)
    env = os.environ.copy()
    env.update(env_values)
    print("> smoke test LOCAL_EMBEDDING_CMD")
    if args.dry_run:
        return
    proc = subprocess.run(
        command,
        cwd=str(ROOT),
        shell=True,
        input=payload,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=args.smoke_timeout,
        env=env,
        check=False,
    )
    if proc.returncode != 0:
        raise SetupError(
            "Embedding smoke test failed. The environment was configured, but the model command cannot run yet.\n\n"
            f"command: {command}\n"
            f"stdout:\n{tail(proc.stdout)}\n\n"
            f"stderr:\n{tail(proc.stderr)}\n\n"
            "Common fixes: confirm the model path exists, install the selected optional dependency, "
            "or rerun with --skip-smoke-test if the model files will be copied later."
        )
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise SetupError(
            "Embedding smoke test returned non-JSON stdout. Logs must go to stderr, stdout must be JSON.\n\n"
            f"stdout:\n{tail(proc.stdout)}"
        ) from exc
    rows = data.get("data") if isinstance(data, dict) else data
    if not isinstance(rows, list) or not rows:
        raise SetupError("Embedding smoke test JSON did not contain a non-empty vector list.")
    first = rows[0].get("embedding") if isinstance(rows[0], dict) else rows[0]
    if not isinstance(first, list) or not first:
        raise SetupError("Embedding smoke test did not return a valid embedding vector.")
    print(f"ok: smoke test returned vector dimension {len(first)}")


def build_parser():
    parser = argparse.ArgumentParser(description="Configure local embedding for this knowledge-base project.")
    parser.add_argument("--backend", choices=("flagembedding", "sentence-transformers", "node"), default="flagembedding")
    parser.add_argument("--model-path", default=None, help="Local model directory, for example models/bge-m3.")
    parser.add_argument("--venv", default=".venv-embed", help="Virtualenv directory for Python backends.")
    parser.add_argument("--python", default=sys.executable, help="Python executable used to create the embedding venv.")
    parser.add_argument("--node", default="node", help="Node executable for the node backend.")
    parser.add_argument("--npm", default="npm", help="npm executable for the node backend.")
    parser.add_argument("--batch-size", type=int, help="Embedding batch size.")
    parser.add_argument("--max-seq-length", type=int, help="Maximum sequence length for FlagEmbedding.")
    parser.add_argument("--use-fp16", action="store_true", help="Use fp16 for FlagEmbedding.")
    parser.add_argument("--pooling", default="mean", help="Transformers.js pooling mode.")
    parser.add_argument("--dtype", default="q8", help="Transformers.js dtype, for example q8 or fp32.")
    parser.add_argument("--offline-wheel-dir", help="Install Python packages from a local wheel directory.")
    parser.add_argument("--pip-index-url", help="Install Python packages from an intranet pip mirror.")
    parser.add_argument("--npm-offline", action="store_true", help="Run npm install --offline.")
    parser.add_argument("--no-install", action="store_true", help="Only write .env; do not install Python or Node dependencies.")
    parser.add_argument("--skip-smoke-test", action="store_true", help="Skip running one embedding request after setup.")
    parser.add_argument("--install-timeout", type=int, default=1800)
    parser.add_argument("--smoke-timeout", type=int, default=300)
    parser.add_argument("--dry-run", action="store_true")
    return parser


def default_model_path(backend):
    if backend == "node":
        return "models/bge-small-zh-v1.5"
    return "models/bge-m3"


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    args.model_path = args.model_path or default_model_path(args.backend)
    try:
        ensure_repo_root()
        copy_env_if_missing(dry_run=args.dry_run)
        if args.backend == "flagembedding":
            env_values = configure_flagembedding(args)
        elif args.backend == "sentence-transformers":
            env_values = configure_sentence_transformers(args)
        else:
            env_values = configure_node(args)
        upsert_env(env_values, dry_run=args.dry_run)
        model_exists = check_model_path(args.model_path)
        if not model_exists and not args.skip_smoke_test:
            raise SetupError("Model path is missing. Copy model files first, or rerun with --skip-smoke-test.")
        smoke_test(env_values, args)
    except SetupError as exc:
        print(f"\nERROR: {exc}", file=sys.stderr)
        return 1
    print("\nEmbedding setup complete.")
    print("Next:")
    print("  python kb.py index")
    print("  python kb.py embed-index")
    print('  python kb.py semantic-search "EIS 阻抗增长和 SEI 的关系"')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
