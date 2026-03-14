"""Tests for retention module."""

from __future__ import annotations

import time
from pathlib import Path

from PIL import Image

from pi_webcam.config import Settings
from pi_webcam.database import Database
from pi_webcam.retention import (
    clean_empty_dirs,
    delete_frame_files,
    get_disk_free_mb,
    run_age_cleanup,
    run_cleanup,
    run_watermark_cleanup,
)


def _create_frame(
    settings: Settings, db: Database, filename: str, captured_at: int
) -> Path:
    """Helper: create a frame file + DB entry."""
    # Determine paths from filename
    parts = filename.replace(".jpg", "").split("_")
    if len(parts) == 2:
        date_part, time_part = parts
        year, month, day = date_part[:4], date_part[4:6], date_part[6:8]
        rel_path = f"{year}/{month}/{day}/{time_part}.jpg"
    else:
        rel_path = filename

    full_path = settings.frames_dir / rel_path
    full_path.parent.mkdir(parents=True, exist_ok=True)

    img = Image.new("RGB", (100, 100))
    img.save(full_path, "JPEG")

    db.insert_frame(
        filename=filename,
        captured_at=captured_at,
        file_path=rel_path,
        file_size=full_path.stat().st_size,
    )
    return full_path


class TestDeleteFrameFiles:
    def test_delete_existing_files(self, settings: Settings) -> None:
        # Create some files
        f1 = settings.frames_dir / "a.jpg"
        f2 = settings.frames_dir / "b.jpg"
        for f in (f1, f2):
            f.write_bytes(b"fake")

        deleted = delete_frame_files(
            settings.frames_dir, [("a.jpg", None), ("b.jpg", None)]
        )
        assert deleted == 2
        assert not f1.exists()
        assert not f2.exists()

    def test_delete_with_thumbs(self, settings: Settings) -> None:
        frame = settings.frames_dir / "test.jpg"
        thumb_dir = settings.frames_dir / "thumb"
        thumb_dir.mkdir()
        thumb = thumb_dir / "test.jpg"
        frame.write_bytes(b"f")
        thumb.write_bytes(b"t")

        deleted = delete_frame_files(
            settings.frames_dir, [("test.jpg", "thumb/test.jpg")]
        )
        assert deleted == 1
        assert not frame.exists()
        assert not thumb.exists()

    def test_missing_files_no_error(self, settings: Settings) -> None:
        deleted = delete_frame_files(
            settings.frames_dir, [("nonexistent.jpg", None)]
        )
        assert deleted == 0


class TestCleanEmptyDirs:
    def test_removes_empty_dirs(self, settings: Settings) -> None:
        d = settings.frames_dir / "a" / "b" / "c"
        d.mkdir(parents=True)

        removed = clean_empty_dirs(settings.frames_dir)
        assert removed == 3
        assert not (settings.frames_dir / "a").exists()

    def test_keeps_dirs_with_files(self, settings: Settings) -> None:
        d = settings.frames_dir / "a" / "b"
        d.mkdir(parents=True)
        (d / "test.jpg").write_bytes(b"data")

        removed = clean_empty_dirs(settings.frames_dir)
        assert removed == 0
        assert d.exists()


class TestRunAgeCleanup:
    def test_deletes_old_frames(self, settings: Settings, db: Database) -> None:
        now = int(time.time())
        old_ts = now - (settings.retention_days + 1) * 86400
        new_ts = now - 3600

        _create_frame(settings, db, "20200101_120000.jpg", old_ts)
        _create_frame(settings, db, "20260314_120000.jpg", new_ts)

        deleted = run_age_cleanup(settings, db)
        assert deleted == 1
        assert db.get_frame_count() == 1

    def test_nothing_to_delete(self, settings: Settings, db: Database) -> None:
        now = int(time.time())
        _create_frame(settings, db, "20260314_120000.jpg", now - 3600)

        deleted = run_age_cleanup(settings, db)
        assert deleted == 0
        assert db.get_frame_count() == 1


class TestRunWatermarkCleanup:
    def test_skips_when_enough_space(self, settings: Settings, db: Database) -> None:
        # Watermark is 100 MB, disk should have way more free
        now = int(time.time())
        _create_frame(settings, db, "20260314_120000.jpg", now)

        deleted = run_watermark_cleanup(settings, db)
        assert deleted == 0

    def test_no_frames_to_delete(self, settings: Settings, db: Database) -> None:
        # Even with high watermark, no frames = nothing to delete
        settings_high = Settings(
            data_dir=settings.data_dir,
            db_path=settings.db_path,
            disk_watermark_mb=999999999,
        )
        deleted = run_watermark_cleanup(settings_high, db)
        assert deleted == 0


class TestRunCleanup:
    def test_full_cleanup(self, settings: Settings, db: Database) -> None:
        now = int(time.time())
        old_ts = now - (settings.retention_days + 1) * 86400

        _create_frame(settings, db, "20200101_120000.jpg", old_ts)
        _create_frame(settings, db, "20260314_120000.jpg", now)

        age_del, wm_del = run_cleanup(settings, db)
        assert age_del == 1
        assert wm_del == 0
        assert db.get_frame_count() == 1


class TestGetDiskFreeMb:
    def test_returns_positive(self, tmp_path: Path) -> None:
        free = get_disk_free_mb(tmp_path)
        assert free > 0
