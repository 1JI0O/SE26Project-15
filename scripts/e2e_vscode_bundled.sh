#!/usr/bin/env bash
# End-to-end against the VSIX-bundled runtime (no monorepo PYTHONPATH).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DEMO="${ROOT}/examples/tracelab-demo"
PDF_SRC="${DEMO}/paper.pdf"
BUNDLED="${ROOT}/vscode-extension/bundled"
CONFIG="$(mktemp -t tracelab-e2e-XXXXXX.json)"

cleanup() {
  rm -f "${CONFIG}"
}
trap cleanup EXIT

if [[ -z "${MINERU_TOKEN:-}" ]]; then
  echo "MINERU_TOKEN is required" >&2
  exit 1
fi
if [[ -z "${DEEPSEEK_KEY:-}" ]]; then
  echo "DEEPSEEK_KEY is required" >&2
  exit 1
fi

bash "${ROOT}/scripts/bundle_vscode_runtime.sh"

mkdir -p "${DEMO}"
if [[ ! -f "${PDF_SRC}" ]]; then
  echo "missing ${PDF_SRC}" >&2
  exit 1
fi

cat > "${CONFIG}" <<EOF
{
  "mineru": {
    "enabled": true,
    "provider": "official",
    "base_url": "https://mineru.net/api/v4",
    "api_token": "${MINERU_TOKEN}"
  },
  "llm": {
    "enabled": true,
    "base_url": "https://api.deepseek.com/v1",
    "model": "deepseek-chat",
    "api_key": "${DEEPSEEK_KEY}"
  }
}
EOF

export PYTHONPATH="${BUNDLED}${PYTHONPATH:+:${PYTHONPATH}}"

run() {
  echo "==> $*"
  uv run --project "${BUNDLED}" python -m tracelab_core.cli --workspace "${DEMO}" "$@"
}

rm -rf "${DEMO}/.tracelab"
run init
run import-pdf --pdf "${PDF_SRC}"
run parse --config "${CONFIG}"
run analyze
run trace --config "${CONFIG}" --limit 30
run status

python3 - "${DEMO}" <<'PY'
import json
import sys
from pathlib import Path

demo = Path(sys.argv[1])
normalized = demo / ".tracelab/papers/parsed/normalized.json"
symbols = demo / ".tracelab/analysis/symbols.json"
links = demo / ".tracelab/traces/links.json"
failures = []
if not normalized.is_file():
    failures.append("missing normalized.json")
else:
    paper = json.loads(normalized.read_text())
    paras = paper.get("paragraphs") or []
    sections = paper.get("sections") or []
    if not paras and not sections:
        failures.append("empty paper content")
    print("parser", paper.get("parser"), "paragraphs", len(paras))
if not symbols.is_file() or not json.loads(symbols.read_text()):
    failures.append("empty symbols")
else:
    print("symbols", len(json.loads(symbols.read_text())))
if not links.is_file() or not (json.loads(links.read_text()).get("links") or []):
    failures.append("empty links")
else:
    print("links", len(json.loads(links.read_text())["links"]))
if failures:
    print("E2E FAILED", failures)
    raise SystemExit(1)
print("E2E BUNDLED PASSED")
PY
