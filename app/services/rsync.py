from __future__ import annotations

from pathlib import Path


def quote_path(path: Path | str) -> str:
    return f'"{path}"'


def build_rsync_command(source_path: Path | str, destination: str = "user@desktop:/models/") -> str:
    return f"rsync -av --partial --progress {quote_path(source_path)}/ {quote_path(destination)}"
