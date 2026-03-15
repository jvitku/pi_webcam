"""Integration tests — end-to-end pipeline without camera hardware."""

from __future__ import annotations

import time

from fastapi.testclient import TestClient
from PIL import Image

from pi_webcam.capture import CaptureWorker, reconcile_frames
from pi_webcam.config import Settings
from pi_webcam.database import Database
from pi_webcam.retention import run_cleanup
from pi_webcam.server import create_app


class TestCaptureToAPI:
    """Test the full pipeline: capture → database → API → serve image."""

    def test_captured_frame_accessible_via_api(
        self, settings: Settings, db: Database
    ) -> None:
        """Simulate a capture, verify it appears in the API."""
        worker = CaptureWorker(settings, db)

        # Simulate ffmpeg outputting latest.jpg
        latest = settings.frames_dir / "latest.jpg"
        img = Image.new("RGB", (1280, 720), color=(100, 200, 50))
        img.save(latest, "JPEG")

        # Register it (simulates the poll step)
        worker._capture_latest(latest)

        # Verify via API
        app = create_app(settings)
        app.state.db = db
        client = TestClient(app)

        # Should appear in frames list
        response = client.get("/api/frames")
        data = response.json()
        assert data["total"] == 1
        frame = data["frames"][0]
        assert frame["file_size"] > 0

        # Should be retrievable as latest
        response = client.get("/api/frames/latest")
        assert response.status_code == 200
        assert response.json()["file_size"] > 0

        # Image file should be servable
        response = client.get(f"/images/{frame['file_path']}")
        assert response.status_code == 200
        assert response.headers["content-type"] == "image/jpeg"

        # Thumbnail should be servable
        if frame["thumb_path"]:
            response = client.get(f"/thumbs/{frame['thumb_path']}")
            assert response.status_code == 200

    def test_retention_removes_old_and_api_reflects(
        self, settings: Settings, db: Database
    ) -> None:
        """Capture old frames, run retention, verify they're gone from API."""
        now = int(time.time())
        old_ts = now - (settings.retention_days + 1) * 86400

        # Create old frame
        old_dir = settings.frames_dir / "2020" / "01" / "01"
        old_dir.mkdir(parents=True)
        old_file = old_dir / "120000.jpg"
        img = Image.new("RGB", (100, 100))
        img.save(old_file, "JPEG")
        db.insert_frame(
            filename="20200101_120000.jpg",
            captured_at=old_ts,
            file_path="2020/01/01/120000.jpg",
            file_size=old_file.stat().st_size,
        )

        # Create new frame
        new_dir = settings.frames_dir / "2026" / "03" / "14"
        new_dir.mkdir(parents=True)
        new_file = new_dir / "120000.jpg"
        img.save(new_file, "JPEG")
        db.insert_frame(
            filename="20260314_120000.jpg",
            captured_at=now,
            file_path="2026/03/14/120000.jpg",
            file_size=new_file.stat().st_size,
        )

        assert db.get_frame_count() == 2

        # Run retention
        age_del, _ = run_cleanup(settings, db)
        assert age_del == 1

        # API should show only 1 frame
        app = create_app(settings)
        app.state.db = db
        client = TestClient(app)

        response = client.get("/api/frames")
        data = response.json()
        assert data["total"] == 1
        assert data["frames"][0]["filename"] == "20260314_120000.jpg"

        # Old file should be gone from disk
        assert not old_file.exists()

    def test_reconciliation_after_crash(
        self, settings: Settings, db: Database
    ) -> None:
        """Simulate crash scenario: orphan files and stale DB entries."""
        # Orphan file on disk (not in DB)
        orphan_path = settings.frames_dir / "20260314_130000.jpg"
        img = Image.new("RGB", (100, 100))
        img.save(orphan_path, "JPEG")

        # Stale DB entry (file doesn't exist)
        db.insert_frame(
            filename="20260314_140000.jpg",
            captured_at=1773493200,
            file_path="2026/03/14/140000.jpg",
        )

        registered, removed = reconcile_frames(settings, db)

        # Orphan should be registered
        assert registered >= 1

        # Stale entry should be removed
        assert removed >= 1

        # Only real files should remain in DB
        app = create_app(settings)
        app.state.db = db
        client = TestClient(app)

        response = client.get("/api/frames")
        data = response.json()
        for frame in data["frames"]:
            full_path = settings.frames_dir / frame["file_path"]
            assert full_path.exists(), f"Frame file should exist: {full_path}"

    def test_multiple_days_navigation(
        self, settings: Settings, db: Database
    ) -> None:
        """Test that frames across multiple days work correctly."""
        # Day 1: 2026-03-14
        day1_dir = settings.frames_dir / "2026" / "03" / "14"
        day1_dir.mkdir(parents=True)
        img = Image.new("RGB", (100, 100))
        for i in range(3):
            path = day1_dir / f"12000{i}.jpg"
            img.save(path, "JPEG")
            db.insert_frame(
                filename=f"20260314_12000{i}.jpg",
                captured_at=1773489600 + i,
                file_path=f"2026/03/14/12000{i}.jpg",
                file_size=path.stat().st_size,
            )

        # Day 2: 2026-03-15
        day2_dir = settings.frames_dir / "2026" / "03" / "15"
        day2_dir.mkdir(parents=True)
        for i in range(2):
            path = day2_dir / f"12000{i}.jpg"
            img.save(path, "JPEG")
            db.insert_frame(
                filename=f"20260315_12000{i}.jpg",
                captured_at=1773576000 + i,
                file_path=f"2026/03/15/12000{i}.jpg",
                file_size=path.stat().st_size,
            )

        app = create_app(settings)
        app.state.db = db
        client = TestClient(app)

        # Should have 2 days
        days = client.get("/api/days").json()
        assert len(days) == 2

        # Query day 1 only
        day1_frames = client.get(
            f"/api/frames?start=1773489600&end={1773489600 + 86399}"
        ).json()
        assert day1_frames["total"] == 3

        # Query day 2 only
        day2_frames = client.get(
            f"/api/frames?start=1773576000&end={1773576000 + 86399}"
        ).json()
        assert day2_frames["total"] == 2
