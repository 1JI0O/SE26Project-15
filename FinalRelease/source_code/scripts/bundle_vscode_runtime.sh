#!/usr/bin/env bash
# Sync self-contained Python runtime into vscode-extension/bundled/
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
python3 - "$ROOT" <<'PY'
from pathlib import Path
import shutil
import sys

root = Path(sys.argv[1])
bundled = root / "vscode-extension" / "bundled"
keep_pyproject = bundled / "pyproject.toml"
keep_lock = bundled / "uv.lock"
pyproject_text = keep_pyproject.read_text() if keep_pyproject.is_file() else None
lock_text = keep_lock.read_text() if keep_lock.is_file() else None

if bundled.exists():
    shutil.rmtree(bundled)
bundled.mkdir(parents=True)

src_core = root / "packages" / "tracelab_core" / "tracelab_core"
shutil.copytree(
    src_core,
    bundled / "tracelab_core",
    ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.egg-info"),
)

files = [
    "app/__init__.py",
    "app/services/__init__.py",
    "app/services/paper_parser.py",
    "app/services/document_parsers/base.py",
    "app/services/document_parsers/models.py",
    "app/services/document_parsers/geometry.py",
    "app/services/document_parsers/normalizer.py",
    "app/services/document_parsers/mineru.py",
    "app/services/document_parsers/mineru_official.py",
    "app/services/code_analysis/constants.py",
    "app/services/code_analysis/python_ast.py",
    "app/services/tensor_flow/architecture.py",
    "app/services/tensor_flow/semantic.py",
    "app/services/tensor_flow/layout.py",
    "app/services/tracing/static_candidates.py",
]
backend = root / "backend"
for rel in files:
    src = backend / rel
    dst = bundled / rel
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)

stub = '"""Bundled TraceLab subset — no re-exports."""\n'
for rel in (
    "app/services/document_parsers/__init__.py",
    "app/services/code_analysis/__init__.py",
    "app/services/tensor_flow/__init__.py",
    "app/services/tracing/__init__.py",
):
    path = bundled / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(stub)

if pyproject_text:
    keep_pyproject.write_text(pyproject_text)
else:
    keep_pyproject.write_text(
        """[project]
name = "tracelab-vscode-runtime"
version = "0.2.0"
description = "Self-contained TraceLab runtime bundled inside the VS Code extension"
requires-python = ">=3.11"
dependencies = [
  "httpx>=0.27.0",
  "pathspec>=0.12.1",
  "pypdf>=4.3.0",
]

[project.scripts]
tracelab = "tracelab_core.cli:main"

[build-system]
requires = ["setuptools>=69"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
where = ["."]
include = ["tracelab_core*", "app*"]
"""
    )
if lock_text:
    keep_lock.write_text(lock_text)

print(f"synced {bundled}")
PY

cd "$ROOT/vscode-extension/bundled"
uv lock
uv sync
echo "bundle ready"
