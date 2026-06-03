from __future__ import annotations

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import RepositoryCache, RepositoryFile
from app.db.session import get_db
from app.services.hf_client import hf_client
from app.services.storage import can_fit_download, get_disk_snapshot


router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


def _upsert_repo_cache(session: Session, repo_id: str, revision: str, files: list[RepositoryFile]) -> RepositoryCache:
    cache_entry = session.scalar(
        select(RepositoryCache).where(RepositoryCache.repo_id == repo_id, RepositoryCache.revision == revision)
    )
    if cache_entry is None:
        cache_entry = RepositoryCache(repo_id=repo_id, revision=revision)
        session.add(cache_entry)
        session.flush()

    cache_entry.total_size_bytes = sum(file.size_bytes for file in files)
    cache_entry.file_count = len(files)
    cache_entry.validation_error = None

    session.execute(delete(RepositoryFile).where(RepositoryFile.repository_cache_id == cache_entry.id))
    for file in files:
        file.repository_cache_id = cache_entry.id
        session.add(file)

    session.flush()
    return cache_entry


@router.get("/", response_class=HTMLResponse)
def home(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    disk_snapshot = get_disk_snapshot()
    recent_jobs = []
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "app_name": settings.app_name,
            "disk": disk_snapshot,
            "recent_jobs": recent_jobs,
            "default_category": settings.default_category,
        },
    )


@router.post("/repos/inspect", response_class=HTMLResponse)
def inspect_repo_html(
    request: Request,
    repo_id: str = Form(...),
    revision: str = Form("main"),
    token: str = Form(""),
    category: str = Form(settings.default_category),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    try:
        inspection = hf_client.inspect_repo(repo_id=repo_id.strip(), revision=revision.strip() or "main", token=token or None)
    except Exception as exc:
        return templates.TemplateResponse(
            "index.html",
            {
                "request": request,
                "app_name": settings.app_name,
                "disk": get_disk_snapshot(),
                "recent_jobs": [],
                "default_category": settings.default_category,
                "error_message": str(exc),
            },
            status_code=400,
        )

    files = [
        RepositoryFile(
            repo_id=inspection.repo_id,
            revision=inspection.revision,
            path=file.path,
            size_bytes=file.size_bytes,
            file_type=file.extension,
            last_modified=file.last_modified,
            etag=file.etag,
        )
        for file in inspection.files
    ]
    _upsert_repo_cache(db, inspection.repo_id, inspection.revision, files)
    fits, disk_snapshot, required_bytes = can_fit_download(inspection.total_size_bytes)
    return templates.TemplateResponse(
        "inspect.html",
        {
            "request": request,
            "repo_id": inspection.repo_id,
            "revision": inspection.revision,
            "token": token,
            "category": category,
            "files": inspection.files,
            "disk": disk_snapshot,
            "fits": fits,
            "required_bytes": required_bytes,
            "total_size_bytes": inspection.total_size_bytes,
        },
    )


@router.post("/api/repos/validate")
def validate_repo(payload: dict[str, str]) -> dict[str, object]:
    repo_id = payload.get("repo_id", "").strip()
    revision = payload.get("revision", "main").strip() or "main"
    token = payload.get("token") or None
    if not repo_id:
        raise HTTPException(status_code=400, detail="repo_id is required")
    inspection = hf_client.inspect_repo(repo_id=repo_id, revision=revision, token=token)
    return {
        "valid": True,
        "repo_id": inspection.repo_id,
        "revision": inspection.revision,
        "file_count": len(inspection.files),
        "total_size_bytes": inspection.total_size_bytes,
    }


@router.get("/api/repos/{repo_id:path}/files")
def repo_files(repo_id: str, revision: str = "main", token: str | None = None) -> dict[str, object]:
    inspection = hf_client.inspect_repo(repo_id=repo_id, revision=revision, token=token)
    return {
        "repo_id": inspection.repo_id,
        "revision": inspection.revision,
        "files": [
            {
                "path": file.path,
                "size_bytes": file.size_bytes,
                "file_type": file.file_type,
                "extension": file.extension,
                "last_modified": file.last_modified,
            }
            for file in inspection.files
        ],
    }
