from __future__ import annotations

import logging
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import select

from app.config import settings
from app.db.models import DownloadJob, DownloadJobFile, FileStatus, JobStatus
from app.db.session import SessionLocal, session_scope
from app.services.downloader import DownloadCancelled, DownloadPaused, ProgressUpdate, download_file
from app.services.manifests import compute_sha256
from app.services.runtime_tokens import drop_runtime_token, get_runtime_token
from app.worker.state_machine import ensure_transition


logger = logging.getLogger(__name__)


class DownloadWorker:
    def __init__(self) -> None:
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._executor: ThreadPoolExecutor | None = None
        self._futures: dict[str, Future[None]] = {}

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._executor = ThreadPoolExecutor(max_workers=settings.max_concurrent_downloads)
        self._reconcile_inflight_jobs()
        self._thread = threading.Thread(target=self._run_loop, name="download-worker", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)
        if self._executor is not None:
            self._executor.shutdown(wait=False, cancel_futures=True)
            self._executor = None

    def _reconcile_inflight_jobs(self) -> None:
        with session_scope() as session:
            jobs = session.scalars(select(DownloadJob).where(DownloadJob.status == JobStatus.downloading)).all()
            for job in jobs:
                job.status = JobStatus.queued
                job.error_message = "Recovered after service restart"
                for job_file in job.files:
                    if job_file.status == FileStatus.downloading:
                        job_file.status = FileStatus.queued

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            self._cleanup_futures()
            available_slots = settings.max_concurrent_downloads - len(self._futures)
            if available_slots > 0:
                self._submit_jobs(available_slots)
            self._stop_event.wait(settings.worker_poll_seconds)

    def _cleanup_futures(self) -> None:
        done_ids = [job_id for job_id, future in self._futures.items() if future.done()]
        for job_id in done_ids:
            future = self._futures.pop(job_id)
            try:
                future.result()
            except Exception:
                logger.exception("Background job failed", extra={"job_id": job_id})

    def _submit_jobs(self, limit: int) -> None:
        with session_scope() as session:
            now = datetime.utcnow()
            jobs = session.scalars(
                select(DownloadJob)
                .where(DownloadJob.status == JobStatus.queued)
                .where((DownloadJob.next_retry_at.is_(None)) | (DownloadJob.next_retry_at <= now))
                .order_by(DownloadJob.created_at.asc())
                .limit(limit)
            ).all()

        for job in jobs:
            if job.id in self._futures:
                continue
            if self._executor is None:
                break
            self._futures[job.id] = self._executor.submit(self._execute_job, job.id)

    def _execute_job(self, job_id: str) -> None:
        try:
            with session_scope() as session:
                job = session.get(DownloadJob, job_id)
                if job is None or job.status != JobStatus.queued:
                    return
                ensure_transition(job.status, JobStatus.downloading)
                job.status = JobStatus.downloading
                job.started_at = job.started_at or datetime.utcnow()
                job.error_message = None
                job.failure_reason = None

            with session_scope() as session:
                job = session.get(DownloadJob, job_id)
                if job is None:
                    return
                token = get_runtime_token(job.id)
                for job_file in sorted(job.files, key=lambda item: item.path):
                    if job_file.status == FileStatus.completed:
                        continue
                    self._download_job_file(job_id, job_file.id, token)

            with session_scope() as session:
                job = session.get(DownloadJob, job_id)
                if job is None:
                    return
                ensure_transition(job.status, JobStatus.completed)
                job.status = JobStatus.completed
                job.completed_at = datetime.utcnow()
                job.current_file = None
                job.current_file_bytes = 0
                job.current_file_total_bytes = 0
                job.eta_seconds = 0
            drop_runtime_token(job_id)
        except DownloadPaused:
            with session_scope() as session:
                job = session.get(DownloadJob, job_id)
                if job is not None:
                    ensure_transition(job.status, JobStatus.paused)
                    job.status = JobStatus.paused
        except DownloadCancelled:
            with session_scope() as session:
                job = session.get(DownloadJob, job_id)
                if job is not None:
                    ensure_transition(job.status, JobStatus.cancelled)
                    job.status = JobStatus.cancelled
                    job.completed_at = datetime.utcnow()
            drop_runtime_token(job_id)
        except Exception as exc:
            with session_scope() as session:
                job = session.get(DownloadJob, job_id)
                if job is None:
                    return
                job.retry_count += 1
                job.failure_reason = str(exc)
                if job.retry_count <= settings.max_retries:
                    job.status = JobStatus.queued
                    job.error_message = f"Retry {job.retry_count} scheduled after failure"
                    job.next_retry_at = datetime.utcnow() + timedelta(seconds=settings.retry_base_seconds * (2 ** (job.retry_count - 1)))
                else:
                    ensure_transition(job.status, JobStatus.failed)
                    job.status = JobStatus.failed
                    job.completed_at = datetime.utcnow()
                    job.error_message = str(exc)
                    job.current_file = None
                    drop_runtime_token(job_id)
            logger.exception("Job execution failed", extra={"job_id": job_id})

    def _download_job_file(self, job_id: str, job_file_id: int, token: str | None) -> None:
        with session_scope() as session:
            job = session.get(DownloadJob, job_id)
            job_file = session.get(DownloadJobFile, job_file_id)
            if job is None or job_file is None:
                return
            target_root = Path(job.target_path)
            target_path = target_root / job_file.path
            temp_path = settings.incomplete_root / job_id / job_file.path
            job_file.final_path = str(target_path)
            job_file.temp_path = str(temp_path)
            job_file.status = FileStatus.downloading
            job_file.started_at = job_file.started_at or datetime.utcnow()
            job.current_file = job_file.path

        def progress_callback(update: ProgressUpdate) -> None:
            with session_scope() as progress_session:
                job = progress_session.get(DownloadJob, job_id)
                job_file = progress_session.get(DownloadJobFile, job_file_id)
                if job is None or job_file is None:
                    return
                delta = max(update.written_bytes - job_file.bytes_downloaded, 0)
                job_file.bytes_downloaded = update.written_bytes
                job.downloaded_bytes += delta
                job.current_file_bytes = update.written_bytes
                job.current_file_total_bytes = update.file_size_bytes
                job.speed_bytes_per_second = update.speed_bytes_per_second
                job.eta_seconds = update.eta_seconds
                job.last_progress_at = datetime.utcnow()

        def should_stop_callback() -> str | None:
            with SessionLocal() as probe_session:
                job = probe_session.get(DownloadJob, job_id)
                if job is None:
                    return "cancel"
                if job.status == JobStatus.paused:
                    return "pause"
                if job.status == JobStatus.cancelled:
                    return "cancel"
            return None

        with session_scope() as session:
            job = session.get(DownloadJob, job_id)
            job_file = session.get(DownloadJobFile, job_file_id)
            if job is None or job_file is None:
                return
            try:
                download_file(
                    repo_id=job.repo_id,
                    revision=job.revision,
                    file_path=job_file.path,
                    destination_path=Path(job_file.final_path),
                    temp_path=Path(job_file.temp_path),
                    token=token,
                    expected_size=job_file.size_bytes,
                    progress_callback=progress_callback,
                    should_stop_callback=should_stop_callback,
                )
            except DownloadPaused:
                job_file.status = FileStatus.paused
                raise
            except DownloadCancelled:
                job_file.status = FileStatus.cancelled
                raise
            except Exception:
                job_file.status = FileStatus.failed
                raise

        with session_scope() as session:
            job = session.get(DownloadJob, job_id)
            job_file = session.get(DownloadJobFile, job_file_id)
            if job is None or job_file is None or not job_file.final_path:
                return
            if settings.verify_checksums:
                job_file.sha256 = compute_sha256(Path(job_file.final_path))
            job_file.status = FileStatus.completed
            job_file.completed_at = datetime.utcnow()


download_worker = DownloadWorker()
