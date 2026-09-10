import time
import unittest
from pathlib import Path

from station_agent.adapters._common import normalize_reliability_percent
from station_agent.adapters.dx_cluster import parse_spot_line
from station_agent.adapters.pskreporter import parse_pskreporter_report
from station_agent.adapters.rbn import parse_rbn_line
from station_agent.aggregator import Aggregator, group_spots_into_candidates
from station_agent.db import Database
from station_agent.models import Spot
from station_agent.scoring import ScoringConfig
from station_agent.web.serialization import candidate_to_dict


class ProviderReliabilityNormalizationTests(unittest.TestCase):
    def test_supported_fraction_and_percent_formats(self):
        self.assertEqual(normalize_reliability_percent("0.95", unit="fraction"), 95.0)
        self.assertEqual(normalize_reliability_percent("95", unit="percent"), 95.0)

    def test_missing_and_invalid_values_remain_unknown(self):
        for value in (None, "", "unknown", float("nan"), float("inf"), -1, 101):
            with self.subTest(value=value):
                self.assertIsNone(normalize_reliability_percent(value, unit="percent"))


class ProviderReliabilityCandidateTests(unittest.TestCase):
    def setUp(self):
        self.now = time.time()
        self.db = Database(":memory:")
        self.aggregator = Aggregator([], self.db, ScoringConfig())

    def tearDown(self):
        self.db.close()

    def _spot(self, callsign: str, reliability: float | None) -> Spot:
        return Spot(
            callsign=callsign,
            freq_hz=14_195_000,
            mode="SSB",
            timestamp=self.now,
            source="provider_fixture",
            reliability_percent=reliability,
        )

    def test_values_below_at_and_above_threshold(self):
        spots = [
            self._spot("AA1AA", 94.999),
            self._spot("BB1BB", 95.0),
            self._spot("CC1CC", 99.0),
        ]
        candidates = self.aggregator.build_candidates(spots, now=self.now)
        self.assertEqual({candidate.callsign for candidate in candidates}, {"BB1BB", "CC1CC"})

    def test_missing_value_preserves_previous_candidate_behavior(self):
        candidates = self.aggregator.build_candidates([self._spot("AA1AA", None)], now=self.now)
        self.assertEqual([candidate.callsign for candidate in candidates], ["AA1AA"])
        self.assertIsNone(candidates[0].reliability_percent)

    def test_merged_candidate_uses_lowest_reported_reliability(self):
        spots = [self._spot("AA1AA", 99.0), self._spot("AA1AA", 94.0)]
        candidates = group_spots_into_candidates(spots)
        self.assertEqual(candidates[0].reliability_percent, 94.0)
        self.assertEqual(self.aggregator.build_candidates(spots, now=self.now), [])

    def test_current_provider_formats_leave_reliability_unknown(self):
        cluster = parse_spot_line(
            "DX de OK1KT: 14195.0 JA1XYZ SSB nice signal 1234Z", now=self.now
        )
        rbn = parse_rbn_line(
            "DX de RBN-1-#: 7024.3 DL1ABC CW 12 dB 25 WPM CQ 1200Z", now=self.now
        )
        psk = parse_pskreporter_report(
            '<receptionReports><receptionReport senderCallsign="OK1ABC" '
            'receiverCallsign="W1AW" frequency="14074000" mode="FT8" '
            'flowStartSeconds="1700000000" sNR="-10" /></receptionReports>'
        )[0]
        self.assertTrue(all(spot.reliability_percent is None for spot in (cluster, rbn, psk)))

    def test_reliability_survives_database_round_trip(self):
        self.db.insert_spot(self._spot("AA1AA", 97.5))
        restored = self.db.recent_spots(60, now=self.now)[0]
        self.assertEqual(restored.reliability_percent, 97.5)


class GuiCandidateDetailReliabilityTests(unittest.TestCase):
    """GUI detail kandidáta (rozbalený řádek po kliknutí) musí zobrazit
    reliabilitu z dx clusterů v procentech, nebo výslovně uvést, že ji
    provider neposkytl -- nikdy hodnotu nedopočítávat na frontendu
    (viz DX_PROVIDER_RELIABILITY_RESEARCH.md)."""

    def test_candidate_payload_exposes_reliability_percent_field(self):
        candidate = Spot(
            callsign="OK1ABC",
            freq_hz=14_195_000,
            mode="SSB",
            timestamp=time.time(),
            source="dx_cluster",
        )
        candidates = group_spots_into_candidates([candidate])
        payload = candidate_to_dict(candidates[0])
        self.assertIn("reliability_percent", payload)
        self.assertIsNone(payload["reliability_percent"])

    def test_gui_renders_reliability_in_candidate_detail_without_frontend_derivation(self):
        root = Path(__file__).resolve().parents[1]
        script = (root / "station_agent" / "web" / "static" / "app.js").read_text(
            encoding="utf-8"
        )

        self.assertIn("c.reliability_percent", script)
        self.assertIn("candidate-detail-reliability", script)
        # Chybějící hodnota se musí zobrazit jako výslovně neznámá, ne jako
        # 0/50/95 -- viz DX_PROVIDER_RELIABILITY_RESEARCH.md.
        self.assertIn("neznámá (provider ji neposkytl)", script)


if __name__ == "__main__":
    unittest.main()
