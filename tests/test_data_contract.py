"""Mechanicky vynucuje datový kontrakt popsaný v DATA_CONTRACT.md.

Na rozdíl od tests/test_adapters_parsing.py (které ověřuje detail parsování
jednotlivých formátů) tenhle soubor ověřuje kontrakt napříč vrstvami:
Spot.source musí odpovídat skutečnému jménu adaptéru, scoring reasons musí
odpovídat deklarovaným váhám, a JSON pro GUI musí obsahovat pole, která DoD
vyžaduje zobrazit.
"""

from __future__ import annotations

import time
import unittest
from datetime import datetime, timezone

from station_agent.adapters.dx_cluster import DXClusterAdapter, parse_spot_line
from station_agent.adapters.mock import MockAdapter
from station_agent.adapters.pskreporter import PSKReporterAdapter, parse_pskreporter_report
from station_agent.adapters.rbn import RBNAdapter, parse_rbn_line
from station_agent.config import DEFAULT_SCORING_WEIGHTS
from station_agent.dxcc import PREFIX_TABLE
from station_agent.models import Candidate
from station_agent.scoring import DEFAULT_WEIGHTS, ScoringConfig, score_candidate
from station_agent.web.serialization import candidate_to_dict

FIXED_NOW = datetime(2024, 1, 1, 12, 34, 30, tzinfo=timezone.utc).timestamp()

PSKR_FIXTURE = """<?xml version="1.0"?>
<receptionReports>
<receptionReport senderCallsign="OK1ABC" receiverCallsign="W1AW"
                  frequency="14074000" mode="FT8"
                  flowStartSeconds="1700000000" sNR="-10" />
</receptionReports>
"""


class SpotSourceMatchesAdapterNameTests(unittest.TestCase):
    """DATA_CONTRACT.md sekce 1: Spot.source MUSÍ odpovídat self.name
    adaptéru, který spot vytvořil -- to je jediný identifikátor evidence
    použitý v Candidate.confirming_sources, nesmí se rozjet od skutečného
    adaptéru."""

    def test_mock_adapter(self):
        spots = MockAdapter().fetch()
        self.assertTrue(spots)
        self.assertTrue(all(s.source == MockAdapter.name for s in spots))

    def test_dx_cluster_parser(self):
        line = "DX de OK1KT:     14195.0  JA1XYZ       SSB nice signal          1234Z"
        spot = parse_spot_line(line, now=FIXED_NOW)
        self.assertIsNotNone(spot)
        self.assertEqual(spot.source, DXClusterAdapter.name)

    def test_named_dx_cluster_adapter_preserves_provider_identity(self):
        adapter = DXClusterAdapter(
            host="cluster.example",
            port=23,
            source_name="dx_cluster_example",
        )
        line = "DX de OK1KT:     14195.0  JA1XYZ       SSB nice signal          1234Z"
        spot = adapter.parse_line(line)
        self.assertIsNotNone(spot)
        self.assertEqual(spot.source, adapter.name)

    def test_rbn_parser(self):
        line = "DX de RBN-1-#:    7024.3  DL1ABC       CW    12 dB  25 WPM  CQ      1200Z"
        spot = parse_rbn_line(line, now=FIXED_NOW)
        self.assertIsNotNone(spot)
        self.assertEqual(spot.source, RBNAdapter.name)

    def test_pskreporter_parser(self):
        spots = parse_pskreporter_report(PSKR_FIXTURE)
        self.assertTrue(spots)
        self.assertTrue(all(s.source == PSKReporterAdapter.name for s in spots))


class ScoringContractTests(unittest.TestCase):
    """DATA_CONTRACT.md sekce 3: score_candidate() musí vrátit přesně jeden
    ScoreReason na každý deklarovaný faktor a nic navíc, váhy musí dát 100,
    a scoring.DEFAULT_WEIGHTS musí být re-export téhož slovníku jako
    config.DEFAULT_SCORING_WEIGHTS (jediný zdroj pravdy)."""

    def test_scoring_default_weights_is_reexport_of_config(self):
        self.assertIs(DEFAULT_WEIGHTS, DEFAULT_SCORING_WEIGHTS)

    def test_default_weights_sum_to_100(self):
        self.assertEqual(sum(DEFAULT_SCORING_WEIGHTS.values()), 100)

    def test_reason_factors_exactly_match_declared_weights(self):
        now = time.time()
        candidate = Candidate(
            callsign="OK1ABC",
            freq_hz=14_195_000,
            mode="SSB",
            band="20m",
            first_seen=now,
            last_seen=now,
            confirming_sources={"mock"},
            dxcc=PREFIX_TABLE["OK"],
        )
        cfg = ScoringConfig(weights=dict(DEFAULT_SCORING_WEIGHTS), spot_max_age_minutes=15)
        result = score_candidate(candidate, cfg, is_needed_dxcc=lambda c: True)
        factors = {r.factor for r in result.reasons}
        self.assertEqual(factors, set(DEFAULT_SCORING_WEIGHTS.keys()))


class CandidateSerializationContractTests(unittest.TestCase):
    """DATA_CONTRACT.md sekce 5: pole, která DoD vyžaduje zobrazit v GUI,
    musí být v JSON pro každého kandidáta přítomná (i když None)."""

    REQUIRED_FIELDS = {
        "callsign",
        "freq_hz",
        "mode",
        "country",
        "locator",
        "dxcc",
        "age_seconds",
        "confirming_sources",
        "spotters",
        "best_snr_db",
        "bearing_deg",
        "distance_km",
        "score",
    }

    def test_candidate_to_dict_has_all_required_fields(self):
        now = time.time()
        candidate = Candidate(
            callsign="OK1ABC",
            freq_hz=14_195_000,
            mode="SSB",
            band="20m",
            first_seen=now,
            last_seen=now,
            confirming_sources={"mock"},
            dxcc=PREFIX_TABLE["OK"],
        )
        cfg = ScoringConfig(weights=dict(DEFAULT_SCORING_WEIGHTS), spot_max_age_minutes=15)
        candidate.score = score_candidate(candidate, cfg, is_needed_dxcc=lambda c: True)
        payload = candidate_to_dict(candidate)
        missing = self.REQUIRED_FIELDS - payload.keys()
        self.assertEqual(missing, set())
        self.assertEqual(set(payload["score"]["reasons"][0].keys()), {"factor", "points", "max_points", "detail"})


if __name__ == "__main__":
    unittest.main()
