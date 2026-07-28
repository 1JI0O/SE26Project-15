#!/usr/bin/env bash
# End-to-end CLI smoke for TraceLab VS Code core.
# Usage:
#   MINERU_TOKEN=... DEEPSEEK_KEY=... ./scripts/e2e_vscode_core.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DEMO="${ROOT}/examples/tracelab-demo"
PDF_SRC="${DEMO}/paper.pdf"
BACKEND="${ROOT}/backend"
CORE="${ROOT}/packages/tracelab_core"
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

mkdir -p "${DEMO}"

# Ensure demo PDF mentions symbols in nn.py / train.py (hand-written minimal PDF).
if [[ ! -f "${PDF_SRC}" ]]; then
  python3 - "${PDF_SRC}" <<'PY'
from pathlib import Path
import sys
Path(sys.argv[1]).write_bytes(b"""%PDF-1.4
1 0 obj<< /Type /Catalog /Pages 2 0 R >>endobj
2 0 obj<< /Type /Pages /Kids [3 0 R] /Count 1 >>endobj
3 0 obj<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources<< /Font<< /F1 5 0 R >> >> >>endobj
4 0 obj<< /Length 380 >>stream
BT
/F1 14 Tf
72 720 Td
(Tiny Transformer with MultiHeadAttention) Tj
0 -24 Td
(We propose MultiHeadAttention using scaled dot-product attention.) Tj
0 -20 Td
(TinyTransformerBlock stacks attention and a feed-forward network.) Tj
0 -20 Td
(LayerNorm and GELU stabilize TinyTransformerBlock training.) Tj
0 -20 Td
(The train_step function optimizes mean squared loss on batch tensors.) Tj
ET
endstream
endobj
5 0 obj<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>endobj
xref
0 6
0000000000 65535 f 
0000000009 00000 n 
0000000058 00000 n 
0000000115 00000 n 
0000000266 00000 n 
0000000700 00000 n 
trailer<< /Size 6 /Root 1 0 R >>
startxref
777
%%EOF
""")
print("wrote", sys.argv[1])
PY
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

export PYTHONPATH="${BACKEND}:${CORE}${PYTHONPATH:+:${PYTHONPATH}}"

run() {
  echo "==> $*"
  uv run --project "${BACKEND}" python -m tracelab_core.cli --workspace "${DEMO}" "$@"
}

rm -rf "${DEMO}/.tracelab"
run init
run import-pdf --pdf "${DEMO}/paper.pdf"
run parse --config "${CONFIG}"
run analyze
run trace --config "${CONFIG}" --limit 30
STATUS="$(run status)"
echo "${STATUS}"

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
        failures.append("normalized.json has empty paragraphs/sections")
    print(f"paper parser={paper.get('parser')!r} paragraphs={len(paras)} sections={len(sections)}")

if not symbols.is_file():
    failures.append("missing symbols.json")
else:
    data = json.loads(symbols.read_text())
    if not data:
        failures.append("symbols.json empty")
    print(f"symbols={len(data)}")

if not links.is_file():
    failures.append("missing links.json")
else:
    payload = json.loads(links.read_text())
    items = payload.get("links") or []
    if not items:
        failures.append("links.json has zero links")
    print(f"links={len(items)}")

if failures:
    print("E2E FAILED:")
    for item in failures:
        print(f" - {item}")
    raise SystemExit(1)
print("E2E PASSED")
PY
