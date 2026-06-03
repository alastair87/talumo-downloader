from __future__ import annotations

import hashlib
from pathlib import Path

from app.db.models import DownloadJob


def compute_sha256(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def build_manifest(job: DownloadJob) -> dict[str, object]:
    files = []
    for job_file in sorted(job.files, key=lambda item: item.path):
        files.append(
            {
                "path": job_file.path,
                "size": job_file.size_bytes,
                "sha256": job_file.sha256,
            }
        )

    return {
        "repo_id": job.repo_id,
        "revision": job.revision,
        "files": files,
    }
