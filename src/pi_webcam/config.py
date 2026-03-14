"""Application configuration via environment variables."""

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Pi Webcam configuration loaded from environment variables."""

    model_config = {"env_prefix": "PI_WEBCAM_"}

    # Data storage
    data_dir: Path = Path("/data/pi_webcam")
    db_path: Path = Path("/data/pi_webcam/pi_webcam.db")

    # Capture
    capture_fps: float = Field(
        default=0.5, gt=0, le=30,
        description="Frames per second to capture (0.5 = one frame every 2s)",
    )
    rtsp_url: str = "rtsp://localhost:8554/cam"
    jpeg_quality: int = Field(
        default=3, ge=1, le=31, description="ffmpeg JPEG quality (1=best)"
    )

    # Thumbnails
    thumb_width: int = 320
    thumb_height: int = 180

    # Retention
    retention_days: int = Field(default=14, ge=1)
    retention_check_minutes: int = Field(default=15, ge=1)
    disk_watermark_mb: int = Field(
        default=5120, ge=100, description="Minimum free disk space in MB"
    )

    # Web server
    host: str = "0.0.0.0"
    port: int = 8080

    # Optional basic auth
    auth_username: str = ""
    auth_password: str = ""

    # MediaMTX URLs
    webrtc_url: str = "http://localhost:8889/cam"
    hls_url: str = "http://localhost:8888/cam"
    mediamtx_api_url: str = "http://localhost:9997"

    @property
    def frames_dir(self) -> Path:
        return self.data_dir / "frames"

    @property
    def auth_enabled(self) -> bool:
        return bool(self.auth_username and self.auth_password)


def get_settings(**overrides: object) -> Settings:
    """Create settings, optionally with overrides for testing."""
    return Settings(**overrides)  # type: ignore[arg-type]
