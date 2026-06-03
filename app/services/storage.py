from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from app.config import settings


@dataclass(slots=True)
class DiskSnapshot:
    total_bytes: int
    used_bytes: int
    free_bytes: int
    models_size_bytes: int
    incomplete_size_bytes: int
    hf_cache_size_bytes: int


def sanitize_repo_id(repo_id: str) -> str:
    return repo_id.strip().replace("..", "").replace(" ", "-").replace("/", "--")


def build_job_target_path(repo_id: str, revision: str, category: str | None = None) -> Path:
    category_name = category or settings.default_category
    return settings.models_root / category_name / sanitize_repo_id(repo_id) / revision


def directory_size(path: Path) -> int:
    if not path.exists():
        return 0
    total = 0
    for file_path in path.rglob("*"):
        if file_path.is_file():
            total += file_path.stat().st_size
    return total


def get_disk_snapshot() -> DiskSnapshot:
    usage = shutil.disk_usage(settings.models_root)
    return DiskSnapshot(
        total_bytes=usage.total,
        used_bytes=usage.used,
        free_bytes=usage.free,
        models_size_bytes=directory_size(settings.models_root),
        incomplete_size_bytes=directory_size(settings.incomplete_root),
        hf_cache_size_bytes=directory_size(settings.hf_cache_root),
    )


def required_bytes_with_overhead(total_bytes: int) -> int:
    return int(total_bytes * 1.05)


def can_fit_download(total_bytes: int) -> tuple[bool, DiskSnapshot, int]:
    snapshot = get_disk_snapshot()
    required = required_bytes_with_overhead(total_bytes) + settings.free_space_threshold_bytes
    return snapshot.free_bytes >= required, snapshot, required
