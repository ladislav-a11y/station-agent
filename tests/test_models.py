import time
import unittest

from station_agent.models import Candidate, Spot


class SpotTests(unittest.TestCase):
    def test_normalizes_callsign_and_mode_and_band(self):
        spot = Spot(callsign=" ok1abc ", freq_hz=14_195_000, mode="usb", timestamp=time.time(), source="mock")
        self.assertEqual(spot.callsign, "OK1ABC")
        self.assertEqual(spot.mode, "SSB")
        self.assertEqual(spot.band, "20m")

    def test_unknown_band_is_marked_unknown(self):
        spot = Spot(callsign="OK1ABC", freq_hz=1_000, mode="CW", timestamp=time.time(), source="mock")
        self.assertEqual(spot.band, "unknown")

    def test_explicit_band_is_respected(self):
        spot = Spot(
            callsign="OK1ABC", freq_hz=14_195_000, mode="SSB", timestamp=time.time(), source="mock", band="custom"
        )
        self.assertEqual(spot.band, "custom")


class CandidateTests(unittest.TestCase):
    def test_age_seconds(self):
        now = time.time()
        candidate = Candidate(
            callsign="OK1ABC", freq_hz=14_195_000, mode="SSB", band="20m", first_seen=now - 30, last_seen=now - 10
        )
        self.assertGreaterEqual(candidate.age_seconds, 9.5)
        self.assertLess(candidate.age_seconds, 15)


if __name__ == "__main__":
    unittest.main()
