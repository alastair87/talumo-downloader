from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = Field(default="HF Downloader", alias="APP_NAME")
    host: str = Field(default="0.0.0.0", alias="HOST")
    port: int = Field(default=8000, alias="PORT")
    data_dir: Path = Field(default=Path("./data"), alias="DATA_DIR")
    database_path: Path = Field(default=Path("./data/app.db"), alias="DATABASE_PATH")
    models_root: Path = Field(default=Path("./data/models"), alias="MODELS_ROOT")
    hf_cache_root: Path = Field(default=Path("./data/hf-cache"), alias="HF_CACHE_ROOT")
    incomplete_root: Path = Field(default=Path("./data/incomplete"), alias="INCOMPLETE_ROOT")
    default_category: str = Field(default="uncategorized", alias="DEFAULT_CATEGORY")
    free_space_threshold_gb: int = Field(default=20, alias="FREE_SPACE_THRESHOLD_GB")
    worker_poll_seconds: int = Field(default=2, alias="WORKER_POLL_SECONDS")
    max_concurrent_downloads: int = Field(default=1, alias="MAX_CONCURRENT_DOWNLOADS")
    max_retries: int = Field(default=4, alias="MAX_RETRIES")
    retry_base_seconds: int = Field(default=10, alias="RETRY_BASE_SECONDS")
    chunk_size_bytes: int = Field(default=1024 * 1024, alias="CHUNK_SIZE_BYTES")
    verify_checksums: bool = Field(default=True, alias="VERIFY_CHECKSUMS")

    @property
    def database_url(self) -> str:
        return f"sqlite:///{self.database_path.resolve()}"

    @property
    def free_space_threshold_bytes(self) -> int:
        return self.free_space_threshold_gb * 1024 * 1024 * 1024

    def ensure_directories(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.models_root.mkdir(parents=True, exist_ok=True)
        self.hf_cache_root.mkdir(parents=True, exist_ok=True)
        self.incomplete_root.mkdir(parents=True, exist_ok=True)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)


settings = Settings()
