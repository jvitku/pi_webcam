"""Shared test fixtures."""

from __future__ import annotations

from pathlib import Path

import pytest

from pi_webcam.config import Settings
from pi_webcam.database import Database


@pytest.fixture
def tmp_data_dir(tmp_path: Path) -> Path:
    """Create a temporary data directory with frames subdirectory."""
    data_dir = tmp_path / "data"
    frames_dir = data_dir / "frames"
    frames_dir.mkdir(parents=True)
    return data_dir


@pytest.fixture
def settings(tmp_data_dir: Path) -> Settings:
    """Create settings pointing to temporary directories."""
    return Settings(
        data_dir=tmp_data_dir,
        db_path=tmp_data_dir / "test.db",
        rtsp_url="rtsp://localhost:8554/cam",
        retention_days=7,
        retention_check_minutes=1,
        disk_watermark_mb=100,
    )


@pytest.fixture
def db(settings: Settings) -> Database:
    """Create a file-backed test database."""
    database = Database(settings.db_path)
    database.connect()
    database.init_schema()
    yield database  # type: ignore[misc]
    database.close()


@pytest.fixture
def sample_jpeg(tmp_path: Path) -> Path:
    """Create a minimal valid JPEG file for testing."""
    from PIL import Image

    img = Image.new("RGB", (1280, 720), color=(100, 150, 200))
    jpeg_path = tmp_path / "sample.jpg"
    img.save(jpeg_path, "JPEG")
    return jpeg_path
