"""FastAPI web server — API routes and static file serving."""

import base64
import secrets
import time
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.base import BaseHTTPMiddleware

from pi_webcam.config import Settings
from pi_webcam.database import Database
from pi_webcam.models import CaptureStatus, Frame, FrameList, SystemStatus


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
        limit: int = Query(default=100, ge=1, le=1000),
        offset: int = Query(default=0, ge=0),
        db: Database = Depends(get_db),
    ) -> FrameList:
        frames_data, total = db.get_frames(
            start=start, end=end, limit=limit, offset=offset,
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

        from pi_webcam.retention import get_disk_free_mb, get_disk_used_mb

        return SystemStatus(
            capture=capture,
            capture_fps=s.capture_fps,
            total_frames=db.get_frame_count(),
            disk_free_mb=get_disk_free_mb(s.data_dir),
            disk_used_mb=get_disk_used_mb(s.data_dir),
            cpu_temp=cpu_temp,
            uptime_seconds=int(time.time()) - app.state.start_time,
        )

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
