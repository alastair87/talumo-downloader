from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from huggingface_hub import HfApi


@dataclass(slots=True)
class RepoFileEntry:
    path: str
    size_bytes: int
    file_type: str
    last_modified: str | None
    etag: str | None

    @property
    def extension(self) -> str:
        return Path(self.path).suffix.lstrip(".") or "unknown"


@dataclass(slots=True)
class RepoInspection:
    repo_id: str
    revision: str
    files: list[RepoFileEntry]

    @property
    def total_size_bytes(self) -> int:
        return sum(file.size_bytes for file in self.files)


def _normalize_file_metadata(item: object) -> RepoFileEntry | None:
    path = getattr(item, "rfilename", None) or getattr(item, "path", None)
    if not path:
        return None

    lfs_data = getattr(item, "lfs", None)
    size_bytes = getattr(item, "size", None) or 0
    etag = getattr(item, "blob_id", None)
    if isinstance(lfs_data, dict):
        size_bytes = lfs_data.get("size") or size_bytes
        etag = lfs_data.get("oid") or etag

    return RepoFileEntry(
        path=path,
        size_bytes=int(size_bytes or 0),
        file_type=Path(path).suffix.lstrip(".") or "file",
        last_modified=str(getattr(item, "last_modified", None) or "") or None,
        etag=etag,
    )


class HuggingFaceClient:
    def __init__(self) -> None:
        self.api = HfApi()

    def inspect_repo(self, repo_id: str, revision: str = "main", token: str | None = None) -> RepoInspection:
        model_info = self.api.model_info(repo_id=repo_id, revision=revision, files_metadata=True, token=token)
        files: list[RepoFileEntry] = []
        for sibling in model_info.siblings or []:
            metadata = _normalize_file_metadata(sibling)
            if metadata is not None:
                files.append(metadata)

        return RepoInspection(repo_id=repo_id, revision=revision, files=sorted(files, key=lambda item: item.path))


hf_client = HuggingFaceClient()
