"""Tests for Pydantic models."""

from __future__ import annotations

from pi_webcam.models import CaptureStatus, Frame, FrameList, SystemStatus, TimeRange


class TestFrame:
    def test_create(self) -> None:
        f = Frame(
            id=1,
            filename="20260314_120000.jpg",
            captured_at=1773496800,
            file_path="2026/03/14/120000.jpg",
        )
        assert f.id == 1
        assert f.captured_at == 1773496800
        assert f.file_size is None
        assert f.metadata is None

    def test_with_all_fields(self) -> None:
        f = Frame(
            id=1,
            filename="test.jpg",
            captured_at=1000,
            file_size=50000,
            file_path="2026/01/01/test.jpg",
            thumb_path="2026/01/01/thumb/test.jpg",
            metadata='{"motion": 0.5}',
        )
        assert f.file_size == 50000
        assert f.thumb_path == "2026/01/01/thumb/test.jpg"


class TestFrameList:
    def test_create(self) -> None:
        fl = FrameList(
            frames=[
                Frame(id=1, filename="a.jpg", captured_at=1000, file_path="a.jpg"),
            ],
            total=10,
            offset=0,
            limit=1,
            has_more=True,
        )
        assert len(fl.frames) == 1
        assert fl.has_more

    def test_empty(self) -> None:
        fl = FrameList(frames=[], total=0, offset=0, limit=100, has_more=False)
        assert not fl.has_more


class TestTimeRange:
    def test_create(self) -> None:
        tr = TimeRange(start=1000, end=2000)
        assert tr.end - tr.start == 1000


class TestCaptureStatus:
    def test_defaults(self) -> None:
        cs = CaptureStatus(running=False)
        assert cs.pid is None
        assert cs.frames_captured == 0
        assert cs.errors == 0

    def test_running(self) -> None:
        cs = CaptureStatus(running=True, pid=1234, frames_captured=100, last_capture_at=1000)
        assert cs.running
        assert cs.pid == 1234


class TestSystemStatus:
    def test_create(self) -> None:
        ss = SystemStatus(
            capture=CaptureStatus(running=True),
            capture_fps=0.5,
            total_frames=5000,
            disk_free_mb=50000,
            disk_used_mb=10000,
            uptime_seconds=3600,
        )
        assert ss.cpu_temp is None
        assert ss.cpu_percent is None
        assert ss.mem_used_mb is None
        assert ss.net_rx_kbps is None
        assert ss.net_tx_kbps is None
        assert ss.total_frames == 5000
        assert ss.capture_fps == 0.5

    def test_with_sys_stats(self) -> None:
        ss = SystemStatus(
            capture=CaptureStatus(running=True),
            capture_fps=1.0,
            total_frames=100,
            disk_free_mb=5000,
            disk_used_mb=10000,
            cpu_temp=55.2,
            cpu_percent=42.3,
            mem_used_mb=320,
            mem_total_mb=460,
            net_rx_kbps=150.5,
            net_tx_kbps=2048.0,
            uptime_seconds=7200,
        )
        assert ss.cpu_percent == 42.3
        assert ss.mem_used_mb == 320
        assert ss.net_tx_kbps == 2048.0
