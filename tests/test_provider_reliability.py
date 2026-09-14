"""Reliabilita spotu podle principu Log4OM2 (viz
DX_PROVIDER_RELIABILITY_RESEARCH.md): hodnocení se odvozuje z vlastností a
potvrzení spotu (počet nezávislých spotterů v rámci časového okna
slučování), nikoli z identity DX cluster providera. Dřívější
provider-odvozené `reliability_percent` pole (Spot/Candidate, DB sloupec,
`RELIABILITY_THRESHOLD_PERCENT` filtr v aggregatoru,
`normalize_reliability_percent`) bylo odstraněno -- žádný zapojený provider
jej nikdy reálně neplnil."""

import time
import unittest
from pathlib import Path

from station_agent.adapters.dx_cluster import parse_spot_line
from station_agent.adapters.pskreporter import parse_pskreporter_report
from station_agent.adapters.rbn import parse_rbn_line
from station_agent.aggregator import Aggregator, group_spots_into_candidates
from station_agent.db import Database
from station_agent.models import Spot
from station_agent.scoring import RELIABLE_SPOTTER_COUNT, ScoringConfig, is_reliable_spot
from station_agent.web.serialization import candidate_to_dict


class OldProviderReliabilityFieldRemovedTests(unittest.TestCase):
    """Regrese: staré DX-provider odvozené pole se nesmí vrátit -- viz
    DX_PROVIDER_RELIABILITY_RESEARCH.md "Závěr"."""

    def test_spot_has_no_reliability_percent_field(self):
        spot = Spot(
            callsign="OK1ABC", freq_hz=14_195_000, mode="SSB",
            timestamp=time.time(), source="mock",
        )
        self.assertFalse(hasattr(spot, "reliability_percent"))

    def test_candidate_has_no_reliability_percent_field(self):
        candidates = group_spots_into_candidates(
            [Spot(callsign="OK1ABC", freq_hz=14_195_000, mode="SSB",
                  timestamp=time.time(), source="mock")]
        )
        self.assertFalse(hasattr(candidates[0], "reliability_percent"))

    def test_common_adapters_module_no_longer_exposes_percent_normalizer(self):
        from station_agent.adapters import _common
        self.assertFalse(hasattr(_common, "normalize_reliability_percent"))


class Log4OMSpotReliabilityTests(unittest.TestCase):
    """`is_reliable_spot()` -- Log4OM2-styl kontroly reliability: reliabilní
    je spot potvrzený alespoň `RELIABLE_SPOTTER_COUNT` na sobě nezávislými
    spottery (napříč zdroji), bez ohledu na to, který provider spot poslal."""

    def setUp(self):
        self.now = time.time()

    def _spot(self, spotter: str, source: str = "dx_cluster") -> Spot:
        return Spot(
            callsign="AA1AA", freq_hz=14_195_000, mode="SSB",
            timestamp=self.now, source=source, spotter=spotter,
        )

    def test_no_spotters_is_not_reliable(self):
        candidates = group_spots_into_candidates(
            [Spot(callsign="AA1AA", freq_hz=14_195_000, mode="SSB",
                  timestamp=self.now, source="mock", spotter="")]
        )
        self.assertFalse(is_reliable_spot(candidates[0]))

    def test_single_spotter_is_not_yet_reliable(self):
        candidates = group_spots_into_candidates([self._spot("OK1KT")])
        self.assertEqual(len(candidates[0].spotters), 1)
        self.assertFalse(is_reliable_spot(candidates[0]))

    def test_threshold_independent_spotters_makes_spot_reliable(self):
        spots = [self._spot("OK1KT"), self._spot("DL2ABC")]
        candidates = group_spots_into_candidates(spots)
        self.assertEqual(len(candidates[0].spotters), RELIABLE_SPOTTER_COUNT)
        self.assertTrue(is_reliable_spot(candidates[0]))

    def test_reliability_is_independent_of_which_provider_reported(self):
        """Stejný počet nezávislých spotterů dá stejný výsledek bez ohledu
        na to, ze kterých zdrojů/providerů spoty přišly."""
        via_one_provider = group_spots_into_candidates(
            [self._spot("OK1KT", source="dx_cluster"), self._spot("DL2ABC", source="dx_cluster")]
        )
        via_two_providers = group_spots_into_candidates(
            [self._spot("OK1KT", source="dx_cluster"), self._spot("DL2ABC", source="rbn")]
        )
        self.assertEqual(
            is_reliable_spot(via_one_provider[0]), is_reliable_spot(via_two_providers[0])
        )

    def test_duplicate_reports_from_same_spotter_do_not_count_twice(self):
        candidates = group_spots_into_candidates([self._spot("OK1KT"), self._spot("OK1KT")])
        self.assertEqual(len(candidates[0].spotters), 1)
        self.assertFalse(is_reliable_spot(candidates[0]))

    def test_current_provider_formats_carry_spotter_for_reliability_check(self):
        """Regrese: reliabilita se dnes počítá ze spottera, který parsery
        současných providerů reálně vyplňují (na rozdíl od dřívějšího
        neexistujícího procentního pole)."""
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
        self.assertTrue(cluster.spotter)
        self.assertTrue(rbn.spotter)
        self.assertTrue(psk.spotter)


class ReliabilityFilterNoLongerDropsCandidatesTests(unittest.TestCase):
    """Regrese: `Aggregator.build_candidates()` už žádného kandidáta kvůli
    reliabilitě nezahazuje (starý `RELIABILITY_THRESHOLD_PERCENT` filtr byl
    odstraněný spolu s neplatným polem) -- nízká reliabilita se projeví jen
    nižším skóre/štítkem, ne zmizením ze seznamu."""

    def setUp(self):
        self.now = time.time()
        self.db = Database(":memory:")
        self.aggregator = Aggregator([], self.db, ScoringConfig())

    def tearDown(self):
        self.db.close()

    def test_single_unconfirmed_spot_still_appears_as_a_candidate(self):
        spot = Spot(
            callsign="AA1AA", freq_hz=14_195_000, mode="SSB",
            timestamp=self.now, source="dx_cluster", spotter="",
        )
        candidates = self.aggregator.build_candidates([spot], now=self.now)
        self.assertEqual([c.callsign for c in candidates], ["AA1AA"])


class GuiCandidateDetailReliabilityTests(unittest.TestCase):
    """GUI detail kandidáta (rozbalený řádek po kliknutí) musí zobrazit
    Log4OM2 reliabilitu spotu odvozenou lokálně -- nikdy hodnotu
    nedopočítávat na frontendu (viz DX_PROVIDER_RELIABILITY_RESEARCH.md)."""

    def test_candidate_payload_exposes_boolean_reliable_field(self):
        spots = [
            Spot(callsign="OK1ABC", freq_hz=14_195_000, mode="SSB",
                 timestamp=time.time(), source="dx_cluster", spotter="OK1KT"),
            Spot(callsign="OK1ABC", freq_hz=14_195_000, mode="SSB",
                 timestamp=time.time(), source="rbn", spotter="DL2ABC"),
        ]
        candidates = group_spots_into_candidates(spots)
        payload = candidate_to_dict(candidates[0])
        self.assertIn("reliable", payload)
        self.assertIs(payload["reliable"], True)
        self.assertNotIn("reliability_percent", payload)

    def test_gui_renders_log4om2_reliability_without_frontend_derivation(self):
        root = Path(__file__).resolve().parents[1]
        script = (root / "station_agent" / "web" / "static" / "app.js").read_text(
            encoding="utf-8"
        )
        self.assertIn("c.reliable", script)
        self.assertIn("candidate-detail-reliability", script)
        self.assertIn("Log4OM2 reliabilita", script)
        self.assertNotIn("c.reliability_percent", script)


if __name__ == "__main__":
    unittest.main()
