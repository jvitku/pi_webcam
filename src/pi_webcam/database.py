"""SQLite database operations for frame metadata."""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import Any

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS frames (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    filename    TEXT    NOT NULL UNIQUE,
    captured_at INTEGER NOT NULL,
    file_size   INTEGER,
    file_path   TEXT    NOT NULL,
    thumb_path  TEXT,
    metadata    TEXT,
    created_at  INTEGER DEFAULT (unixepoch())
);

CREATE INDEX IF NOT EXISTS idx_frames_captured_at ON frames(captured_at);
"""


class Database:
    """Synchronous SQLite database wrapper.

    For use with FastAPI, wrap calls in asyncio.to_thread() or run_in_executor().
    """

    def __init__(self, db_path: Path | str) -> None:
        self._db_path = str(db_path)
        self._conn: sqlite3.Connection | None = None
        self._last_full_vacuum: float = 0.0

    def connect(self) -> None:
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA auto_vacuum=INCREMENTAL")
        self._conn.execute("PRAGMA busy_timeout=30000")  # 30 s — covers daily VACUUM
        # Performance tuning for Pi Zero 2W (512 MB RAM):
        self._conn.execute("PRAGMA mmap_size=67108864")  # 64 MB memory-mapped I/O
        self._conn.execute("PRAGMA cache_size=-4000")  # 4 MB page cache
        self._conn.execute("PRAGMA temp_store=MEMORY")  # temp tables in RAM

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            raise RuntimeError("Database not connected. Call connect() first.")
        return self._conn

    def init_schema(self) -> None:
        self.conn.executescript(SCHEMA_SQL)

    def insert_frame(
        self,
        filename: str,
        captured_at: int,
        file_path: str,
        file_size: int | None = None,
        thumb_path: str | None = None,
        metadata: str | None = None,
    ) -> int:
        cursor = self.conn.execute(
            """INSERT INTO frames
               (filename, captured_at, file_size, file_path, thumb_path, metadata)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (filename, captured_at, file_size, file_path, thumb_path, metadata),
        )
        self.conn.commit()
        return cursor.lastrowid or 0

    def get_frame_by_id(self, frame_id: int) -> dict[str, Any] | None:
        row = self.conn.execute("SELECT * FROM frames WHERE id = ?", (frame_id,)).fetchone()
        return dict(row) if row else None

    def get_latest_frame(self) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT * FROM frames ORDER BY captured_at DESC LIMIT 1"
        ).fetchone()
        return dict(row) if row else None

    def get_frames(
        self,
        start: int | None = None,
        end: int | None = None,
        limit: int = 100,
        offset: int = 0,
        sample: int = 1,
    ) -> tuple[list[dict[str, Any]], int]:
        """Return (frames, total_count) for the given time range.

        If sample > 1, return every Nth frame (for efficient overview).
        """
        conditions: list[str] = []
        params: list[Any] = []

        if start is not None:
            conditions.append("captured_at >= ?")
            params.append(start)
        if end is not None:
            conditions.append("captured_at <= ?")
            params.append(end)

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        count_row = self.conn.execute(
            f"SELECT COUNT(*) FROM frames {where}", params  # noqa: S608
        ).fetchone()
        total = count_row[0] if count_row else 0

        if sample > 1:
            # Use id-based modulo instead of ROW_NUMBER() window function.
            # ROW_NUMBER() materializes the entire result set in memory to
            # assign row numbers — on 600K+ rows this exhausts the Pi Zero's
            # 512 MB RAM. Modulo on the autoincrement id uses no extra memory
            # and still produces approximately evenly-spaced samples because
            # ids are assigned in chronological insertion order.
            sample_cond = "id % ? = 0"
            if conditions:
                full_where = f"WHERE {' AND '.join(conditions)} AND {sample_cond}"
            else:
                full_where = f"WHERE {sample_cond}"
            rows = self.conn.execute(
                f"SELECT * FROM frames {full_where}"  # noqa: S608
                " ORDER BY id ASC LIMIT ? OFFSET ?",
                [*params, sample, limit, offset],
            ).fetchall()
        else:
            rows = self.conn.execute(
                f"SELECT * FROM frames {where}"  # noqa: S608
                " ORDER BY captured_at ASC LIMIT ? OFFSET ?",
                [*params, limit, offset],
            ).fetchall()

        return [dict(r) for r in rows], total

    def get_days_with_frames(self) -> list[str]:
        """Return list of dates (YYYY-MM-DD) that have frames."""
        rows = self.conn.execute(
            "SELECT DISTINCT date(captured_at, 'unixepoch', 'localtime') as day "
            "FROM frames ORDER BY day DESC"
        ).fetchall()
        return [row[0] for row in rows]

    def get_frame_count(self) -> int:
        row = self.conn.execute("SELECT COUNT(*) FROM frames").fetchone()
        return row[0] if row else 0

    def delete_frames_before(
        self, timestamp: int, batch_size: int = 5000,
    ) -> list[tuple[str, str | None]]:
        """Delete frames older than timestamp. Returns list of (file_path, thumb_path).

        Processes in batches to avoid loading hundreds of thousands of rows
        into memory at once (e.g. when retention_days is reduced or the Pi
        has been offline for a while).
        """
        all_paths: list[tuple[str, str | None]] = []
        while True:
            rows = self.conn.execute(
                "SELECT id, file_path, thumb_path FROM frames "
                "WHERE captured_at < ? ORDER BY id ASC LIMIT ?",
                (timestamp, batch_size),
            ).fetchall()
            if not rows:
                break
            batch_paths = [(row[1], row[2]) for row in rows]
            id_list = [row[0] for row in rows]
            placeholders = ",".join("?" * len(id_list))
            self.conn.execute(
                f"DELETE FROM frames WHERE id IN ({placeholders})",  # noqa: S608
                id_list,
            )
            self.conn.commit()
            all_paths.extend(batch_paths)
        return all_paths

    def delete_oldest_frames(self, count: int) -> list[tuple[str, str | None]]:
        """Delete the N oldest frames. Returns list of (file_path, thumb_path)."""
        rows = self.conn.execute(
            "SELECT file_path, thumb_path FROM frames ORDER BY captured_at ASC LIMIT ?", (count,)
        ).fetchall()
        paths = [(row[0], row[1]) for row in rows]

        if paths:
            ids = self.conn.execute(
                "SELECT id FROM frames ORDER BY captured_at ASC LIMIT ?", (count,)
            ).fetchall()
            id_list = [r[0] for r in ids]
            placeholders = ",".join("?" * len(id_list))
            self.conn.execute(
                f"DELETE FROM frames WHERE id IN ({placeholders})", id_list  # noqa: S608
            )
            self.conn.commit()

        return paths

    def run_incremental_vacuum(self) -> None:
        self.conn.execute("PRAGMA incremental_vacuum")

    def wal_checkpoint(self) -> None:
        """Truncate the WAL file to keep reads fast and reclaim disk space.

        Without periodic checkpointing, the WAL grows unbounded and every
        read must scan through it, causing severe slowdowns on the Pi Zero.
        """
        self.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")

    def full_vacuum_if_needed(self, interval_seconds: int = 86400) -> bool:
        """Run a full VACUUM if enough time has elapsed since the last one.

        Unlike incremental_vacuum (which only returns free pages),
        full VACUUM rebuilds the entire database file, defragmenting page
        layout.  After months of insert/delete cycles, scattered pages
        degrade sequential-read performance — this resets it.

        Default interval is 24 hours.  Takes ~10-30 s on a 100 MB DB on
        the Pi Zero and briefly blocks all other DB access.
        """
        now = time.time()
        if now - self._last_full_vacuum < interval_seconds:
            return False
        self.conn.execute("VACUUM")
        self._last_full_vacuum = now
        return True

    def get_all_file_paths(self) -> set[str]:
        """Return set of all file_path values in the database."""
        rows = self.conn.execute("SELECT file_path FROM frames").fetchall()
        return {row[0] for row in rows}
