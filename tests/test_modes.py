import unittest

from station_agent.modes import SUPPORTED_MODES, normalize_mode


class ModesTests(unittest.TestCase):
    def test_aliases(self):
        self.assertEqual(normalize_mode("usb"), "SSB")
        self.assertEqual(normalize_mode("LSB"), "SSB")
        self.assertEqual(normalize_mode("ft8"), "FT8")
        self.assertEqual(normalize_mode("bpsk31"), "PSK31")

    def test_unknown_falls_back_to_other_digital(self):
        self.assertEqual(normalize_mode("JT65"), "OTHER_DIGITAL")
        self.assertEqual(normalize_mode(""), "OTHER_DIGITAL")
        self.assertEqual(normalize_mode("MSK144"), "OTHER_DIGITAL")

    def test_all_supported_modes_normalize_to_selves(self):
        for mode in SUPPORTED_MODES:
            self.assertEqual(normalize_mode(mode), mode)


if __name__ == "__main__":
    unittest.main()
