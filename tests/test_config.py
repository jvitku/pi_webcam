"""Tests for configuration module."""

from __future__ import annotations

from pathlib import Path

import pytest

from pi_webcam.config import Settings, get_settings


class TestSettings:
    def test_defaults(self) -> None:
        s = Settings()
        assert s.data_dir == Path("/data/pi_webcam")
        assert s.capture_fps == 0.5
        assert s.jpeg_quality == 3
        assert s.retention_days == 14
        assert s.port == 8080
        assert s.thumb_width == 320
        assert s.thumb_height == 180

    def test_frames_dir(self) -> None:
        s = Settings(data_dir=Path("/tmp/test"))
        assert s.frames_dir == Path("/tmp/test/frames")

    def test_auth_disabled_by_default(self) -> None:
        s = Settings()
        assert not s.auth_enabled

    def test_auth_enabled_when_both_set(self) -> None:
        s = Settings(auth_username="admin", auth_password="secret")
        assert s.auth_enabled

    def test_auth_disabled_with_only_username(self) -> None:
        s = Settings(auth_username="admin", auth_password="")
        assert not s.auth_enabled

    def test_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PI_WEBCAM_PORT", "9090")
        monkeypatch.setenv("PI_WEBCAM_RETENTION_DAYS", "30")
        s = Settings()
        assert s.port == 9090
        assert s.retention_days == 30

    def test_capture_fps_validation(self) -> None:
        with pytest.raises(ValueError):
            Settings(capture_fps=0)

    def test_capture_fps_max_validation(self) -> None:
        with pytest.raises(ValueError):
            Settings(capture_fps=31)

    def test_jpeg_quality_validation(self) -> None:
        with pytest.raises(ValueError):
            Settings(jpeg_quality=32)

    def test_get_settings_with_overrides(self) -> None:
        s = get_settings(port=3000)
        assert s.port == 3000
