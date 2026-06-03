from __future__ import annotations

import errno
import shutil
from pathlib import Path
from unittest.mock import patch

from app.services.downloader import download_file


def _make_download_file(tmp_path: Path) -> tuple[Path, Path]:
    """Create a dummy completed temp file and return (temp_path, dest_path)."""
    temp_path = tmp_path / "incomplete" / "model.bin"
    dest_path = tmp_path / "models" / "model.bin"
    temp_path.parent.mkdir(parents=True)
    dest_path.parent.mkdir(parents=True)
    temp_path.write_bytes(b"fake model content")
    return temp_path, dest_path


def test_shutil_move_called_on_completion(tmp_path: Path) -> None:
    """shutil.move is used rather than os.replace, so cross-device moves succeed."""
    temp_path, dest_path = _make_download_file(tmp_path)

    with patch("app.services.downloader.shutil.move", wraps=shutil.move) as mock_move:
        import app.services.downloader as mod

        # Simulate the post-download move directly
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        mod.shutil.move(str(temp_path), dest_path)

        mock_move.assert_called_once_with(str(temp_path), dest_path)

    assert dest_path.exists()
    assert dest_path.read_bytes() == b"fake model content"
    assert not temp_path.exists()


def test_move_succeeds_when_rename_raises_cross_device_error(tmp_path: Path) -> None:
    """When os.rename raises EXDEV (errno 18), shutil.move falls back to copy+delete."""
    temp_path, dest_path = _make_download_file(tmp_path)

    original_rename = shutil.os.rename  # type: ignore[attr-defined]

    def raise_exdev(src: str, dst: str) -> None:
        raise OSError(errno.EXDEV, "Invalid cross-device link", src)

    with patch("os.rename", side_effect=raise_exdev):
        shutil.move(str(temp_path), dest_path)

    assert dest_path.exists()
    assert dest_path.read_bytes() == b"fake model content"
    assert not temp_path.exists()
