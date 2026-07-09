from __future__ import annotations

from fastapi import APIRouter

from app.services.storage import get_disk_snapshot


router = APIRouter()


@router.get("/api/system/disk")
def disk_status() -> dict[str, int]:
    snapshot = get_disk_snapshot()
    return {
        "total_bytes": snapshot.total_bytes,
        "used_bytes": snapshot.used_bytes,
        "free_bytes": snapshot.free_bytes,
        "models_size_bytes": snapshot.models_size_bytes,
        "incomplete_size_bytes": snapshot.incomplete_size_bytes,
        "hf_cache_size_bytes": snapshot.hf_cache_size_bytes,
    }


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
