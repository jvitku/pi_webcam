"""Entry point — starts capture worker, retention worker, and web server."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI

from pi_webcam.capture import CaptureWorker, reconcile_frames
from pi_webcam.config import Settings, get_settings
from pi_webcam.database import Database
from pi_webcam.models import CaptureStatus
from pi_webcam.retention import retention_loop

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Manage startup and shutdown of background workers."""
    settings: Settings = app.state.settings
    db: Database = app.state.db

    # Connect database and initialize schema
    db.connect()
    db.init_schema()
    logger.info("Database initialized at %s", settings.db_path)

    # Reconcile filesystem and database
    registered, removed = reconcile_frames(settings, db)
    if registered or removed:
        logger.info(
            "Reconciled: %d registered, %d stale removed", registered, removed
        )

    # Start capture worker
    stop_event = asyncio.Event()
    capture_worker = CaptureWorker(settings, db)

    async def update_capture_status() -> None:
        """Periodically sync capture worker state to app state."""
        while not stop_event.is_set():
            app.state.capture_status = CaptureStatus(
                running=capture_worker.running,
                pid=capture_worker.pid,
                frames_captured=capture_worker.frames_captured,
                last_capture_at=capture_worker.last_capture_at,
                errors=capture_worker.errors,
            )
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=2.0)
                break
            except TimeoutError:
                pass

    capture_task = asyncio.create_task(capture_worker.start())
    status_task = asyncio.create_task(update_capture_status())
    retention_task = asyncio.create_task(retention_loop(settings, db, stop_event))

    logger.info("All workers started")

    try:
        yield
    finally:
        logger.info("Shutting down workers...")
        stop_event.set()
        await capture_worker.stop()

        # Cancel background tasks
        for task in (capture_task, status_task, retention_task):
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

        db.close()
        logger.info("Shutdown complete")


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create the full application with lifespan management."""
    from pi_webcam.server import create_app as create_server_app

    if settings is None:
        settings = get_settings()

    app = create_server_app(settings)
    app.router.lifespan_context = lifespan
    return app


def main() -> None:
    """CLI entry point."""
    settings = get_settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)

    app = create_app(settings)
    uvicorn.run(
        app,
        host=settings.host,
        port=settings.port,
        workers=1,
        log_level="info",
    )


if __name__ == "__main__":
    main()
