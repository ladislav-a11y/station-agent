import time
import unittest

from station_agent.db import Database
from station_agent.models import Spot


class DatabaseTests(unittest.TestCase):
    def setUp(self):
        self.db = Database(":memory:")

    def tearDown(self):
        self.db.close()

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


if __name__ == "__main__":
    unittest.main()
