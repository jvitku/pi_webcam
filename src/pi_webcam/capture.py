"""Frame capture worker — extracts JPEGs from RTSP stream via ffmpeg."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import re
from pathlib import Path

from pi_webcam.config import Settings
from pi_webcam.database import Database
from pi_webcam.thumbnails import generate_thumbnail

logger = logging.getLogger(__name__)

# Pattern for filenames produced by ffmpeg -strftime: YYYYMMDD_HHMMSS.jpg
FILENAME_PATTERN = re.compile(r"^(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})\.jpg$")


def filename_to_epoch(filename: str) -> int | None:
    """Parse a timestamped filename into Unix epoch.

    Filenames are in local time (from ffmpeg -strftime using system clock).
    """
    match = FILENAME_PATTERN.match(filename)
    if not match:
        return None
    year, month, day, hour, minute, second = (int(g) for g in match.groups())
    try:
        # Local time — no tzinfo, mktime uses system timezone
        import time as _time

        local_dt = _time.mktime((year, month, day, hour, minute, second, 0, 0, -1))
        return int(local_dt)
    except (ValueError, OverflowError):
        return None


def relative_path_for_timestamp(filename: str) -> str | None:
    """Generate date-based relative path from a timestamped filename.

    E.g. '20260314_153022.jpg' -> '2026/03/14/153022.jpg'
    """
    match = FILENAME_PATTERN.match(filename)
    if not match:
        return None
    year, month, day, hour, minute, second = match.groups()
    return f"{year}/{month}/{day}/{hour}{minute}{second}.jpg"


def thumb_relative_path(file_rel_path: str) -> str:
    """Generate thumbnail relative path from a frame relative path.

    E.g. '2026/03/14/153022.jpg' -> '2026/03/14/thumb/153022.jpg'
    """
    parts = file_rel_path.rsplit("/", 1)
    if len(parts) == 2:
        return f"{parts[0]}/thumb/{parts[1]}"
    return f"thumb/{parts[0]}"


def build_ffmpeg_command(settings: Settings, output_dir: Path) -> list[str]:
    """Build the ffmpeg command for capturing frames from RTSP."""
    return [
        "ffmpeg",
        "-rtsp_transport", "tcp",
        "-fflags", "nobuffer",
        "-flags", "low_delay",
        "-i", settings.rtsp_url,
        "-vf", f"fps={settings.capture_fps}",
        "-q:v", str(settings.jpeg_quality),
        "-f", "image2",
        "-strftime", "1",
        str(output_dir / "%Y%m%d_%H%M%S.jpg"),
    ]


class CaptureWorker:
    """Manages ffmpeg subprocess and registers new frames in the database."""

    def __init__(self, settings: Settings, db: Database) -> None:
        self.settings = settings
        self.db = db
        self.running = False
        self.pid: int | None = None
        self.frames_captured = 0
        self.last_capture_at: int | None = None
        self.errors = 0
        self._process: asyncio.subprocess.Process | None = None
        self._known_files: set[str] = set()
        self._stop_event = asyncio.Event()

    @property
    def output_dir(self) -> Path:
        return self.settings.frames_dir

    async def start(self) -> None:
        """Start the capture loop."""
        self.running = True
        self._stop_event.clear()
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Seed known files from existing directory contents
        self._known_files = {
            str(p) for p in self.output_dir.rglob("*.jpg") if "thumb" not in str(p)
        }

        backoff = 1.0
        max_backoff = 30.0

        while not self._stop_event.is_set():
            try:
                await self._run_ffmpeg()
                backoff = 1.0  # Reset on clean exit
            except asyncio.CancelledError:
                break
            except Exception:
                self.errors += 1
                logger.exception("ffmpeg process failed, restarting in %.1fs", backoff)
                try:
                    await asyncio.wait_for(self._stop_event.wait(), timeout=backoff)
                    break  # Stop was requested during backoff
                except TimeoutError:
                    pass
                backoff = min(backoff * 2, max_backoff)

        self.running = False
        self.pid = None

    async def stop(self) -> None:
        """Stop the capture worker."""
        self._stop_event.set()
        if self._process and self._process.returncode is None:
            self._process.terminate()
            try:
                await asyncio.wait_for(self._process.wait(), timeout=5)
            except TimeoutError:
                self._process.kill()
        self.running = False

    async def restart_ffmpeg(self) -> None:
        """Kill the current ffmpeg process so the capture loop restarts it."""
        if self._process and self._process.returncode is None:
            self._process.terminate()
            try:
                await asyncio.wait_for(self._process.wait(), timeout=5)
            except TimeoutError:
                self._process.kill()

    async def _run_ffmpeg(self) -> None:
        """Run ffmpeg and poll for new files while it runs."""
        cmd = build_ffmpeg_command(self.settings, self.output_dir)
        logger.info("Starting ffmpeg: %s", " ".join(cmd))

        self._process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        self.pid = self._process.pid

        # Run file polling concurrently with ffmpeg
        poll_task = asyncio.create_task(self._poll_for_files())

        try:
            stderr_data = b""
            assert self._process.stderr is not None  # noqa: S101
            while True:
                try:
                    chunk = await asyncio.wait_for(
                        self._process.stderr.read(4096), timeout=1.0
                    )
                    if chunk:
                        stderr_data += chunk
                        # Log significant ffmpeg errors
                        text = chunk.decode("utf-8", errors="replace")
                        for line in text.strip().split("\n"):
                            if any(k in line.lower() for k in ("error", "fatal", "failed")):
                                logger.warning("ffmpeg: %s", line.strip())
                    elif self._process.returncode is not None:
                        break
                except TimeoutError:
                    if self._process.returncode is not None:
                        break
                    # Still running, continue polling
                    continue

            await self._process.wait()

            if self._process.returncode != 0 and not self._stop_event.is_set():
                logger.error(
                    "ffmpeg exited with code %d: %s",
                    self._process.returncode,
                    stderr_data[-500:].decode("utf-8", errors="replace"),
                )
                raise RuntimeError(f"ffmpeg exited with code {self._process.returncode}")
        finally:
            poll_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await poll_task
            # Final poll to catch any remaining files
            self._scan_and_register()

    async def _poll_for_files(self) -> None:
        """Periodically scan output directory for new JPEG files."""
        while True:
            self._scan_and_register()
            await asyncio.sleep(0.5)

    def _scan_and_register(self) -> None:
        """Find new JPEG files and register them in the database."""
        current_files = set()
        for jpg_path in self.output_dir.rglob("*.jpg"):
            if "thumb" in str(jpg_path):
                continue
            current_files.add(str(jpg_path))

        new_files = current_files - self._known_files

        for file_str in sorted(new_files):
            file_path = Path(file_str)
            self._register_frame(file_path)

        self._known_files = current_files

    def _register_frame(self, file_path: Path) -> None:
        """Register a single frame in the database and generate thumbnail."""
        filename = file_path.name
        epoch = filename_to_epoch(filename)
        if epoch is None:
            logger.warning("Skipping file with invalid name: %s", filename)
            return

        rel_path = relative_path_for_timestamp(filename)
        if rel_path is None:
            return

        # Move file to date-based directory structure
        dest = self.settings.frames_dir / rel_path
        if file_path != dest:
            dest.parent.mkdir(parents=True, exist_ok=True)
            try:
                file_path.rename(dest)
            except OSError:
                logger.warning("Failed to move %s to %s", file_path, dest)
                return

        file_size = dest.stat().st_size if dest.exists() else None

        # Generate thumbnail
        thumb_rel = thumb_relative_path(rel_path)
        thumb_dest = self.settings.frames_dir / thumb_rel
        thumb_ok = generate_thumbnail(
            dest, thumb_dest,
            width=self.settings.thumb_width,
            height=self.settings.thumb_height,
        )

        try:
            self.db.insert_frame(
                filename=filename,
                captured_at=epoch,
                file_path=rel_path,
                file_size=file_size,
                thumb_path=thumb_rel if thumb_ok else None,
            )
            self.frames_captured += 1
            self.last_capture_at = epoch
        except Exception:
            logger.exception("Failed to register frame %s", filename)
            self.errors += 1


def reconcile_frames(settings: Settings, db: Database) -> tuple[int, int]:
    """Reconcile filesystem and database on startup.

    Returns (orphan_files_registered, stale_entries_removed).
    """
    frames_dir = settings.frames_dir
    if not frames_dir.exists():
        frames_dir.mkdir(parents=True, exist_ok=True)
        return 0, 0

    # Find files on disk not in DB
    db_paths = db.get_all_file_paths()
    registered = 0

    for jpg_path in frames_dir.rglob("*.jpg"):
        if "thumb" in str(jpg_path):
            continue
        rel = str(jpg_path.relative_to(frames_dir))
        if rel not in db_paths:
            filename = jpg_path.name
            epoch = filename_to_epoch(filename)
            if epoch is None:
                # Try to extract from path structure
                continue
            file_size = jpg_path.stat().st_size
            thumb_rel = thumb_relative_path(rel)
            thumb_exists = (frames_dir / thumb_rel).exists()
            try:
                db.insert_frame(
                    filename=filename,
                    captured_at=epoch,
                    file_path=rel,
                    file_size=file_size,
                    thumb_path=thumb_rel if thumb_exists else None,
                )
                registered += 1
            except Exception:
                pass  # Duplicate or other error

    # Find DB entries without files on disk
    removed = 0
    all_db_paths = db.get_all_file_paths()
    for db_path in all_db_paths:
        full_path = frames_dir / db_path
        if not full_path.exists():
            # Remove stale entry
            db.conn.execute("DELETE FROM frames WHERE file_path = ?", (db_path,))
            removed += 1
    if removed:
        db.conn.commit()

    logger.info("Reconciliation: registered %d orphan files, removed %d stale entries",
                registered, removed)
    return registered, removed
