import tempfile
import time
import unittest
from pathlib import Path

from station_agent.db import Database
from station_agent.models import Spot


class DatabaseTests(unittest.TestCase):
    def setUp(self):
        self.db = Database(":memory:")

    def tearDown(self):
        self.db.close()

    def test_filter_preferences_round_trip_and_replace_previous_choice(self):
        self.assertIsNone(self.db.load_filter_preferences())
        self.db.save_filter_preferences(["20m", "15m"], ["SSB", "FT8"])
        self.assertEqual(
            self.db.load_filter_preferences(),
            (["20m", "15m"], ["SSB", "FT8"]),
        )
        self.db.save_filter_preferences(["40m"], ["CW"])
        self.assertEqual(self.db.load_filter_preferences(), (["40m"], ["CW"]))

    def test_insert_and_recent_spots(self):
        now = time.time()
        self.db.insert_spot(
            Spot(callsign="OK1ABC", freq_hz=14_195_000, mode="SSB", timestamp=now, source="mock")
        )
        self.db.insert_spot(
            Spot(callsign="W1AW", freq_hz=7_030_000, mode="CW", timestamp=now - 3600, source="mock")
        )
        recent = self.db.recent_spots(max_age_seconds=600, now=now)
        self.assertEqual(len(recent), 1)
        self.assertEqual(recent[0].callsign, "OK1ABC")

    def test_spot_location_evidence_round_trip(self):
        now = time.time()
        self.db.insert_spot(
            Spot(
                callsign="OK1ABC",
                freq_hz=14_195_000,
                mode="SSB",
                timestamp=now,
                source="fixture",
                country="Czech Republic",
                locator="JN79FG",
                bearing_deg=123.0,
                distance_km=456.0,
            )
        )

        restored = self.db.recent_spots(max_age_seconds=60, now=now)[0]
        self.assertEqual(restored.country, "Czech Republic")
        self.assertEqual(restored.locator, "JN79FG")
        self.assertEqual(restored.bearing_deg, 123.0)
        self.assertEqual(restored.distance_km, 456.0)

    def test_purge_older_than(self):
        now = time.time()
        self.db.insert_spot(
            Spot(callsign="OK1ABC", freq_hz=14_195_000, mode="SSB", timestamp=now - 7200, source="mock")
        )
        removed = self.db.purge_older_than(max_age_seconds=600, now=now)
        self.assertEqual(removed, 1)
        self.assertEqual(self.db.recent_spots(max_age_seconds=86400, now=now), [])

    def test_worked_entities(self):
        self.assertFalse(self.db.is_worked("Czech Republic"))
        self.db.mark_worked("Czech Republic")
        self.assertTrue(self.db.is_worked("Czech Republic"))
        self.assertIn("Czech Republic", self.db.worked_entities())
        # idempotentní
        self.db.mark_worked("Czech Republic")
        self.assertEqual(len(self.db.worked_entities()), 1)

    def test_autotune_log(self):
        self.db.log_autotune("OK1ABC", 14_195_000, "SSB", 82, "test reason")
        history = self.db.autotune_history()
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["callsign"], "OK1ABC")
        self.assertEqual(history[0]["score"], 82)

    def test_band_openings_log_and_recent(self):
        self.db.log_band_opening("20m", 6)
        self.db.log_band_opening("40m", 8)
        recent = self.db.recent_band_openings()
        self.assertEqual(len(recent), 2)
        self.assertEqual(recent[0]["band"], "40m")  # nejnovější první
        self.assertEqual(recent[0]["station_count"], 8)
        self.assertEqual(recent[1]["band"], "20m")

    def test_band_openings_respects_limit(self):
        for i in range(5):
            self.db.log_band_opening("20m", 5 + i)
        recent = self.db.recent_band_openings(limit=2)
        self.assertEqual(len(recent), 2)

    def test_qso_history_is_explicit_and_newest_first(self):
        self.assertEqual(self.db.recent_qsos(), [])
        self.db.log_qso("OK1ABC", 14_195_000, "SSB", "20m", 123.4, "první", ts=10)
        self.db.log_qso("W1AW", 7_030_000, "CW", "40m", None, ts=20)
        history = self.db.recent_qsos()
        self.assertEqual([row["callsign"] for row in history], ["W1AW", "OK1ABC"])
        self.assertEqual(history[1]["bearing_deg"], 123.4)


class DatabaseFileGrowthTests(unittest.TestCase):
    """Regrese pro nestandardní chování odhalené live testem 03.09.2026:
    soubor `.sqlite3` rostl na disku i přes pravidelné `purge_older_than`,
    protože SQLite bez `auto_vacuum` nevrací uvolněné stránky OS (viz
    Database._enable_incremental_vacuum)."""

    def test_new_file_database_enables_incremental_auto_vacuum(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "station.sqlite3"
            with Database(str(db_path)) as db:
                mode = db._conn.execute("PRAGMA auto_vacuum").fetchone()[0]
                self.assertEqual(mode, 2)  # INCREMENTAL

    def test_purge_reclaims_disk_space_instead_of_only_freelist(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "station.sqlite3"
            with Database(str(db_path)) as db:
                now = time.time()
                stale = [
                    Spot(
                        callsign=f"OK1AA{i:03d}",
                        freq_hz=14_195_000,
                        mode="SSB",
                        timestamp=now - 7200,
                        source="mock",
                        comment="x" * 500,
                    )
                    for i in range(500)
                ]
                db.insert_spots(stale)
                size_before_purge = db_path.stat().st_size
                removed = db.purge_older_than(max_age_seconds=600, now=now)
                self.assertEqual(removed, 500)
                freelist_count = db._conn.execute("PRAGMA freelist_count").fetchone()[0]
                size_after_purge = db_path.stat().st_size

            self.assertEqual(freelist_count, 0)
            self.assertLess(size_after_purge, size_before_purge)


class DatabaseConstructionFailureTests(unittest.TestCase):
    def test_invalid_sqlite_file_closes_connection_instead_of_leaking_lock(self):
        """Regrese: kdyz `path` miri na existujici soubor, ktery neni platna
        SQLite databaze, `sqlite3.connect()` uspeje (soubor jen otevre), ale
        nasledne `executescript(SCHEMA)` vyhodi sqlite3.DatabaseError. Puvodne
        se `self._conn` v tomto pripade nikdy nezavrelo -- konstruktor selhal
        a instance se nikdy nevratila volajicimu, takze zadny kod nemel
        referenci, kterou by zavrel. Na Windows to drzi OS zamek na souboru,
        ktery pak brani i uklidu docasneho adresare (viz DIAGNOSIS_P5.md)."""
        with tempfile.TemporaryDirectory() as temp_dir:
            bad_path = Path(temp_dir) / "not_a_database.sqlite3"
            bad_path.write_text("not a real sqlite file", encoding="utf-8")
            with self.assertRaises(Exception):
                Database(str(bad_path))
        # Kdyby `self._conn` zustalo otevrene, `TemporaryDirectory.__exit__`
        # (ktery na Windows maze soubory primo) by vyhodil PermissionError
        # misto tichého uklidu -- pokud jsme se dostali sem bez vyjimky,
        # zamek byl uvolnen.


if __name__ == "__main__":
    unittest.main()
