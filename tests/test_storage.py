from app.config import settings
from app.services.rsync import build_rsync_command
from app.services.storage import build_job_target_path, sanitize_repo_id


def test_sanitize_repo_id() -> None:
    assert sanitize_repo_id("Qwen/Qwen2.5-7B-Instruct-GGUF") == "Qwen--Qwen2.5-7B-Instruct-GGUF"


def test_build_job_target_path() -> None:
    path = build_job_target_path("Qwen/Qwen2.5", "main", "qwen")
    assert str(path).endswith("qwen/Qwen--Qwen2.5/main")


def test_rsync_command() -> None:
    command = build_rsync_command(settings.models_root / "qwen")
    assert "rsync -av --partial --progress" in command
