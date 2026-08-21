import unittest

from station_agent.bandplan import SUPPORTED_BANDS, band_to_default_freq_hz, freq_to_band


class BandPlanTests(unittest.TestCase):
    def test_known_bands(self):
        self.assertEqual(freq_to_band(14_195_000), "20m")
        self.assertEqual(freq_to_band(7_030_000), "40m")
        self.assertEqual(freq_to_band(28_450_000), "10m")
        self.assertEqual(freq_to_band(3_600_000), "80m")

    def test_out_of_band(self):
        self.assertIsNone(freq_to_band(1_900_000))
        self.assertIsNone(freq_to_band(50_000_000))

    def test_all_supported_bands_have_limits(self):
        for band in SUPPORTED_BANDS:
            self.assertIsNotNone(band_to_default_freq_hz(band))

    def test_band_to_default_freq_roundtrips(self):
        for band in SUPPORTED_BANDS:
            freq = band_to_default_freq_hz(band)
            self.assertEqual(freq_to_band(freq), band)


if __name__ == "__main__":
    unittest.main()
