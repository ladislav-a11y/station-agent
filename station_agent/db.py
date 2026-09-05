"""SQLite perzistence: historie spotů, "worked" DXCC cache, audit AUTO TUNE.

Žádná ORM vrstva navíc -- stdlib sqlite3 je pro rozsah projektu dostatečný
a snadno testovatelný přes ``:memory:`` databázi.
"""

from __future__ import annotations

import json
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
    spotter TEXT DEFAULT '',
    country TEXT,
    locator TEXT,
    bearing_deg REAL,
    distance_km REAL
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

CREATE TABLE IF NOT EXISTS band_openings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    band TEXT NOT NULL,
    station_count INTEGER NOT NULL,
    reason TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_band_openings_ts ON band_openings(ts);

CREATE TABLE IF NOT EXISTS qso_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    callsign TEXT NOT NULL,
    freq_hz INTEGER NOT NULL,
    mode TEXT NOT NULL,
    band TEXT NOT NULL,
    bearing_deg REAL,
    note TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_qso_history_ts ON qso_history(ts);

CREATE TABLE IF NOT EXISTS filter_preferences (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    bands_json TEXT NOT NULL,
    modes_json TEXT NOT NULL
);
"""


class Database:
    def __init__(self, path: str | Path = ":memory:"):
        self.path = str(path)
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        try:
            self._conn.row_factory = sqlite3.Row
            self._conn.executescript(SCHEMA)
            columns = {row["name"] for row in self._conn.execute("PRAGMA table_info(band_openings)")}
            if "reason" not in columns:
                self._conn.execute("ALTER TABLE band_openings ADD COLUMN reason TEXT NOT NULL DEFAULT ''")
            spot_columns = {row["name"] for row in self._conn.execute("PRAGMA table_info(spots)")}
            for name, column_type in (
                ("country", "TEXT"),
                ("locator", "TEXT"),
                ("bearing_deg", "REAL"),
                ("distance_km", "REAL"),
            ):
                if name not in spot_columns:
                    self._conn.execute(f"ALTER TABLE spots ADD COLUMN {name} {column_type}")
            self._conn.commit()
            self._enable_incremental_vacuum()
        except Exception:
            # Např. `path` míří na existující soubor, který není platná
            # SQLite databáze (sqlite3.DatabaseError "file is not a
            # database") -- bez tohoto by `self._conn` zůstalo otevřené a
            # drželo by OS zámek na souboru, i když konstruktor selhal a
            # instance se nikdy nevrátila volajícímu (viz cli.py
            # build_app_state, stejný vzor pro selhání po úspěšném
            # otevření DB).
            self._conn.close()
            raise

    def _enable_incremental_vacuum(self) -> None:
        """Zapne ``auto_vacuum = INCREMENTAL`` a jednorázově zkomprimuje
        soubor.

        Live test 03.09.2026 odhalil nestandardní chování: `spots` se sice
        pravidelně čistí (viz `app_state.refresh_candidates` ->
        `purge_older_than`), ale bez `auto_vacuum` SQLite uvolněné stránky
        po DELETE nevrací OS -- zůstávají ve freelistu uvnitř souboru. Po
        dnech nepřetržitého provozu tak soubor na disku naroste na stovky
        MB, i když v tabulkách reálně zůstávají jen řádky z posledního
        `spot_max_age_minutes` okna (ověřeno: `station_agent.sqlite3` mělo
        72051 stránek, z toho 71817 (99,7 %) ve freelistu). Přepnutí režimu
        na existující databázi vyžaduje `VACUUM` -- proto se dělá jen
        jednou (další start už `auto_vacuum` najde zapnuté a přeskočí).
        In-memory databáze (testy) tímto problémem netrpí, přeskakuje se.
        """
        if self.path == ":memory:":
            return
        current_mode = self._conn.execute("PRAGMA auto_vacuum").fetchone()[0]
        if current_mode == 2:
            return
        self._conn.execute("PRAGMA auto_vacuum = INCREMENTAL")
        self._conn.execute("VACUUM")

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
            INSERT INTO spots (
                callsign, freq_hz, mode, band, ts, source, snr_db, comment,
                spotter, country, locator, bearing_deg, distance_km
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                spot.country,
                spot.locator,
                spot.bearing_deg,
                spot.distance_km,
            ),
        )
        self._conn.commit()

    def insert_spots(self, spots: list[Spot]) -> None:
        """Vloží více spotů v jediné transakci (jeden commit) místo
        jednotlivého ``insert_spot()`` na spot -- při dávce několika stovek
        až tisíc spotů z jednoho pollu (typicky PSKReporter, viz
        aggregator.poll_once) to zásadně zkracuje čas do prvního zobrazení
        GUI, protože ten poll běží synchronně před startem web serveru
        (viz cli.py)."""
        if not spots:
            return
        self._conn.executemany(
            """
            INSERT INTO spots (
                callsign, freq_hz, mode, band, ts, source, snr_db, comment,
                spotter, country, locator, bearing_deg, distance_km
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
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
                    spot.country,
                    spot.locator,
                    spot.bearing_deg,
                    spot.distance_km,
                )
                for spot in spots
            ],
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
                country=row["country"],
                locator=row["locator"],
                bearing_deg=row["bearing_deg"],
                distance_km=row["distance_km"],
            )
            for row in rows
        ]

    def purge_older_than(self, max_age_seconds: float, now: float | None = None) -> int:
        now = time.time() if now is None else now
        cutoff = now - max_age_seconds
        cur = self._conn.execute("DELETE FROM spots WHERE ts < ?", (cutoff,))
        self._conn.commit()
        if cur.rowcount and self.path != ":memory:":
            # Uvolní stránky smazaných řádků zpět OS hned teď (viz
            # _enable_incremental_vacuum) -- bez tohoto by DELETE jen
            # naplnil interní freelist a soubor by na disku dál rostl i
            # přes pravidelné čištění. sqlite3 stepuje "PRAGMA
            # incremental_vacuum" po jedné uvolněné stránce na fetch --
            # bez fetchall() by se `.execute()` zastavilo po první stránce
            # a zbytek freelistu by zůstal neuvolněný.
            self._conn.execute("PRAGMA incremental_vacuum").fetchall()
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

    # -- GUI filter preferences -------------------------------------------

    def save_filter_preferences(self, bands: list[str], modes: list[str]) -> None:
        """Atomicky zapamatuje poslední volbu předvolby módů/pásem."""
        self._conn.execute(
            """
            INSERT INTO filter_preferences (id, bands_json, modes_json)
            VALUES (1, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                bands_json = excluded.bands_json,
                modes_json = excluded.modes_json
            """,
            (json.dumps(bands), json.dumps(modes)),
        )
        self._conn.commit()

    def load_filter_preferences(self) -> tuple[list[str], list[str]] | None:
        """Vrátí poslední GUI filtry, nebo ``None`` před první volbou."""
        row = self._conn.execute(
            "SELECT bands_json, modes_json FROM filter_preferences WHERE id = 1"
        ).fetchone()
        if row is None:
            return None
        try:
            bands = json.loads(row["bands_json"])
            modes = json.loads(row["modes_json"])
        except (TypeError, json.JSONDecodeError):
            return None
        if not isinstance(bands, list) or not all(isinstance(value, str) for value in bands):
            return None
        if not isinstance(modes, list) or not all(isinstance(value, str) for value in modes):
            return None
        return bands, modes

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

    # -- band-opening notifikace ------------------------------------------

    def log_band_opening(
        self, band: str, station_count: int, ts: float | None = None, reason: str = ""
    ) -> None:
        ts = time.time() if ts is None else ts
        self._conn.execute(
            "INSERT INTO band_openings (ts, band, station_count, reason) VALUES (?, ?, ?, ?)",
            (ts, band, station_count, reason),
        )
        self._conn.commit()

    def recent_band_openings(self, limit: int = 50) -> list[sqlite3.Row]:
        return self._conn.execute(
            "SELECT * FROM band_openings ORDER BY ts DESC LIMIT ?", (limit,)
        ).fetchall()

    # -- operátorem potvrzená historie QSO -------------------------------

    def log_qso(
        self,
        callsign: str,
        freq_hz: int,
        mode: str,
        band: str,
        bearing_deg: float | None = None,
        note: str = "",
        ts: float | None = None,
    ) -> None:
        """Uloží lokální historický záznam pouze po explicitní akci operátora.

        Metoda nijak nekomunikuje s Log4OM2 a nepotvrzuje záznam v externím
        deníku; webové API ji nabízí jen přes samostatné tlačítko v GUI.
        """
        ts = time.time() if ts is None else ts
        self._conn.execute(
            """
            INSERT INTO qso_history (ts, callsign, freq_hz, mode, band, bearing_deg, note)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (ts, callsign, freq_hz, mode, band, bearing_deg, note),
        )
        self._conn.commit()

    def recent_qsos(self, limit: int = 50) -> list[sqlite3.Row]:
        return self._conn.execute(
            "SELECT * FROM qso_history ORDER BY ts DESC LIMIT ?", (limit,)
        ).fetchall()

    # -- údržba: úplné vyčištění obsahu ------------------------------------

    #: Všechny tabulky s daty, které `clear_all_data()` maže. Soubor,
    #: schéma (`SCHEMA` výše) a config.yaml zůstávají nedotčené -- mažou
    #: se jen řádky.
    DATA_TABLES = (
        "spots",
        "worked_entities",
        "autotune_log",
        "band_openings",
        "qso_history",
        "filter_preferences",
    )

    def clear_all_data(self) -> dict[str, int]:
        """Smaže veškerý obsah databáze (spoty, AUTO TUNE log, band-opening
        historii, QSO historii, worked-DXCC cache i uložené GUI filtry) a
        vrátí počet smazaných řádků na tabulku.

        Soubor, schéma (struktura tabulek) i zdrojový kód zůstávají beze
        změny -- maže se jen obsah. Běží v jedné transakci; při jakémkoli
        selhání (výjimka, nebo neočekávaně neprázdná tabulka po commitu)
        vyhodí ``RuntimeError`` a transakci vrátí zpět, aby volající nikdy
        nepokračoval s neověřeným nebo částečně vyčištěným stavem.
        """
        try:
            removed = {
                table: self._conn.execute(f"DELETE FROM {table}").rowcount
                for table in self.DATA_TABLES
            }
            self._conn.commit()
        except Exception as exc:
            try:
                self._conn.rollback()
            except Exception:
                # Spojení může být mezitím zavřené/nedostupné (např. jiný
                # proces) -- selhání samotného rollbacku nesmí zamaskovat
                # původní chybu čištění hlášenou níže.
                pass
            raise RuntimeError(
                f"Vyčištění databáze '{self.path}' selhalo, žádná data nebyla "
                f"změněna: {exc}"
            ) from exc

        not_empty = {
            table: count
            for table in self.DATA_TABLES
            if (count := self._conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
        }
        if not_empty:
            raise RuntimeError(
                f"Vyčištění databáze '{self.path}' proběhlo, ale ověření po "
                f"zápisu zjistilo neprázdné tabulky (možný souběžný zápis "
                f"nebo poškozený stav): {not_empty}"
            )

        if self.path != ":memory:":
            # Stejný důvod jako u purge_older_than výše -- bez incremental
            # vacuum by DELETE jen naplnil freelist a soubor na disku by si
            # držel starou velikost i po úplném vyčištění obsahu.
            try:
                self._conn.execute("PRAGMA incremental_vacuum").fetchall()
                self._conn.commit()
            except Exception as exc:
                raise RuntimeError(
                    f"Data databáze '{self.path}' byla vyčištěna, ale "
                    f"uvolnění místa na disku (incremental_vacuum) selhalo: "
                    f"{exc}"
                ) from exc

        return removed
