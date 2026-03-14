"""SQLite database operations for frame metadata."""

from __future__ import annotations

import sqlite3
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

    def connect(self) -> None:
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA auto_vacuum=INCREMENTAL")
        self._conn.execute("PRAGMA busy_timeout=5000")

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
    ) -> tuple[list[dict[str, Any]], int]:
        """Return (frames, total_count) for the given time range with pagination."""
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

        rows = self.conn.execute(
            f"SELECT * FROM frames {where} ORDER BY captured_at ASC LIMIT ? OFFSET ?",  # noqa: S608
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

    def delete_frames_before(self, timestamp: int) -> list[tuple[str, str | None]]:
        """Delete frames older than timestamp. Returns list of (file_path, thumb_path)."""
        rows = self.conn.execute(
            "SELECT file_path, thumb_path FROM frames WHERE captured_at < ?", (timestamp,)
        ).fetchall()
        paths = [(row[0], row[1]) for row in rows]

        if paths:
            self.conn.execute("DELETE FROM frames WHERE captured_at < ?", (timestamp,))
            self.conn.commit()

        return paths

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

    def get_all_file_paths(self) -> set[str]:
        """Return set of all file_path values in the database."""
        rows = self.conn.execute("SELECT file_path FROM frames").fetchall()
        return {row[0] for row in rows}
