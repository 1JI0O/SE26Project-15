from pathlib import Path

from app.services.code_analysis.constants import (
    BLOCKED_BINARY_EXTENSIONS,
    EDITOR_READABLE_BASENAMES,
    EDITOR_READABLE_EXTENSIONS,
)


def is_editor_readable_file(path: str) -> bool:
    file_path = Path(path)
    suffix = file_path.suffix.lower()
    if suffix in BLOCKED_BINARY_EXTENSIONS:
        return False
    if suffix in EDITOR_READABLE_EXTENSIONS:
        return True
    return file_path.name.lower() in EDITOR_READABLE_BASENAMES


def language_for(path: str) -> str:
    suffix = Path(path).suffix.lower()
    if suffix == ".py":
        return "python"
    if suffix in {".md", ".rst"}:
        return "docs"
    if suffix in {".yaml", ".yml", ".toml", ".json"}:
        return "config"
    if not is_editor_readable_file(path):
        return "binary"
    return "other"
