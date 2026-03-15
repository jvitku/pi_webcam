"""Tests for the FastAPI web server."""

from __future__ import annotations

import base64
import time

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from pi_webcam.config import Settings
from pi_webcam.database import Database
from pi_webcam.server import create_app, validate_image_path


@pytest.fixture
def app(settings: Settings, db: Database) -> TestClient:
    """Create a test client with initialized database."""
    application = create_app(settings)
    application.state.db = db
    return TestClient(application)


@pytest.fixture
def app_with_frames(
    settings: Settings, db: Database, app: TestClient
) -> TestClient:
    """Test client with some frames in the database and on disk."""
    now = int(time.time())
    for i in range(5):
        rel_path = f"2026/03/14/12000{i}.jpg"
        full_path = settings.frames_dir / rel_path
        full_path.parent.mkdir(parents=True, exist_ok=True)
        img = Image.new("RGB", (100, 100), color=(i * 50, 0, 0))
        img.save(full_path, "JPEG")

        thumb_rel = f"2026/03/14/thumb/12000{i}.jpg"
        thumb_path = settings.frames_dir / thumb_rel
        thumb_path.parent.mkdir(parents=True, exist_ok=True)
        img_small = Image.new("RGB", (32, 18))
        img_small.save(thumb_path, "JPEG")

        db.insert_frame(
            filename=f"20260314_12000{i}.jpg",
            captured_at=now + i,
            file_path=rel_path,
            file_size=full_path.stat().st_size,
            thumb_path=thumb_rel,
        )
    return app


class TestValidateImagePath:
    def test_valid_path(self) -> None:
        assert validate_image_path("2026/03/14/120000.jpg") == "2026/03/14/120000.jpg"

    def test_path_traversal(self) -> None:
        from fastapi import HTTPException

        with pytest.raises(HTTPException, match="400"):
            validate_image_path("../../../etc/passwd")

    def test_absolute_path(self) -> None:
        from fastapi import HTTPException

        with pytest.raises(HTTPException, match="400"):
            validate_image_path("/etc/passwd.jpg")

    def test_invalid_extension(self) -> None:
        from fastapi import HTTPException

        with pytest.raises(HTTPException, match="400"):
            validate_image_path("test.py")


class TestIndexPage:
    def test_get_index(self, app: TestClient) -> None:
        response = app.get("/")
        assert response.status_code == 200
        assert "Pi Webcam" in response.text


class TestFramesAPI:
    def test_list_frames_empty(self, app: TestClient) -> None:
        response = app.get("/api/frames")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 0
        assert data["frames"] == []
        assert data["has_more"] is False

    def test_list_frames(self, app_with_frames: TestClient) -> None:
        response = app_with_frames.get("/api/frames")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 5
        assert len(data["frames"]) == 5

    def test_list_frames_with_limit(self, app_with_frames: TestClient) -> None:
        response = app_with_frames.get("/api/frames?limit=2")
        data = response.json()
        assert len(data["frames"]) == 2
        assert data["has_more"] is True

    def test_list_frames_with_offset(self, app_with_frames: TestClient) -> None:
        response = app_with_frames.get("/api/frames?limit=2&offset=3")
        data = response.json()
        assert len(data["frames"]) == 2
        assert data["offset"] == 3

    def test_list_frames_time_range(self, app_with_frames: TestClient) -> None:
        # Get all frames to know timestamps
        all_data = app_with_frames.get("/api/frames").json()
        first_ts = all_data["frames"][0]["captured_at"]
        second_ts = all_data["frames"][1]["captured_at"]

        response = app_with_frames.get(f"/api/frames?start={first_ts}&end={second_ts}")
        data = response.json()
        assert data["total"] == 2

    def test_latest_frame(self, app_with_frames: TestClient) -> None:
        response = app_with_frames.get("/api/frames/latest")
        assert response.status_code == 200
        data = response.json()
        assert data["filename"] == "20260314_120004.jpg"

    def test_latest_frame_empty(self, app: TestClient) -> None:
        response = app.get("/api/frames/latest")
        assert response.status_code == 404

    def test_get_frame_by_id(self, app_with_frames: TestClient) -> None:
        response = app_with_frames.get("/api/frames/1")
        assert response.status_code == 200
        assert response.json()["id"] == 1

    def test_get_frame_not_found(self, app: TestClient) -> None:
        response = app.get("/api/frames/999")
        assert response.status_code == 404

    def test_invalid_limit(self, app: TestClient) -> None:
        response = app.get("/api/frames?limit=0")
        assert response.status_code == 422

    def test_invalid_limit_too_high(self, app: TestClient) -> None:
        response = app.get("/api/frames?limit=10001")
        assert response.status_code == 422


class TestDaysAPI:
    def test_list_days_empty(self, app: TestClient) -> None:
        response = app.get("/api/days")
        assert response.status_code == 200
        assert response.json() == []

    def test_list_days(self, app_with_frames: TestClient) -> None:
        response = app_with_frames.get("/api/days")
        assert response.status_code == 200
        days = response.json()
        assert len(days) >= 1


class TestStatusAPI:
    def test_status(self, app: TestClient) -> None:
        response = app.get("/api/status")
        assert response.status_code == 200
        data = response.json()
        assert data["total_frames"] == 0
        assert data["disk_free_mb"] > 0
        assert data["uptime_seconds"] >= 0
        assert data["capture"]["running"] is False


class TestStreamURL:
    def test_stream_url(self, app: TestClient) -> None:
        response = app.get("/api/stream-url")
        assert response.status_code == 200
        data = response.json()
        assert "webrtc" in data
        assert "hls" in data


class TestImageServing:
    def test_serve_image(self, app_with_frames: TestClient) -> None:
        response = app_with_frames.get("/images/2026/03/14/120000.jpg")
        assert response.status_code == 200
        assert response.headers["content-type"] == "image/jpeg"
        assert "immutable" in response.headers["cache-control"]

    def test_serve_thumbnail(self, app_with_frames: TestClient) -> None:
        response = app_with_frames.get("/thumbs/2026/03/14/thumb/120000.jpg")
        assert response.status_code == 200
        assert response.headers["content-type"] == "image/jpeg"

    def test_image_not_found(self, app: TestClient) -> None:
        response = app.get("/images/nonexistent.jpg")
        assert response.status_code == 404

    def test_path_traversal_blocked(self, app: TestClient) -> None:
        response = app.get("/images/..%2F..%2Fetc/passwd.jpg")
        assert response.status_code == 400


class TestAuth:
    def test_no_auth_required_by_default(self, app: TestClient) -> None:
        response = app.get("/api/status")
        assert response.status_code == 200

    def test_auth_required_when_enabled(self, settings: Settings, db: Database) -> None:
        auth_settings = Settings(
            data_dir=settings.data_dir,
            db_path=settings.db_path,
            auth_username="admin",
            auth_password="secret",
        )
        auth_app = create_app(auth_settings)
        auth_app.state.db = db
        client = TestClient(auth_app)

        response = client.get("/api/status")
        assert response.status_code == 401

    def test_auth_with_valid_credentials(
        self, settings: Settings, db: Database
    ) -> None:
        auth_settings = Settings(
            data_dir=settings.data_dir,
            db_path=settings.db_path,
            auth_username="admin",
            auth_password="secret",
        )
        auth_app = create_app(auth_settings)
        auth_app.state.db = db
        client = TestClient(auth_app)

        creds = base64.b64encode(b"admin:secret").decode()
        response = client.get(
            "/api/status", headers={"Authorization": f"Basic {creds}"}
        )
        assert response.status_code == 200

    def test_auth_with_wrong_credentials(
        self, settings: Settings, db: Database
    ) -> None:
        auth_settings = Settings(
            data_dir=settings.data_dir,
            db_path=settings.db_path,
            auth_username="admin",
            auth_password="secret",
        )
        auth_app = create_app(auth_settings)
        auth_app.state.db = db
        client = TestClient(auth_app)

        creds = base64.b64encode(b"admin:wrong").decode()
        response = client.get(
            "/api/status", headers={"Authorization": f"Basic {creds}"}
        )
        assert response.status_code == 401
