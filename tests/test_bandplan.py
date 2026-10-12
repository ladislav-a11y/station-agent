import unittest

from station_agent.bandplan import (
    MODE_FREQUENCY_RULES,
    SUPPORTED_BANDS,
    band_to_default_freq_hz,
    freq_to_band,
    validate_mode_frequency,
)


class BandPlanTests(unittest.TestCase):
    def test_known_bands(self):
        self.assertEqual(freq_to_band(14_195_000), "20m")
        self.assertEqual(freq_to_band(7_030_000), "40m")
        self.assertEqual(freq_to_band(28_450_000), "10m")
        self.assertEqual(freq_to_band(3_600_000), "80m")

    def test_out_of_band(self):
        self.assertEqual(freq_to_band(1_900_000), "160m")
        self.assertIsNone(freq_to_band(50_000_000))

    def test_all_supported_bands_have_limits(self):
        for band in SUPPORTED_BANDS:
            self.assertIsNotNone(band_to_default_freq_hz(band))

    def test_band_to_default_freq_roundtrips(self):
        for band in SUPPORTED_BANDS:
            freq = band_to_default_freq_hz(band)
            self.assertEqual(freq_to_band(freq), band)

    def test_mode_frequency_valid_invalid_and_boundary_combinations(self):
        cases = (
            (6_999_999, "SSB", False),
            (7_000_000, "CW", True),
            (7_000_000, "SSB", False),
            (7_039_999, "CW", True),
            (7_040_000, "FT8", True),
            (7_040_000, "SSB", False),
            (7_049_999, "RTTY", True),
            (7_050_000, "SSB", False),
            (7_052_699, "SSB", False),
            (7_052_700, "SSB", False),  # FT2 dial 7.052 MHz
            (7_074_000, "FT8", True),
            (7_086_000, "SSB", False),  # FT4 dial 7.090 MHz
            (7_086_000, "CW", True),
            (7_200_000, "SSB", True),
            (7_200_001, "SSB", False),
            (10_100_000, "SSB", False),
            (10_136_000, "FT8", True),
            (14_074_000, "FT8", True),
            (14_195_000, "SSB", True),
        )
        for freq_hz, mode, expected in cases:
            with self.subTest(freq_hz=freq_hz, mode=mode):
                self.assertEqual(validate_mode_frequency(freq_hz, mode).valid, expected)

    def test_ssb_excludes_digital_dials_plus_minus_five_khz_on_every_band(self):
        from station_agent.bandplan import DIGITAL_DIAL_FREQUENCIES_HZ

        self.assertIn("FT2", DIGITAL_DIAL_FREQUENCIES_HZ)
        for mode, bands in DIGITAL_DIAL_FREQUENCIES_HZ.items():
            for band, dials in bands.items():
                for dial in dials:
                    if mode == "FT2" and band == "30m":
                        continue  # Na 30 m hlasový provoz není povolen ani mimo okno.
                    for offset in (-5_000, 0, 5_000):
                        with self.subTest(mode=mode, band=band, dial=dial, offset=offset):
                            self.assertFalse(validate_mode_frequency(dial + offset, "SSB").valid)

        self.assertFalse(validate_mode_frequency(7_075_000, "SSB").valid)
        self.assertFalse(validate_mode_frequency(7_086_000, "SSB").valid)  # FT4 7.090 MHz
        self.assertTrue(validate_mode_frequency(7_096_000, "SSB").valid)
        self.assertTrue(validate_mode_frequency(7_074_000, "FT8").valid)

    def test_mode_frequency_rejects_invalid_frequency_types(self):
        for value in (True, 0, -1, 7_086_000.0):
            with self.subTest(value=value):
                self.assertFalse(validate_mode_frequency(value, "SSB").valid)

    def test_rule_catalog_is_ordered_non_overlapping_and_versioned(self):
        for rule in MODE_FREQUENCY_RULES:
            self.assertLess(rule.lower_hz, rule.upper_hz)
            self.assertTrue(rule.source_revision)
        for previous, current in zip(MODE_FREQUENCY_RULES, MODE_FREQUENCY_RULES[1:]):
            self.assertLessEqual(previous.upper_hz, current.lower_hz)


if __name__ == "__main__":
    unittest.main()
