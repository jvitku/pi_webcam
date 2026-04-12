"""Retention worker — cleans up old frames based on age and disk space."""

from __future__ import annotations

import asyncio
import logging
import shutil
from pathlib import Path

from pi_webcam.config import Settings
from pi_webcam.database import Database

logger = logging.getLogger(__name__)


def get_disk_free_mb(path: Path) -> int:
    """Get free disk space in MB for the partition containing path."""
    usage = shutil.disk_usage(str(path))
    return int(usage.free / (1024 * 1024))


def get_disk_used_mb(path: Path) -> int:
    """Get used disk space in MB for the partition containing path."""
    usage = shutil.disk_usage(str(path))
    return int(usage.used / (1024 * 1024))


def delete_frame_files(frames_dir: Path, paths: list[tuple[str, str | None]]) -> int:
    """Delete frame and thumbnail files from disk. Returns count of deleted files."""
    deleted = 0
    for file_path, thumb_path in paths:
        full = frames_dir / file_path
        if full.exists():
            full.unlink()
            deleted += 1

        if thumb_path:
            thumb_full = frames_dir / thumb_path
            if thumb_full.exists():
                thumb_full.unlink()

    return deleted


def clean_empty_dirs(frames_dir: Path) -> int:
    """Remove empty directories under frames_dir. Returns count removed."""
    import os

    removed = 0
    # os.walk(topdown=False) visits leaves first and is memory-efficient
    # (holds one directory at a time). The old rglob("*") + sorted() approach
    # materialised every file AND directory into a sorted list — 1.2M+ Path
    # objects (~180 MB) for 14 days of frames on the Pi Zero.
    for dirpath, _dirnames, _filenames in os.walk(str(frames_dir), topdown=False):
        p = Path(dirpath)
        if p == frames_dir:
            continue
        # Re-check the filesystem because earlier iterations may have removed
        # children since os.walk enumerated them.
        if not any(p.iterdir()):
            p.rmdir()
            removed += 1
    return removed


def run_age_cleanup(settings: Settings, db: Database) -> int:
    """Delete frames older than retention_days. Returns count deleted."""
    import time

    cutoff = int(time.time()) - (settings.retention_days * 86400)
    paths = db.delete_frames_before(cutoff)
    if not paths:
        return 0

    deleted = delete_frame_files(settings.frames_dir, paths)
    logger.info(
        "Age cleanup: removed %d frames older than %d days",
        deleted, settings.retention_days,
    )
    return deleted


def run_watermark_cleanup(settings: Settings, db: Database) -> int:
    """Delete oldest frames until free disk > watermark. Returns count deleted."""
    total_deleted = 0
    batch_size = 100

    while True:
        free_mb = get_disk_free_mb(settings.data_dir)
        if free_mb >= settings.disk_watermark_mb:
            break

        paths = db.delete_oldest_frames(batch_size)
        if not paths:
            logger.warning("Disk low (%d MB free) but no more frames to delete", free_mb)
            break

        deleted = delete_frame_files(settings.frames_dir, paths)
        total_deleted += deleted

    if total_deleted:
        logger.info("Watermark cleanup: removed %d frames (free: %d MB)", total_deleted,
                     get_disk_free_mb(settings.data_dir))
    return total_deleted


def run_cleanup(settings: Settings, db: Database) -> tuple[int, int]:
    """Run full cleanup: age-based then watermark-based."""
    age_deleted = run_age_cleanup(settings, db)
    watermark_deleted = run_watermark_cleanup(settings, db)

    if age_deleted or watermark_deleted:
        clean_empty_dirs(settings.frames_dir)
        db.run_incremental_vacuum()

    # Always checkpoint WAL — inserts accumulate even without deletions.
    # Without this, the WAL file grows for days, causing reads to crawl.
    db.wal_checkpoint()

    # Full VACUUM once per day to defragment page layout.
    if db.full_vacuum_if_needed():
        logger.info("Full VACUUM completed")

    return age_deleted, watermark_deleted


async def retention_loop(settings: Settings, db: Database, stop_event: asyncio.Event) -> None:
    """Run cleanup periodically until stop_event is set."""
    interval = settings.retention_check_minutes * 60
    while not stop_event.is_set():
        try:
            await asyncio.to_thread(run_cleanup, settings, db)
        except Exception:
            logger.exception("Retention cleanup failed")

        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval)
            break
        except TimeoutError:
            pass
