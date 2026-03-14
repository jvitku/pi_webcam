"""Tests for database module."""

from __future__ import annotations

import sqlite3
import time

import pytest

from pi_webcam.database import Database


class TestDatabase:
    def test_connect_and_init(self, db: Database) -> None:
        # Schema should be created
        count = db.get_frame_count()
        assert count == 0

    def test_insert_and_get_frame(self, db: Database) -> None:
        now = int(time.time())
        frame_id = db.insert_frame(
            filename="20260314_120000.jpg",
            captured_at=now,
            file_path="2026/03/14/120000.jpg",
            file_size=50000,
            thumb_path="2026/03/14/thumb/120000.jpg",
        )
        assert frame_id > 0

        frame = db.get_frame_by_id(frame_id)
        assert frame is not None
        assert frame["filename"] == "20260314_120000.jpg"
        assert frame["captured_at"] == now
        assert frame["file_size"] == 50000
        assert frame["thumb_path"] == "2026/03/14/thumb/120000.jpg"

    def test_get_frame_not_found(self, db: Database) -> None:
        assert db.get_frame_by_id(999) is None

    def test_unique_filename_constraint(self, db: Database) -> None:
        now = int(time.time())
        db.insert_frame(filename="test.jpg", captured_at=now, file_path="test.jpg")
        with pytest.raises(sqlite3.IntegrityError):
            db.insert_frame(filename="test.jpg", captured_at=now + 1, file_path="test2.jpg")

    def test_get_latest_frame(self, db: Database) -> None:
        now = int(time.time())
        db.insert_frame(filename="a.jpg", captured_at=now - 100, file_path="a.jpg")
        db.insert_frame(filename="b.jpg", captured_at=now, file_path="b.jpg")
        db.insert_frame(filename="c.jpg", captured_at=now - 50, file_path="c.jpg")

        latest = db.get_latest_frame()
        assert latest is not None
        assert latest["filename"] == "b.jpg"

    def test_get_latest_frame_empty(self, db: Database) -> None:
        assert db.get_latest_frame() is None

    def test_get_frames_all(self, db: Database) -> None:
        now = int(time.time())
        for i in range(5):
            db.insert_frame(
                filename=f"f{i}.jpg", captured_at=now + i, file_path=f"f{i}.jpg"
            )

        frames, total = db.get_frames()
        assert total == 5
        assert len(frames) == 5
        # Should be ordered by captured_at ASC
        assert frames[0]["filename"] == "f0.jpg"
        assert frames[4]["filename"] == "f4.jpg"

    def test_get_frames_time_range(self, db: Database) -> None:
        now = int(time.time())
        for i in range(10):
            db.insert_frame(
                filename=f"f{i}.jpg", captured_at=now + i, file_path=f"f{i}.jpg"
            )

        frames, total = db.get_frames(start=now + 3, end=now + 7)
        assert total == 5
        assert len(frames) == 5
        assert frames[0]["filename"] == "f3.jpg"

    def test_get_frames_pagination(self, db: Database) -> None:
        now = int(time.time())
        for i in range(10):
            db.insert_frame(
                filename=f"f{i}.jpg", captured_at=now + i, file_path=f"f{i}.jpg"
            )

        frames, total = db.get_frames(limit=3, offset=0)
        assert total == 10
        assert len(frames) == 3
        assert frames[0]["filename"] == "f0.jpg"

        frames2, total2 = db.get_frames(limit=3, offset=3)
        assert total2 == 10
        assert len(frames2) == 3
        assert frames2[0]["filename"] == "f3.jpg"

    def test_get_frame_count(self, db: Database) -> None:
        now = int(time.time())
        assert db.get_frame_count() == 0
        db.insert_frame(filename="a.jpg", captured_at=now, file_path="a.jpg")
        assert db.get_frame_count() == 1
        db.insert_frame(filename="b.jpg", captured_at=now + 1, file_path="b.jpg")
        assert db.get_frame_count() == 2

    def test_delete_frames_before(self, db: Database) -> None:
        now = int(time.time())
        for i in range(5):
            db.insert_frame(
                filename=f"f{i}.jpg",
                captured_at=now + i,
                file_path=f"f{i}.jpg",
                thumb_path=f"thumb/f{i}.jpg",
            )

        paths = db.delete_frames_before(now + 3)
        assert len(paths) == 3
        assert paths[0] == ("f0.jpg", "thumb/f0.jpg")
        assert db.get_frame_count() == 2

    def test_delete_oldest_frames(self, db: Database) -> None:
        now = int(time.time())
        for i in range(5):
            db.insert_frame(
                filename=f"f{i}.jpg", captured_at=now + i, file_path=f"f{i}.jpg"
            )

        paths = db.delete_oldest_frames(2)
        assert len(paths) == 2
        assert db.get_frame_count() == 3

    def test_get_days_with_frames(self, db: Database) -> None:
        # Insert frames on two different days (using known UTC timestamps)
        # 2026-03-14 12:00:00 UTC = 1773489600
        # 2026-03-15 12:00:00 UTC = 1773576000
        db.insert_frame(filename="a.jpg", captured_at=1773489600, file_path="a.jpg")
        db.insert_frame(filename="b.jpg", captured_at=1773496801, file_path="b.jpg")
        db.insert_frame(filename="c.jpg", captured_at=1773576000, file_path="c.jpg")

        days = db.get_days_with_frames()
        assert len(days) == 2

    def test_get_all_file_paths(self, db: Database) -> None:
        now = int(time.time())
        db.insert_frame(filename="a.jpg", captured_at=now, file_path="2026/03/14/a.jpg")
        db.insert_frame(filename="b.jpg", captured_at=now + 1, file_path="2026/03/14/b.jpg")

        paths = db.get_all_file_paths()
        assert paths == {"2026/03/14/a.jpg", "2026/03/14/b.jpg"}

    def test_run_incremental_vacuum(self, db: Database) -> None:
        # Should not raise
        db.run_incremental_vacuum()

    def test_insert_with_metadata(self, db: Database) -> None:
        import json

        now = int(time.time())
        meta = json.dumps({"motion_score": 0.5})
        frame_id = db.insert_frame(
            filename="a.jpg", captured_at=now, file_path="a.jpg", metadata=meta
        )
        frame = db.get_frame_by_id(frame_id)
        assert frame is not None
        assert json.loads(frame["metadata"]) == {"motion_score": 0.5}

    def test_wal_mode_enabled(self, db: Database) -> None:
        row = db.conn.execute("PRAGMA journal_mode").fetchone()
        assert row is not None
        assert row[0] == "wal"
