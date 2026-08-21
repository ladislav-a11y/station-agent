import unittest

from station_agent.dxcc import callsign_to_dxcc


class DXCCTests(unittest.TestCase):
    def test_known_prefixes(self):
        self.assertEqual(callsign_to_dxcc("OK1ABC").name, "Czech Republic")
        self.assertEqual(callsign_to_dxcc("om3xyz").name, "Slovak Republic")
        self.assertEqual(callsign_to_dxcc("W1AW").name, "United States")
        self.assertEqual(callsign_to_dxcc("JA1XYZ").name, "Japan")

    def test_longest_prefix_wins(self):
        # HB9 je specifický prefix pro Švýcarsko (delší než by odpovídalo "H").
        self.assertEqual(callsign_to_dxcc("HB9ABC").name, "Switzerland")

    def test_unknown_prefix_returns_none(self):
        self.assertIsNone(callsign_to_dxcc("ZZ9ZZZ"))
        self.assertIsNone(callsign_to_dxcc(""))

    def test_portable_suffix_stripped(self):
        self.assertEqual(callsign_to_dxcc("OK1ABC/P").name, "Czech Republic")
        self.assertEqual(callsign_to_dxcc("OK1ABC/MM").name, "Czech Republic")

    def test_compound_callsign_uses_part_with_digit(self):
        # W1AW/OK1 -- operátor W1AW vysílá "z OK1" prefixu -> bereme tu
        # část, která vypadá jako plný callsign (obsahuje číslici).
        result = callsign_to_dxcc("PY2ABC/W1")
        self.assertEqual(result.name, "Brazil")


if __name__ == "__main__":
    unittest.main()
