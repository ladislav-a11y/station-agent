"""Cilene regrese pro callsign -> geodata -> API/GUI retezec.

Testy pouzivaji pouze lokalni fixture data.  Hlida se zde jeden souvisly
uzivatelsky scenar, aby jednotkove testy jednotlivych modulu nemohly projit,
zatimco se rozbije predani hodnot mezi agregatorem, serializaci a GUI.
"""

from __future__ import annotations

import time
import unittest
from pathlib import Path

from station_agent.adapters.qrz import QRZClient, parse_qrz_lookup_xml
from station_agent.aggregator import attach_dxcc_and_bearing, group_spots_into_candidates
from station_agent.dxcc import callsign_to_dxcc
from station_agent.models import Spot
from station_agent.web.serialization import candidate_to_dict


QTH = (50.0755, 14.4378)
LOOKUP_4L5O_XML = """<?xml version="1.0" encoding="utf-8"?>
<QRZDatabase xmlns="http://xmldata.qrz.com">
  <Callsign><call>4L5O</call><country>Georgia</country>
    <lat>41.715138</lat><lon>44.827096</lon><grid>LN41ox</grid>
    <cqzone>21</cqzone>
  </Callsign>
  <Session><Key>fixture-session</Key></Session>
</QRZDatabase>
"""


def _candidate(callsign: str, locator: str | None = None):
    spots = [
        Spot(
            callsign=callsign,
            freq_hz=14_074_000,
            mode="FT8",
            timestamp=time.time(),
            source="pskreporter",
            locator=locator,
        )
    ]
    return group_spots_into_candidates(spots)[0]


class CallsignGeodataPipelineRegressionTests(unittest.TestCase):
    def test_common_callsign_uses_offline_prefix_and_valid_locator(self):
        candidate = _candidate("JA1XYZ", "PM95VU")
        fallback_calls: list[str] = []

        attach_dxcc_and_bearing(
            [candidate],
            qth_latlon=QTH,
            dxcc_fallback=lambda call: fallback_calls.append(call),
        )

        self.assertEqual(fallback_calls, [])
        self.assertEqual(candidate.country, "Japan")
        self.assertEqual(candidate.locator, "PM95VU")
        self.assertIsNotNone(candidate.bearing_deg)
        self.assertIsNotNone(candidate.distance_km)
        self.assertGreater(candidate.distance_km, 1_000)

    def test_missing_prefix_and_coordinates_remain_explicitly_unknown(self):
        candidate = _candidate("QQ0XYZ")
        attach_dxcc_and_bearing(
            [candidate], qth_latlon=QTH, dxcc_fallback=lambda _call: None
        )

        payload = candidate_to_dict(candidate)
        self.assertIsNone(payload["country"])
        self.assertIsNone(payload["locator"])
        self.assertIsNone(payload["dxcc"])
        self.assertIsNone(payload["bearing_deg"])
        self.assertIsNone(payload["distance_km"])

    def test_missing_offline_prefix_uses_lookup_coordinates_for_path(self):
        entity = parse_qrz_lookup_xml(LOOKUP_4L5O_XML)
        self.assertIsNone(callsign_to_dxcc("4L5O"))
        self.assertIsNotNone(entity)
        candidate = _candidate("4L5O")

        attach_dxcc_and_bearing(
            [candidate], qth_latlon=QTH, dxcc_fallback=lambda call: entity
        )
        payload = candidate_to_dict(candidate)

        self.assertEqual(payload["callsign"], "4L5O")
        self.assertEqual(payload["country"], "Georgia")
        self.assertEqual(payload["dxcc"]["name"], "Georgia")
        self.assertIsNone(payload["locator"])
        self.assertIsNotNone(payload["bearing_deg"])
        self.assertIsNotNone(payload["distance_km"])

    def test_extended_prefix_prefers_longest_assigned_block(self):
        # EG8 je Kanarske ostrovy, zatimco obecne EG patri Spanelsku.
        canary = callsign_to_dxcc("EG8TEST")
        spain = callsign_to_dxcc("EG1TEST")
        self.assertIsNotNone(canary)
        self.assertIsNotNone(spain)
        self.assertEqual(canary.name, "Canary Islands")
        self.assertEqual(canary.prefix, "EA8")
        self.assertEqual(spain.name, "Spain")


class LookupCacheRegressionTests(unittest.TestCase):
    def test_case_normalized_callsign_cache_feeds_same_geodata(self):
        client = QRZClient(username="fixture", password="fixture")
        network_calls: list[str] = []

        def lookup(call: str):
            network_calls.append(call)
            return parse_qrz_lookup_xml(LOOKUP_4L5O_XML)

        client._lookup_uncached = lookup
        first = client.lookup("4L5O")
        second = client.lookup("4l5o")

        self.assertIs(first, second)
        self.assertEqual(network_calls, ["4L5O"])


class ApiAndDisplayRegressionTests(unittest.TestCase):
    def test_aggregated_candidate_payload_preserves_all_geodata(self):
        candidate = _candidate("JA1XYZ", "PM95VU")
        attach_dxcc_and_bearing([candidate], qth_latlon=QTH)
        payload = candidate_to_dict(candidate)

        self.assertEqual(payload["callsign"], "JA1XYZ")
        self.assertEqual(payload["country"], "Japan")
        self.assertEqual(payload["locator"], "PM95VU")
        self.assertEqual(payload["dxcc"]["name"], "Japan")
        self.assertIsInstance(payload["bearing_deg"], float)
        self.assertIsInstance(payload["distance_km"], float)

    def test_gui_renders_values_and_unknown_markers_from_api_fields(self):
        root = Path(__file__).resolve().parents[1]
        script = (root / "station_agent" / "web" / "static" / "app.js").read_text(
            encoding="utf-8"
        )
        page = (root / "station_agent" / "web" / "static" / "index.html").read_text(
            encoding="utf-8"
        )

        self.assertIn("<th>Lokátor</th>", page)
        self.assertIn('const country = c.country || (c.dxcc && c.dxcc.name) || "?";', script)
        self.assertIn('const locator = c.locator || "?";', script)
        self.assertIn("c.bearing_deg != null", script)
        self.assertIn('c.distance_km ?? "?"', script)
        self.assertIn("<td>${locator}</td>", script)
        self.assertIn("<td>${bearing}</td>", script)


if __name__ == "__main__":
    unittest.main()
