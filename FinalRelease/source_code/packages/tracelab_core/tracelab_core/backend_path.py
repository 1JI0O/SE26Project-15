"""Ensure analysis backend modules are importable when running tracelab CLI."""

from __future__ import annotations

import sys
from pathlib import Path


def ensure_backend_path() -> Path:
    """
    Resolve the Python path root that contains ``app/``.

    - Bundled VSIX: ``vscode-extension/bundled/`` (sibling of ``tracelab_core/``)
    - Monorepo CLI: ``<repo>/backend``
    """
    here = Path(__file__).resolve()
    bundled_root = here.parents[1]
    if (bundled_root / "app").is_dir():
        root = bundled_root
    else:
        root = here.parents[3] / "backend"

    root_str = str(root)
    if root_str not in sys.path:
        sys.path.insert(0, root_str)
    return root
