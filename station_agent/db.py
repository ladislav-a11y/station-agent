"""SQLite perzistence: historie spotů, "worked" DXCC cache, audit AUTO TUNE.

Žádná ORM vrstva navíc -- stdlib sqlite3 je pro rozsah projektu dostatečný
a snadno testovatelný přes ``:memory:`` databázi.
"""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path

from station_agent.models import Spot

SCHEMA = """
CREATE TABLE IF NOT EXISTS spots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    callsign TEXT NOT NULL,
    freq_hz INTEGER NOT NULL,
    mode TEXT NOT NULL,
    band TEXT NOT NULL,
    ts REAL NOT NULL,
    source TEXT NOT NULL,
    snr_db REAL,
    comment TEXT DEFAULT '',
    spotter TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_spots_callsign_ts ON spots(callsign, ts);
CREATE INDEX IF NOT EXISTS idx_spots_ts ON spots(ts);

CREATE TABLE IF NOT EXISTS worked_entities (
    dxcc_name TEXT PRIMARY KEY,
    first_worked_ts REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS autotune_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    callsign TEXT NOT NULL,
    freq_hz INTEGER NOT NULL,
    mode TEXT NOT NULL,
    score INTEGER,
    reason TEXT NOT NULL
);
"""


class Database:
    def __init__(self, path: str | Path = ":memory:"):
        self.path = str(path)
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "Database":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

    # -- spots -----------------------------------------------------------

    def insert_spot(self, spot: Spot) -> None:
        self._conn.execute(
            """
            INSERT INTO spots (callsign, freq_hz, mode, band, ts, source, snr_db, comment, spotter)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                spot.callsign,
                spot.freq_hz,
                spot.mode,
                spot.band,
                spot.timestamp,
                spot.source,
                spot.snr_db,
                spot.comment,
                spot.spotter,
            ),
        )
        self._conn.commit()

    def recent_spots(self, max_age_seconds: float, now: float | None = None) -> list[Spot]:
        now = time.time() if now is None else now
        cutoff = now - max_age_seconds
        rows = self._conn.execute(
            "SELECT * FROM spots WHERE ts >= ? ORDER BY ts DESC", (cutoff,)
        ).fetchall()
        return [
            Spot(
                callsign=row["callsign"],
                freq_hz=row["freq_hz"],
                mode=row["mode"],
                timestamp=row["ts"],
                source=row["source"],
                snr_db=row["snr_db"],
                comment=row["comment"] or "",
                spotter=row["spotter"] or "",
                band=row["band"],
            )
            for row in rows
        ]

    def purge_older_than(self, max_age_seconds: float, now: float | None = None) -> int:
        now = time.time() if now is None else now
        cutoff = now - max_age_seconds
        cur = self._conn.execute("DELETE FROM spots WHERE ts < ?", (cutoff,))
        self._conn.commit()
        return cur.rowcount

    # -- worked DXCC cache -------------------------------------------------

    def mark_worked(self, dxcc_name: str, ts: float | None = None) -> None:
        ts = time.time() if ts is None else ts
        self._conn.execute(
            "INSERT OR IGNORE INTO worked_entities (dxcc_name, first_worked_ts) VALUES (?, ?)",
            (dxcc_name, ts),
        )
        self._conn.commit()

    def is_worked(self, dxcc_name: str) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM worked_entities WHERE dxcc_name = ?", (dxcc_name,)
        ).fetchone()
        return row is not None

    def worked_entities(self) -> set[str]:
        rows = self._conn.execute("SELECT dxcc_name FROM worked_entities").fetchall()
        return {row["dxcc_name"] for row in rows}

    # -- AUTO TUNE audit log ------------------------------------------------

    def log_autotune(
        self,
        callsign: str,
        freq_hz: int,
        mode: str,
        score: int | None,
        reason: str,
        ts: float | None = None,
    ) -> None:
        ts = time.time() if ts is None else ts
        self._conn.execute(
            """
            INSERT INTO autotune_log (ts, callsign, freq_hz, mode, score, reason)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (ts, callsign, freq_hz, mode, score, reason),
        )
        self._conn.commit()

    def autotune_history(self, limit: int = 50) -> list[sqlite3.Row]:
        return self._conn.execute(
            "SELECT * FROM autotune_log ORDER BY ts DESC LIMIT ?", (limit,)
        ).fetchall()
