import time
import unittest

from station_agent.adapters.mock import MockAdapter, sample_spots
from station_agent.models import Spot


class MockAdapterTests(unittest.TestCase):
    def test_fetch_returns_spots_from_mock_source(self):
        adapter = MockAdapter()
        spots = adapter.fetch()
        self.assertGreater(len(spots), 0)
        self.assertTrue(all(s.source == "mock" for s in spots))
        self.assertTrue(all(isinstance(s, Spot) for s in spots))

    def test_sample_spots_are_relative_to_now(self):
        now = time.time()
        spots = sample_spots(now=now)
        for spot in spots:
            self.assertLessEqual(spot.timestamp, now)

    def test_injected_spots_are_returned_verbatim(self):
        fixed = [Spot(callsign="OK1ABC", freq_hz=14_195_000, mode="SSB", timestamp=time.time(), source="mock")]
        adapter = MockAdapter(spots=fixed)
        self.assertEqual(adapter.fetch(), fixed)

    def test_covers_multiple_bands_and_modes(self):
        spots = sample_spots()
        bands = {s.band for s in spots}
        modes = {s.mode for s in spots}
        self.assertGreaterEqual(len(bands), 3)
        self.assertGreaterEqual(len(modes), 3)


if __name__ == "__main__":
    unittest.main()
