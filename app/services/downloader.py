from __future__ import annotations

import os
import time
from dataclasses import dataclass
from pathlib import Path

import requests
from huggingface_hub import hf_hub_url

from app.config import settings


class DownloadPaused(Exception):
    pass


class DownloadCancelled(Exception):
    pass


@dataclass(slots=True)
class ProgressUpdate:
    written_bytes: int
    file_size_bytes: int
    speed_bytes_per_second: int
    eta_seconds: int | None


def _headers(token: str | None, start_byte: int) -> dict[str, str]:
    headers: dict[str, str] = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if start_byte > 0:
        headers["Range"] = f"bytes={start_byte}-"
    return headers


def download_file(
    repo_id: str,
    revision: str,
    file_path: str,
    destination_path: Path,
    temp_path: Path,
    token: str | None,
    expected_size: int,
    progress_callback,
    should_stop_callback,
) -> None:
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path.parent.mkdir(parents=True, exist_ok=True)
    start_byte = temp_path.stat().st_size if temp_path.exists() else 0
    mode = "ab" if start_byte > 0 else "wb"
    url = hf_hub_url(repo_id=repo_id, filename=file_path, revision=revision, repo_type="model")
    response = requests.get(
        url,
        headers=_headers(token, start_byte),
        stream=True,
        timeout=(10, 300),
    )
    if response.status_code == 416:
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path.replace(destination_path)
        return
    response.raise_for_status()

    server_total = expected_size
    content_length = response.headers.get("Content-Length")
    if response.status_code == 206:
        server_total = max(expected_size, start_byte + int(content_length or 0))
    elif start_byte > 0:
        start_byte = 0
        mode = "wb"

    written = start_byte
    started_at = time.monotonic()
    last_sample_at = started_at
    last_sample_bytes = start_byte

    with temp_path.open(mode) as handle:
        for chunk in response.iter_content(chunk_size=settings.chunk_size_bytes):
            if not chunk:
                continue

            stop_signal = should_stop_callback()
            if stop_signal == "pause":
                raise DownloadPaused()
            if stop_signal == "cancel":
                raise DownloadCancelled()

            handle.write(chunk)
            written += len(chunk)
            now = time.monotonic()
            elapsed = max(now - last_sample_at, 0.001)
            speed = int((written - last_sample_bytes) / elapsed)
            remaining = max(server_total - written, 0)
            eta_seconds = int(remaining / speed) if speed > 0 else None
            progress_callback(
                ProgressUpdate(
                    written_bytes=written,
                    file_size_bytes=server_total,
                    speed_bytes_per_second=speed,
                    eta_seconds=eta_seconds,
                )
            )
            if now - last_sample_at >= 1:
                last_sample_at = now
                last_sample_bytes = written

    destination_path.parent.mkdir(parents=True, exist_ok=True)
    os.replace(temp_path, destination_path)
