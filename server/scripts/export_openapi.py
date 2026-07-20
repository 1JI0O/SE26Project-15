import json
from pathlib import Path

from tracelab_server.main import app

repository_root = Path(__file__).resolve().parents[2]
target = repository_root / "docs/contracts/cloud-sync.openapi.json"
target.write_text(
    json.dumps(app.openapi(), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)
print(target)
