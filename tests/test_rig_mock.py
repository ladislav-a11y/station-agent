import unittest

from station_agent.rig.mock_rig import MockRig


class MockRigTests(unittest.TestCase):
    def test_defaults(self):
        rig = MockRig()
        self.assertEqual(rig.get_frequency(), 14_200_000)
        self.assertEqual(rig.get_mode(), "SSB")

    def test_set_frequency_and_mode(self):
        rig = MockRig()
        rig.set_frequency(7_030_000)
        rig.set_mode("CW")
        self.assertEqual(rig.get_frequency(), 7_030_000)
        self.assertEqual(rig.get_mode(), "CW")
        self.assertEqual(rig.set_frequency_calls, [7_030_000])
        self.assertEqual(rig.set_mode_calls, ["CW"])

    def test_get_status(self):
        rig = MockRig(freq_hz=21_074_000, mode="FT8")
        status = rig.get_status()
        self.assertEqual(status.freq_hz, 21_074_000)
        self.assertEqual(status.mode, "FT8")


if __name__ == "__main__":
    unittest.main()
