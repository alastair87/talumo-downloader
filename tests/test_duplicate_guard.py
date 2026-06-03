from __future__ import annotations

from concurrent.futures import Future
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.models import Base, DownloadJob, DownloadJobFile, FileStatus, JobStatus, RepositoryCache, RepositoryFile
from app.db.session import get_db
from app.main import app


# ---------------------------------------------------------------------------
# In-memory DB fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def db_engine():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    yield engine
    Base.metadata.drop_all(bind=engine)


@pytest.fixture()
def db_session(db_engine):
    Session = sessionmaker(bind=db_engine, autoflush=False, autocommit=False)
    session = Session()
    yield session
    session.close()


@pytest.fixture()
def client(db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    with (
        patch("app.main.download_worker"),
        patch("app.api.downloads.can_fit_download", return_value=(True, None, 0)),
        patch("app.api.downloads.store_runtime_token"),
    ):
        yield TestClient(app, raise_server_exceptions=True)
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

REPO_ID = "test-org/test-model"
REVISION = "main"


def _seed_repo_cache(session, repo_id: str = REPO_ID, revision: str = REVISION) -> RepositoryCache:
    cache = RepositoryCache(repo_id=repo_id, revision=revision, total_size_bytes=100, file_count=1)
    session.add(cache)
    session.flush()
    session.add(RepositoryFile(
        repository_cache_id=cache.id,
        repo_id=repo_id,
        revision=revision,
        path="model.bin",
        size_bytes=100,
    ))
    session.commit()
    return cache


def _seed_active_job(session, repo_id: str = REPO_ID, revision: str = REVISION, status: JobStatus = JobStatus.queued) -> DownloadJob:
    job = DownloadJob(repo_id=repo_id, revision=revision, target_path="/data/models/test", status=status)
    session.add(job)
    session.commit()
    return job


# ---------------------------------------------------------------------------
# API guard tests
# ---------------------------------------------------------------------------

class TestApiDuplicateGuard:
    def _post_download(self, client, repo_id=REPO_ID, revision=REVISION):
        return client.post(
            "/downloads",
            data={
                "repo_id": repo_id,
                "revision": revision,
                "category": "uncategorized",
                "token": "",
                "selected_files": ["model.bin"],
            },
        )

    @pytest.mark.parametrize("active_status", [
        JobStatus.queued,
        JobStatus.downloading,
        JobStatus.paused,
        JobStatus.failed,
    ])
    def test_returns_409_when_active_job_exists(self, client, db_session, active_status):
        _seed_repo_cache(db_session)
        _seed_active_job(db_session, status=active_status)
        response = self._post_download(client)
        assert response.status_code == 409
        assert "already active" in response.json()["detail"]

    def test_allows_new_job_after_completion(self, client, db_session):
        _seed_repo_cache(db_session)
        _seed_active_job(db_session, status=JobStatus.completed)
        response = self._post_download(client)
        # Completed jobs should not block a new submission
        assert response.status_code != 409

    def test_allows_new_job_after_cancellation(self, client, db_session):
        _seed_repo_cache(db_session)
        _seed_active_job(db_session, status=JobStatus.cancelled)
        response = self._post_download(client)
        assert response.status_code != 409

    def test_different_revision_is_allowed(self, client, db_session):
        _seed_repo_cache(db_session)
        _seed_active_job(db_session, revision="main")
        _seed_repo_cache(db_session, revision="v2")
        response = self._post_download(client, revision="v2")
        assert response.status_code != 409


# ---------------------------------------------------------------------------
# Worker guard tests
# ---------------------------------------------------------------------------

class TestWorkerDuplicateGuard:
    def _make_job(self, job_id: str, repo_id: str = REPO_ID, revision: str = REVISION) -> DownloadJob:
        job = MagicMock(spec=DownloadJob)
        job.id = job_id
        job.repo_id = repo_id
        job.revision = revision
        return job

    def test_only_one_job_submitted_for_same_repo_revision(self):
        from app.worker.runner import DownloadWorker

        worker = DownloadWorker()
        worker._executor = MagicMock()
        mock_future: Future[None] = MagicMock(spec=Future)
        mock_future.done.return_value = False
        worker._executor.submit.return_value = mock_future

        job_a = self._make_job("job-1")
        job_b = self._make_job("job-2")  # same repo_id:revision as job_a

        now_dt = __import__("datetime").datetime.utcnow()
        with patch("app.worker.runner.session_scope") as mock_scope:
            mock_session = MagicMock()
            mock_session.__enter__ = MagicMock(return_value=mock_session)
            mock_session.__exit__ = MagicMock(return_value=False)
            mock_session.scalars.return_value.all.return_value = [job_a, job_b]
            mock_scope.return_value = mock_session

            with patch("app.worker.runner.datetime") as mock_dt:
                mock_dt.utcnow.return_value = now_dt
                worker._submit_jobs(limit=2)

        # Only one future should have been submitted for the same repo:revision
        assert worker._executor.submit.call_count == 1
        assert "job-1" in worker._futures
        assert "job-2" not in worker._futures

    def test_different_repos_both_submitted(self):
        from app.worker.runner import DownloadWorker

        worker = DownloadWorker()
        worker._executor = MagicMock()
        mock_future: Future[None] = MagicMock(spec=Future)
        mock_future.done.return_value = False
        worker._executor.submit.return_value = mock_future

        job_a = self._make_job("job-1", repo_id="org/model-a")
        job_b = self._make_job("job-2", repo_id="org/model-b")

        now_dt = __import__("datetime").datetime.utcnow()
        with patch("app.worker.runner.session_scope") as mock_scope:
            mock_session = MagicMock()
            mock_session.__enter__ = MagicMock(return_value=mock_session)
            mock_session.__exit__ = MagicMock(return_value=False)
            mock_session.scalars.return_value.all.return_value = [job_a, job_b]
            mock_scope.return_value = mock_session

            with patch("app.worker.runner.datetime") as mock_dt:
                mock_dt.utcnow.return_value = now_dt
                worker._submit_jobs(limit=2)

        assert worker._executor.submit.call_count == 2
        assert "job-1" in worker._futures
        assert "job-2" in worker._futures

    def test_cleanup_removes_repo_revision_tracking(self):
        from app.worker.runner import DownloadWorker

        worker = DownloadWorker()
        done_future: Future[None] = MagicMock(spec=Future)
        done_future.done.return_value = True
        done_future.result.return_value = None

        worker._futures["job-1"] = done_future
        worker._job_repo_revision["job-1"] = f"{REPO_ID}:{REVISION}"

        worker._cleanup_futures()

        assert "job-1" not in worker._futures
        assert "job-1" not in worker._job_repo_revision
