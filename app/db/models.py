from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class JobStatus(str, enum.Enum):
    queued = "queued"
    downloading = "downloading"
    paused = "paused"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


class FileStatus(str, enum.Enum):
    queued = "queued"
    downloading = "downloading"
    paused = "paused"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


class RepositoryCache(Base):
    __tablename__ = "repository_cache"
    __table_args__ = (UniqueConstraint("repo_id", "revision", name="uq_repository_cache_repo_revision"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    repo_id: Mapped[str] = mapped_column(String(255), index=True)
    revision: Mapped[str] = mapped_column(String(255), default="main")
    validated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    total_size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    file_count: Mapped[int] = mapped_column(Integer, default=0)
    validation_error: Mapped[str | None] = mapped_column(Text)

    files: Mapped[list["RepositoryFile"]] = relationship(back_populates="repository", cascade="all, delete-orphan")


class RepositoryFile(Base):
    __tablename__ = "repository_file"
    __table_args__ = (UniqueConstraint("repository_cache_id", "path", name="uq_repository_file_path"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    repository_cache_id: Mapped[int] = mapped_column(Integer, ForeignKey("repository_cache.id"), index=True)
    repo_id: Mapped[str] = mapped_column(String(255), index=True)
    revision: Mapped[str] = mapped_column(String(255), default="main", index=True)
    path: Mapped[str] = mapped_column(String(1024))
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    file_type: Mapped[str] = mapped_column(String(64), default="file")
    last_modified: Mapped[str | None] = mapped_column(String(255))
    etag: Mapped[str | None] = mapped_column(String(255))

    repository: Mapped[RepositoryCache] = relationship(back_populates="files")


class DownloadJob(Base):
    __tablename__ = "download_job"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    repo_id: Mapped[str] = mapped_column(String(255), index=True)
    revision: Mapped[str] = mapped_column(String(255), default="main")
    status: Mapped[JobStatus] = mapped_column(Enum(JobStatus), default=JobStatus.queued, index=True)
    target_category: Mapped[str] = mapped_column(String(255), default="uncategorized")
    target_path: Mapped[str] = mapped_column(String(1024))
    override_space_check: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)
    error_message: Mapped[str | None] = mapped_column(Text)
    failure_reason: Mapped[str | None] = mapped_column(Text)
    total_bytes: Mapped[int] = mapped_column(Integer, default=0)
    downloaded_bytes: Mapped[int] = mapped_column(Integer, default=0)
    current_file: Mapped[str | None] = mapped_column(String(1024))
    current_file_bytes: Mapped[int] = mapped_column(Integer, default=0)
    current_file_total_bytes: Mapped[int] = mapped_column(Integer, default=0)
    speed_bytes_per_second: Mapped[int] = mapped_column(Integer, default=0)
    eta_seconds: Mapped[int | None] = mapped_column(Integer)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime)
    started_by_ip: Mapped[str | None] = mapped_column(String(128))
    manifest_generated_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_progress_at: Mapped[datetime | None] = mapped_column(DateTime)

    files: Mapped[list["DownloadJobFile"]] = relationship(back_populates="job", cascade="all, delete-orphan")


class DownloadJobFile(Base):
    __tablename__ = "download_job_file"
    __table_args__ = (UniqueConstraint("job_id", "path", name="uq_job_file_path"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(String(36), ForeignKey("download_job.id"), index=True)
    path: Mapped[str] = mapped_column(String(1024))
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    bytes_downloaded: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[FileStatus] = mapped_column(Enum(FileStatus), default=FileStatus.queued)
    temp_path: Mapped[str | None] = mapped_column(String(1024))
    final_path: Mapped[str | None] = mapped_column(String(1024))
    sha256: Mapped[str | None] = mapped_column(String(128))
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)
    error_message: Mapped[str | None] = mapped_column(Text)

    job: Mapped[DownloadJob] = relationship(back_populates="files")
