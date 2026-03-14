"""Pydantic models for API request/response data."""

from __future__ import annotations

from pydantic import BaseModel, Field


class Frame(BaseModel):
    """A single captured frame."""

    id: int
    filename: str
    captured_at: int = Field(description="Unix epoch timestamp")
    file_size: int | None = None
    file_path: str
    thumb_path: str | None = None
    metadata: str | None = Field(default=None, description="JSON string for extensible data")


class FrameList(BaseModel):
    """Paginated list of frames."""

    frames: list[Frame]
    total: int
    offset: int
    limit: int
    has_more: bool


class TimeRange(BaseModel):
    """Time range query parameters."""

    start: int = Field(description="Unix epoch start")
    end: int = Field(description="Unix epoch end")


class CaptureStatus(BaseModel):
    """Status of the capture worker."""

    running: bool
    pid: int | None = None
    frames_captured: int = 0
    last_capture_at: int | None = None
    errors: int = 0


class SystemStatus(BaseModel):
    """Overall system status."""

    capture: CaptureStatus
    capture_fps: float
    total_frames: int
    disk_free_mb: int
    disk_used_mb: int
    cpu_temp: float | None = None
    uptime_seconds: int
