import time
import unittest

from station_agent.adapters.dx_cluster import DXClusterAdapter
from station_agent.adapters.mock import MockAdapter
from station_agent.aggregator import Aggregator, attach_dxcc_and_bearing, group_spots_into_candidates
from station_agent.db import Database
from station_agent.models import Spot
from station_agent.scoring import DEFAULT_WEIGHTS, ScoringConfig


class GroupingTests(unittest.TestCase):
    def test_same_station_from_multiple_sources_merges(self):
        now = time.time()
        spots = [
            Spot(callsign="OK1ABC", freq_hz=14_195_000, mode="SSB", timestamp=now, source="mock"),
            Spot(callsign="ok1abc", freq_hz=14_195_100, mode="SSB", timestamp=now + 5, source="dx_cluster"),
        ]
        candidates = group_spots_into_candidates(spots)
        self.assertEqual(len(candidates), 1)
        candidate = candidates[0]
        self.assertEqual(candidate.confirming_sources, {"mock", "dx_cluster"})
        self.assertEqual(candidate.freq_hz, 14_195_100)  # nejnovější spot vyhrává frekvenci

    def test_different_mode_creates_separate_candidates(self):
        now = time.time()
        spots = [
            Spot(callsign="OK1ABC", freq_hz=14_195_000, mode="SSB", timestamp=now, source="mock"),
            Spot(callsign="OK1ABC", freq_hz=14_074_000, mode="FT8", timestamp=now, source="mock"),
        ]
        candidates = group_spots_into_candidates(spots)
        self.assertEqual(len(candidates), 2)

    def test_best_snr_is_max_of_group(self):
        now = time.time()
        spots = [
            Spot(callsign="OK1ABC", freq_hz=14_195_000, mode="CW", timestamp=now, source="mock", snr_db=5),
            Spot(callsign="OK1ABC", freq_hz=14_195_000, mode="CW", timestamp=now, source="rbn", snr_db=18),
        ]
        candidates = group_spots_into_candidates(spots)
        self.assertEqual(candidates[0].best_snr_db, 18)


class DxccBearingTests(unittest.TestCase):
    def test_attaches_dxcc_and_bearing_when_qth_known(self):
        now = time.time()
        candidates = group_spots_into_candidates(
            [Spot(callsign="JA1XYZ", freq_hz=14_195_000, mode="SSB", timestamp=now, source="mock")]
        )
        attach_dxcc_and_bearing(candidates, qth_latlon=(50.0755, 14.4378))
        self.assertEqual(candidates[0].dxcc.name, "Japan")
        self.assertIsNotNone(candidates[0].bearing_deg)
        self.assertIsNotNone(candidates[0].distance_km)

    def test_no_bearing_without_qth(self):
        now = time.time()
        candidates = group_spots_into_candidates(
            [Spot(callsign="JA1XYZ", freq_hz=14_195_000, mode="SSB", timestamp=now, source="mock")]
        )
        attach_dxcc_and_bearing(candidates, qth_latlon=None)
        self.assertIsNone(candidates[0].bearing_deg)


class AggregatorIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.db = Database(":memory:")
        self.scoring_cfg = ScoringConfig(weights=dict(DEFAULT_WEIGHTS), spot_max_age_minutes=15)

    def tearDown(self):
        self.db.close()

    def test_pending_source_does_not_break_poll(self):
        sources = [MockAdapter(), DXClusterAdapter(host="x", port=1)]
        aggregator = Aggregator(sources, self.db, self.scoring_cfg, qth_latlon=(50.0, 14.0))
        spots = aggregator.poll_once()
        self.assertGreater(len(spots), 0)
        self.assertTrue(all(s.source == "mock" for s in spots))

    def test_build_candidates_filters_by_band_and_mode(self):
        aggregator = Aggregator([MockAdapter()], self.db, self.scoring_cfg, qth_latlon=(50.0, 14.0))
        aggregator.poll_once()
        candidates = aggregator.build_candidates(allowed_bands={"20m"}, allowed_modes={"SSB"})
        self.assertTrue(all(c.band == "20m" and c.mode == "SSB" for c in candidates))

    def test_build_candidates_sorted_by_score_descending(self):
        aggregator = Aggregator([MockAdapter()], self.db, self.scoring_cfg, qth_latlon=(50.0, 14.0))
        aggregator.poll_once()
        candidates = aggregator.build_candidates()
        scores = [c.score.total for c in candidates]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_worked_dxcc_reduces_needed_score(self):
        aggregator = Aggregator([MockAdapter()], self.db, self.scoring_cfg, qth_latlon=(50.0, 14.0))
        aggregator.poll_once()
        before = aggregator.build_candidates()
        target = next(c for c in before if c.dxcc is not None)
        self.db.mark_worked(target.dxcc.name)
        after = aggregator.build_candidates()
        target_after = next(c for c in after if c.callsign == target.callsign and c.mode == target.mode)
        self.assertLess(target_after.score.total, target.score.total)


if __name__ == "__main__":
    unittest.main()
