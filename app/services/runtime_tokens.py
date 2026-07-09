from __future__ import annotations


RUNTIME_TOKENS: dict[str, str] = {}


def store_runtime_token(job_id: str, token: str) -> None:
    if token:
        RUNTIME_TOKENS[job_id] = token


def get_runtime_token(job_id: str) -> str | None:
    return RUNTIME_TOKENS.get(job_id)


def drop_runtime_token(job_id: str) -> None:
    RUNTIME_TOKENS.pop(job_id, None)
