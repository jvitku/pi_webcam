"""FastAPI web server — API routes and static file serving."""

import base64
import secrets
import time
from pathlib import Path

import httpx
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.base import BaseHTTPMiddleware

from pi_webcam.config import Settings
from pi_webcam.database import Database
from pi_webcam.models import CaptureStatus, Frame, FrameList, SystemStatus

# --- System stats helpers ---

_prev_cpu: tuple[float, float] | None = None
_prev_net: tuple[float, int, int] | None = None  # (time, rx_bytes, tx_bytes)


def _read_cpu_percent() -> float | None:
    """Read CPU usage from /proc/stat. Returns percent (0-100) since last call."""
    global _prev_cpu  # noqa: PLW0603
    try:
        with open("/proc/stat") as f:
            line = f.readline()
        parts = line.split()
        idle = float(parts[4])
        total = sum(float(x) for x in parts[1:])

        if _prev_cpu is None:
            _prev_cpu = (total, idle)
            return None

        prev_total, prev_idle = _prev_cpu
        _prev_cpu = (total, idle)

        dt = total - prev_total
        di = idle - prev_idle
        if dt <= 0:
            return 0.0
        return round((1.0 - di / dt) * 100, 1)
    except (FileNotFoundError, ValueError, IndexError):
        return None


def _read_mem_info() -> tuple[int, int] | None:
    """Read memory info. Returns (used_mb, total_mb) or None."""
    try:
        info: dict[str, int] = {}
        with open("/proc/meminfo") as f:
            for line in f:
                parts = line.split()
                if parts[0] in ("MemTotal:", "MemAvailable:"):
                    info[parts[0]] = int(parts[1])  # kB
                if len(info) == 2:
                    break
        total = info["MemTotal:"] // 1024
        avail = info["MemAvailable:"] // 1024
        return (total - avail, total)
    except (FileNotFoundError, ValueError, KeyError):
        return None


def _read_net_rates() -> tuple[float, float] | None:
    """Read network throughput in kbps for wlan0. Returns (rx_kbps, tx_kbps)."""
    global _prev_net  # noqa: PLW0603
    try:
        now = time.time()
        rx_bytes = tx_bytes = 0
        with open("/proc/net/dev") as f:
            for line in f:
                if "wlan0" in line:
                    parts = line.split()
                    rx_bytes = int(parts[1])
                    tx_bytes = int(parts[9])
                    break
        if rx_bytes == 0 and tx_bytes == 0:
            return None

        if _prev_net is None:
            _prev_net = (now, rx_bytes, tx_bytes)
            return None

        prev_time, prev_rx, prev_tx = _prev_net
        _prev_net = (now, rx_bytes, tx_bytes)

        dt = now - prev_time
        if dt <= 0:
            return (0.0, 0.0)
        rx_kbps = round((rx_bytes - prev_rx) / dt / 1024 * 8, 1)
        tx_kbps = round((tx_bytes - prev_tx) / dt / 1024 * 8, 1)
        return (rx_kbps, tx_kbps)
    except (FileNotFoundError, ValueError, IndexError):
        return None


def _read_throttled() -> int | None:
    """Read throttle status from vcgencmd. Returns bitmask or None."""
    import subprocess

    try:
        result = subprocess.run(
            ["vcgencmd", "get_throttled"],
            capture_output=True, text=True, timeout=2,
        )
        # Output: "throttled=0x0"
        val = result.stdout.strip().split("=")[-1]
        return int(val, 16)
    except (FileNotFoundError, subprocess.TimeoutExpired, ValueError):
        return None


def validate_image_path(path: str) -> str:
    """Validate image path to prevent path traversal."""
    if ".." in path or path.startswith("/") or path.startswith("\\"):
        raise HTTPException(status_code=400, detail="Invalid path")
    if not path.endswith((".jpg", ".jpeg")):
        raise HTTPException(status_code=400, detail="Invalid file extension")
    return path


class BasicAuthMiddleware(BaseHTTPMiddleware):
    """Optional HTTP Basic Auth middleware."""

    async def dispatch(self, request: Request, call_next):  # type: ignore[no-untyped-def]
        settings: Settings = request.app.state.settings
        if not settings.auth_enabled:
            return await call_next(request)

        # Skip auth for static files
        if request.url.path.startswith("/static"):
            return await call_next(request)

        auth_header = request.headers.get("authorization", "")
        if not auth_header.startswith("Basic "):
            return JSONResponse(
                status_code=401,
                content={"detail": "Authentication required"},
                headers={"WWW-Authenticate": "Basic"},
            )

        try:
            decoded = base64.b64decode(auth_header[6:]).decode("utf-8")
            username, password = decoded.split(":", 1)
        except (ValueError, UnicodeDecodeError):
            return JSONResponse(
                status_code=401,
                content={"detail": "Invalid credentials"},
                headers={"WWW-Authenticate": "Basic"},
            )

        username_ok = secrets.compare_digest(
            username.encode(), settings.auth_username.encode()
        )
        password_ok = secrets.compare_digest(
            password.encode(), settings.auth_password.encode()
        )
        if not (username_ok and password_ok):
            return JSONResponse(
                status_code=401,
                content={"detail": "Invalid credentials"},
                headers={"WWW-Authenticate": "Basic"},
            )

        return await call_next(request)


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create and configure the FastAPI application."""
    if settings is None:
        settings = Settings()

    app = FastAPI(title="Pi Webcam", version="0.1.0")

    # Store settings and DB on app state
    app.state.settings = settings
    app.state.db = Database(settings.db_path)
    app.state.capture_status = CaptureStatus(running=False)
    app.state.start_time = int(time.time())

    # Auth middleware
    app.add_middleware(BasicAuthMiddleware)

    # Templates
    static_dir = Path(__file__).parent.parent.parent / "static"
    if static_dir.exists():
        templates = Jinja2Templates(directory=str(static_dir))
        app.mount(
            "/static", StaticFiles(directory=str(static_dir)), name="static"
        )
    else:
        templates = None

    def get_db() -> Database:
        return app.state.db  # type: ignore[no-any-return]

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request) -> HTMLResponse:
        if templates is None:
            return HTMLResponse(
                "<h1>Pi Webcam</h1><p>Static files not found.</p>"
            )
        return templates.TemplateResponse(request, "index.html", {
            "webrtc_url": settings.webrtc_url,
            "hls_url": settings.hls_url,
        })

    @app.get("/api/frames")
    async def list_frames(
        start: int | None = Query(default=None),
        end: int | None = Query(default=None),
        limit: int = Query(default=100, ge=1, le=10000),
        offset: int = Query(default=0, ge=0),
        sample: int = Query(default=1, ge=1, le=1000),
        db: Database = Depends(get_db),
    ) -> FrameList:
        frames_data, total = db.get_frames(
            start=start, end=end, limit=limit, offset=offset,
            sample=sample,
        )
        frames = [Frame(**f) for f in frames_data]
        return FrameList(
            frames=frames,
            total=total,
            offset=offset,
            limit=limit,
            has_more=(offset + limit) < total,
        )

    @app.get("/api/frames/latest")
    async def latest_frame(
        db: Database = Depends(get_db),
    ) -> Frame:
        data = db.get_latest_frame()
        if data is None:
            raise HTTPException(
                status_code=404, detail="No frames captured yet"
            )
        return Frame(**data)

    @app.get("/api/frames/{frame_id}")
    async def get_frame(
        frame_id: int,
        db: Database = Depends(get_db),
    ) -> Frame:
        data = db.get_frame_by_id(frame_id)
        if data is None:
            raise HTTPException(status_code=404, detail="Frame not found")
        return Frame(**data)

    @app.get("/api/days")
    async def list_days(
        db: Database = Depends(get_db),
    ) -> list[str]:
        return db.get_days_with_frames()

    @app.get("/api/status")
    async def system_status(
        db: Database = Depends(get_db),
    ) -> SystemStatus:
        s: Settings = app.state.settings
        capture: CaptureStatus = app.state.capture_status

        cpu_temp: float | None = None
        try:
            with open("/sys/class/thermal/thermal_zone0/temp") as f:
                cpu_temp = int(f.read().strip()) / 1000.0
        except (FileNotFoundError, ValueError):
            pass

        cpu_percent = _read_cpu_percent()
        mem = _read_mem_info()
        net = _read_net_rates()
        throttled = _read_throttled()

        from pi_webcam.retention import get_disk_free_mb, get_disk_used_mb

        return SystemStatus(
            capture=capture,
            capture_fps=s.capture_fps,
            total_frames=db.get_frame_count(),
            disk_free_mb=get_disk_free_mb(s.data_dir),
            disk_used_mb=get_disk_used_mb(s.data_dir),
            cpu_temp=cpu_temp,
            cpu_percent=cpu_percent,
            mem_used_mb=mem[0] if mem else None,
            mem_total_mb=mem[1] if mem else None,
            net_rx_kbps=net[0] if net else None,
            net_tx_kbps=net[1] if net else None,
            throttled=throttled,
            uptime_seconds=int(time.time()) - app.state.start_time,
        )

    @app.post("/api/capture-fps")
    async def set_capture_fps(
        fps: float = Query(gt=0, le=30),
    ) -> dict[str, object]:
        s: Settings = app.state.settings
        old_fps = s.capture_fps
        # Update the in-memory setting (not persisted to env file)
        object.__setattr__(s, "capture_fps", fps)

        # Restart ffmpeg with new FPS
        capture_worker = getattr(app.state, "capture_worker", None)
        if capture_worker is not None:
            import asyncio

            asyncio.create_task(capture_worker.restart_ffmpeg())

        return {"old_fps": old_fps, "new_fps": fps}

    @app.get("/api/camera")
    async def get_camera_settings() -> dict[str, object]:
        """Get current camera settings from MediaMTX."""
        try:
            async with httpx.AsyncClient() as client:
                r = await client.get(
                    f"{settings.mediamtx_api_url}/v3/config/paths/get/cam",
                    timeout=5,
                )
                if r.status_code != 200:
                    return {"error": "MediaMTX API unavailable"}
                data = r.json()
                return {
                    "afMode": data.get("rpiCameraAfMode", "auto"),
                    "lensPosition": data.get(
                        "rpiCameraLensPosition", 0.0
                    ),
                    "ev": data.get("rpiCameraEV", 0),
                    "metering": data.get(
                        "rpiCameraMetering", "centre"
                    ),
                    "brightness": data.get(
                        "rpiCameraBrightness", 0.0
                    ),
                    "contrast": data.get("rpiCameraContrast", 1.0),
                    "saturation": data.get(
                        "rpiCameraSaturation", 1.0
                    ),
                }
        except httpx.HTTPError as exc:
            raise HTTPException(
                status_code=502, detail="Cannot reach MediaMTX API"
            ) from exc

    @app.patch("/api/camera")
    async def update_camera_settings(
        request: Request,
    ) -> dict[str, object]:
        """Update camera settings via MediaMTX API."""
        body = await request.json()

        # Map our simple keys to MediaMTX rpiCamera keys
        key_map = {
            "afMode": "rpiCameraAfMode",
            "lensPosition": "rpiCameraLensPosition",
            "afWindow": "rpiCameraAfWindow",
            "ev": "rpiCameraEV",
            "metering": "rpiCameraMetering",
            "roi": "rpiCameraROI",
            "brightness": "rpiCameraBrightness",
            "contrast": "rpiCameraContrast",
            "saturation": "rpiCameraSaturation",
        }

        mtx_body: dict[str, object] = {}
        for key, val in body.items():
            if key in key_map:
                mtx_body[key_map[key]] = val

        if not mtx_body:
            raise HTTPException(
                status_code=400, detail="No valid settings provided"
            )

        try:
            async with httpx.AsyncClient() as client:
                # Try PATCH first (v1.13+), fall back to
                # read-modify-replace (v1.12)
                r = await client.patch(
                    f"{settings.mediamtx_api_url}"
                    "/v3/config/paths/patch/cam",
                    json=mtx_body,
                    timeout=5,
                )
                if r.status_code == 404:
                    # Fallback: read current, merge, replace
                    r_get = await client.get(
                        f"{settings.mediamtx_api_url}"
                        "/v3/config/paths/get/cam",
                        timeout=5,
                    )
                    if r_get.status_code != 200:
                        return {"error": "Cannot read config"}
                    current = r_get.json()
                    current.pop("name", None)
                    current.update(mtx_body)
                    r = await client.post(
                        f"{settings.mediamtx_api_url}"
                        "/v3/config/paths/replace/cam",
                        json=current,
                        timeout=5,
                    )
                if r.status_code == 200:
                    return {"applied": mtx_body}
                return {
                    "error": f"MediaMTX returned {r.status_code}",
                    "detail": r.text,
                }
        except httpx.HTTPError as exc:
            raise HTTPException(
                status_code=502, detail="Cannot reach MediaMTX API"
            ) from exc

    @app.get("/api/stream-url")
    async def stream_url() -> dict[str, str]:
        return {
            "webrtc": settings.webrtc_url,
            "hls": settings.hls_url,
        }

    @app.get("/images/{path:path}")
    async def serve_image(path: str) -> FileResponse:
        path = validate_image_path(path)
        full_path = settings.frames_dir / path
        if not full_path.exists():
            raise HTTPException(status_code=404, detail="Image not found")

        return FileResponse(
            str(full_path),
            media_type="image/jpeg",
            headers={
                "Cache-Control": "public, max-age=31536000, immutable",
            },
        )

    @app.get("/thumbs/{path:path}")
    async def serve_thumbnail(path: str) -> FileResponse:
        path = validate_image_path(path)
        full_path = settings.frames_dir / path
        if not full_path.exists():
            raise HTTPException(
                status_code=404, detail="Thumbnail not found"
            )

        return FileResponse(
            str(full_path),
            media_type="image/jpeg",
            headers={
                "Cache-Control": "public, max-age=31536000, immutable",
            },
        )

    return app
