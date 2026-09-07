"""Read-only ověření existence QSO v databázi Log4OM2."""

from __future__ import annotations

import os
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from enum import Enum
from urllib.parse import quote

from station_agent.modes import normalize_mode


class QSOVerificationStatus(str, Enum):
    """Stav odlišující ověřený výsledek od chyb zdrojové databáze."""

    MATCH = "match"
    NO_MATCH = "no_match"
    UNAVAILABLE = "unavailable"
    UNREADABLE = "unreadable"
    UNKNOWN_DATABASE = "unknown_database"
    INVALID_INPUT = "invalid_input"


@dataclass(frozen=True)
class QSOVerificationResult:
    status: QSOVerificationStatus
    diagnostic: str

    @property
    def verified(self) -> bool:
        return self.status in {
            QSOVerificationStatus.MATCH,
            QSOVerificationStatus.NO_MATCH,
        }

    @property
    def exists(self) -> bool | None:
        if not self.verified:
            return None
        return self.status is QSOVerificationStatus.MATCH


def _readonly_uri(path: str) -> str:
    # SQLite přijímá Windows i UNC cesty s dopřednými lomítky. Parametr mode=ro
    # je podstatný: chybějící soubor se nesmí vytvořit a zdroj nelze změnit.
    sqlite_path = os.path.abspath(path).replace("\\", "/")
    # immutable=1 zabraňuje SQLite sahat na journal/WAL/SHM vedle databáze.
    # Checker je proto určen pro neměnný snapshot/zálohu, nikoli pro soubor,
    # do kterého současně zapisuje Log4OM2.
    return f"file:{quote(sqlite_path, safe='/:')}?mode=ro&immutable=1"


def _khz_to_hz(value: object) -> int | None:
    try:
        khz = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    if not khz.is_finite():
        return None
    return int((khz * 1000).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


class Log4OMQSOChecker:
    """Kontroluje tabulku ``Log`` bez zápisu a bez použití přijímací frekvence."""

    def __init__(self, database_path: str):
        self.database_path = database_path

    def check(self, callsign: str, mode: str, freq_hz: int) -> QSOVerificationResult:
        normalized_call = (callsign or "").strip().upper()
        normalized_mode = normalize_mode(mode)
        try:
            requested_hz = int(freq_hz)
        except (TypeError, ValueError, OverflowError):
            return QSOVerificationResult(
                QSOVerificationStatus.INVALID_INPUT,
                "Ověření nelze provést: frekvence není platné celé číslo v Hz.",
            )

        if not os.path.exists(self.database_path):
            return QSOVerificationResult(
                QSOVerificationStatus.UNAVAILABLE,
                "Databáze Log4OM2 není dostupná na nakonfigurované cestě.",
            )
        if not os.path.isfile(self.database_path) or not os.access(self.database_path, os.R_OK):
            return QSOVerificationResult(
                QSOVerificationStatus.UNREADABLE,
                "Nakonfigurovaná cesta není čitelný databázový soubor.",
            )

        try:
            with closing(sqlite3.connect(_readonly_uri(self.database_path), uri=True)) as connection:
                connection.execute("PRAGMA query_only=ON")
                columns = {
                    str(row[1]).lower()
                    for row in connection.execute('PRAGMA table_info("Log")')
                }
                if not {"callsign", "mode", "freq"}.issubset(columns):
                    return QSOVerificationResult(
                        QSOVerificationStatus.UNKNOWN_DATABASE,
                        "Databáze nemá očekávanou tabulku Log se sloupci callsign, mode a freq.",
                    )

                rows = connection.execute(
                    'SELECT mode, freq FROM "Log" WHERE UPPER(TRIM(callsign)) = ?',
                    (normalized_call,),
                )
                matched = any(
                    normalize_mode(str(row_mode or "")) == normalized_mode
                    and _khz_to_hz(row_freq) == requested_hz
                    for row_mode, row_freq in rows
                )
        except sqlite3.DatabaseError:
            return QSOVerificationResult(
                QSOVerificationStatus.UNREADABLE,
                "Databázi Log4OM2 nelze přečíst v read-only režimu.",
            )
        except OSError:
            return QSOVerificationResult(
                QSOVerificationStatus.UNAVAILABLE,
                "Databáze Log4OM2 je momentálně nedostupná.",
            )

        if matched:
            return QSOVerificationResult(
                QSOVerificationStatus.MATCH,
                "Ověřená přesná shoda callsignu, normalizovaného módu a hlavní frekvence.",
            )
        return QSOVerificationResult(
            QSOVerificationStatus.NO_MATCH,
            "Databáze byla ověřena, ale přesná shoda callsignu, módu a frekvence nebyla nalezena.",
        )
