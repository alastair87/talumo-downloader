from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.config import settings
from app.db.models import DownloadJob, DownloadJobFile, FileStatus, JobStatus, RepositoryCache, RepositoryFile
from app.db.session import get_db
from app.services.manifests import build_manifest
from app.services.runtime_tokens import drop_runtime_token, store_runtime_token
from app.services.rsync import build_rsync_command
from app.services.storage import build_job_target_path, can_fit_download
from app.worker.state_machine import ensure_transition


router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


def _job_summary(job: DownloadJob) -> dict[str, object]:
    return {
        "id": job.id,
        "repo_id": job.repo_id,
        "revision": job.revision,
        "status": job.status.value,
        "total_bytes": job.total_bytes,
        "downloaded_bytes": job.downloaded_bytes,
        "current_file": job.current_file,
        "current_file_bytes": job.current_file_bytes,
        "current_file_total_bytes": job.current_file_total_bytes,
        "speed_bytes_per_second": job.speed_bytes_per_second,
        "eta_seconds": job.eta_seconds,
        "error_message": job.error_message,
        "failure_reason": job.failure_reason,
        "target_path": job.target_path,
        "created_at": job.created_at.isoformat(),
        "completed_at": job.completed_at.isoformat() if job.completed_at else None,
        "files": [
            {
                "path": file.path,
                "size_bytes": file.size_bytes,
                "bytes_downloaded": file.bytes_downloaded,
                "status": file.status.value,
                "sha256": file.sha256,
            }
            for file in sorted(job.files, key=lambda item: item.path)
        ],
        "rsync_command": build_rsync_command(job.target_path),
    }


@router.post("/downloads", response_class=HTMLResponse)
def create_download_job(
    request: Request,
    repo_id: str = Form(...),
    revision: str = Form("main"),
    category: str = Form(settings.default_category),
    token: str = Form(""),
    selected_files: list[str] = Form(...),
    override_space_check: bool = Form(False),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    cache_entry = db.scalar(
        select(RepositoryCache)
        .where(RepositoryCache.repo_id == repo_id, RepositoryCache.revision == revision)
        .options(selectinload(RepositoryCache.files))
    )
    if cache_entry is None:
        raise HTTPException(status_code=404, detail="Repository metadata not found. Re-run inspection first.")

    selected = [file for file in cache_entry.files if file.path in selected_files]
    if not selected:
        raise HTTPException(status_code=400, detail="Select at least one file")

    total_bytes = sum(file.size_bytes for file in selected)
    fits, _, _ = can_fit_download(total_bytes)
    if not fits and not override_space_check:
        raise HTTPException(status_code=507, detail="Insufficient free space for selected files")

    target_path = build_job_target_path(repo_id=repo_id, revision=revision, category=category)
    job = DownloadJob(
        repo_id=repo_id,
        revision=revision,
        target_category=category,
        target_path=str(target_path),
        override_space_check=override_space_check,
        total_bytes=total_bytes,
        started_by_ip=request.client.host if request.client else None,
    )
    db.add(job)
    db.flush()
    for file in selected:
        db.add(
            DownloadJobFile(
                job_id=job.id,
                path=file.path,
                size_bytes=file.size_bytes,
                status=FileStatus.queued,
            )
        )
    store_runtime_token(job.id, token)
    db.commit()
    return queue_page(request, db)


@router.get("/queue", response_class=HTMLResponse)
def queue_page(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    jobs = db.scalars(
        select(DownloadJob)
        .options(selectinload(DownloadJob.files))
        .where(DownloadJob.status.in_([JobStatus.queued, JobStatus.downloading, JobStatus.paused, JobStatus.failed]))
        .order_by(DownloadJob.created_at.desc())
    ).all()
    return templates.TemplateResponse("queue.html", {"request": request, "jobs": jobs, "now": datetime.utcnow()})


@router.get("/completed", response_class=HTMLResponse)
def completed_page(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    jobs = db.scalars(
        select(DownloadJob)
        .options(selectinload(DownloadJob.files))
        .where(DownloadJob.status == JobStatus.completed)
        .order_by(DownloadJob.completed_at.desc())
    ).all()
    return templates.TemplateResponse(
        "completed.html",
        {"request": request, "jobs": jobs, "build_manifest": build_manifest, "build_rsync_command": build_rsync_command},
    )


@router.get("/api/downloads/queue")
def queue_api(db: Session = Depends(get_db)) -> dict[str, object]:
    jobs = db.scalars(
        select(DownloadJob)
        .options(selectinload(DownloadJob.files))
        .order_by(DownloadJob.created_at.desc())
        .limit(50)
    ).all()
    return {"jobs": [_job_summary(job) for job in jobs]}


@router.get("/api/downloads/{job_id}")
def job_detail(job_id: str, db: Session = Depends(get_db)) -> dict[str, object]:
    job = db.scalar(select(DownloadJob).where(DownloadJob.id == job_id).options(selectinload(DownloadJob.files)))
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return _job_summary(job)


def _mutate_job_status(job_id: str, target_status: JobStatus, db: Session) -> JSONResponse:
    job = db.get(DownloadJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    ensure_transition(job.status, target_status)
    job.status = target_status
    if target_status == JobStatus.queued:
        job.next_retry_at = None
    db.commit()
    return JSONResponse({"ok": True, "job_id": job.id, "status": job.status.value})


@router.post("/api/downloads/{job_id}/pause")
def pause_job(job_id: str, db: Session = Depends(get_db)) -> JSONResponse:
    return _mutate_job_status(job_id, JobStatus.paused, db)


@router.post("/api/downloads/{job_id}/resume")
def resume_job(job_id: str, db: Session = Depends(get_db)) -> JSONResponse:
    return _mutate_job_status(job_id, JobStatus.queued, db)


@router.post("/api/downloads/{job_id}/cancel")
def cancel_job(job_id: str, db: Session = Depends(get_db)) -> JSONResponse:
    response = _mutate_job_status(job_id, JobStatus.cancelled, db)
    drop_runtime_token(job_id)
    return response


@router.get("/downloads/{job_id}/manifest")
def manifest(job_id: str, db: Session = Depends(get_db)) -> dict[str, object]:
    job = db.scalar(select(DownloadJob).where(DownloadJob.id == job_id).options(selectinload(DownloadJob.files)))
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return build_manifest(job)
