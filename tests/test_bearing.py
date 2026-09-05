import unittest

from station_agent.bearing import (
    bearing_and_distance,
    haversine_distance_km,
    initial_bearing_deg,
    maidenhead_to_latlon,
    validate_latlon,
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
        with self.assertRaises(ValueError):
            maidenhead_to_latlon("JN79FGX")  # lichý počet znaků
        with self.assertRaises(ValueError):
            maidenhead_to_latlon("JN79FG1X")  # 7.-8. znak musí být číslice
        with self.assertRaises(ValueError):
            maidenhead_to_latlon("ZN79FG")  # pole Maidenhead jsou jen A-R
        with self.assertRaises(ValueError):
            maidenhead_to_latlon("JN79YZ")  # subsquare jsou jen A-X
        with self.assertRaises(ValueError):
            maidenhead_to_latlon(1234)

    def test_eight_char_extended_locator(self):
        # Reálně vrací PSKReporter (senderLocator) -- viz LIVE_EVIDENCE.md.
        # 8 znaků musí zpřesnit polohu oproti 6znakovému prefixu, ne ho
        # tiše ignorovat.
        lat6, lon6 = maidenhead_to_latlon("JN79FG")
        lat8, lon8 = maidenhead_to_latlon("JN79FG12")
        self.assertNotAlmostEqual(lat6, lat8, places=4)
        self.assertNotAlmostEqual(lon6, lon8, places=4)
        # Střed 8znakového pole musí ležet uvnitř 6znakového pole (šířka
        # 2/24 stupně lon, 1/24 stupně lat).
        self.assertAlmostEqual(lat8, lat6, delta=1.0 / 24.0)
        self.assertAlmostEqual(lon8, lon6, delta=2.0 / 24.0)

    def test_eight_char_locator_with_letter_extended_square(self):
        # Reálný kandidát 'KN10LNPN' z PSKReporteru: 7.-8. znak (extended
        # square) jsou písmena místo obvyklých číslic. Formálně jde o platné
        # zpřesnění (homogenní dvojice), dřív to ale tvrdě padalo na
        # "Neplatný formát" a bearing spadl zpět na referenční bod DXCC.
        lat6, lon6 = maidenhead_to_latlon("KN10LN")
        lat8, lon8 = maidenhead_to_latlon("KN10LNPN")
        self.assertTrue(-90.0 <= lat8 <= 90.0)
        self.assertTrue(-180.0 <= lon8 <= 180.0)
        self.assertAlmostEqual(lat8, lat6, delta=1.0 / 24.0)
        self.assertAlmostEqual(lon8, lon6, delta=2.0 / 24.0)

    def test_ten_char_extended_locator_from_real_pskreporter_data(self):
        # Skutečné hodnoty senderLocator z živého PSKReporter query API
        # (viz LIVE_EVIDENCE.md, iterace "live test v PowerShell") -- dřív
        # tyto (validní) locatory shodily bearing na "Neplatná délka".
        lat, lon = maidenhead_to_latlon("JO49UC21QH")
        self.assertTrue(-90.0 <= lat <= 90.0)
        self.assertTrue(-180.0 <= lon <= 180.0)
        lat6, lon6 = maidenhead_to_latlon("JO49UC")
        self.assertAlmostEqual(lat, lat6, delta=1.0 / 24.0)
        self.assertAlmostEqual(lon, lon6, delta=2.0 / 24.0)


class BearingDistanceTests(unittest.TestCase):
    def test_coordinate_validation_rejects_non_finite_and_out_of_range(self):
        for coordinates in ((float("nan"), 14), (50, float("inf")), (91, 14), (50, -181)):
            with self.subTest(coordinates=coordinates), self.assertRaises(ValueError):
                validate_latlon(*coordinates)

    def test_combined_calculation_rejects_invalid_endpoint(self):
        with self.assertRaisesRegex(ValueError, "stanice"):
            bearing_and_distance(50, 14, 91, 10)

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
