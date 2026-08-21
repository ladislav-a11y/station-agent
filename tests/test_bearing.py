import unittest

from station_agent.bearing import (
    bearing_and_distance,
    haversine_distance_km,
    initial_bearing_deg,
    maidenhead_to_latlon,
)


class MaidenheadTests(unittest.TestCase):
    def test_known_locator(self):
        lat, lon = maidenhead_to_latlon("JN79FG")
        self.assertAlmostEqual(lat, 49.2708, places=3)
        self.assertAlmostEqual(lon, 14.4583, places=3)

    def test_four_char_locator_returns_cell_center(self):
        lat, lon = maidenhead_to_latlon("JN79")
        self.assertAlmostEqual(lat, 49.5, places=6)
        self.assertAlmostEqual(lon, 15.0, places=6)

    def test_invalid_locator_raises(self):
        with self.assertRaises(ValueError):
            maidenhead_to_latlon("XX")
        with self.assertRaises(ValueError):
            maidenhead_to_latlon("1234")


class BearingDistanceTests(unittest.TestCase):
    def test_bearing_due_east(self):
        bearing = initial_bearing_deg(0, 0, 0, 10)
        self.assertAlmostEqual(bearing, 90, delta=0.5)

    def test_bearing_due_north(self):
        bearing = initial_bearing_deg(0, 0, 10, 0)
        self.assertAlmostEqual(bearing, 0, delta=0.5)

    def test_distance_zero_for_same_point(self):
        self.assertAlmostEqual(haversine_distance_km(50.0, 14.0, 50.0, 14.0), 0.0, places=6)

    def test_bearing_and_distance_combined(self):
        bearing, distance = bearing_and_distance(50.0755, 14.4378, 35.6762, 139.6503)
        self.assertTrue(0 <= bearing < 360)
        self.assertGreater(distance, 8000)  # Praha -> Tokio je řádově 9000 km


if __name__ == "__main__":
    unittest.main()
