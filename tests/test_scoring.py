import time
import unittest

from station_agent.dxcc import PREFIX_TABLE
from station_agent.models import Candidate
from station_agent.scoring import DEFAULT_WEIGHTS, ScoringConfig, score_candidate


def make_candidate(**overrides) -> Candidate:
    now = time.time()
    defaults = dict(
        callsign="OK1ABC",
        freq_hz=14_195_000,
        mode="SSB",
        band="20m",
        first_seen=now,
        last_seen=now,
        confirming_sources={"mock"},
        best_snr_db=None,
        dxcc=PREFIX_TABLE["OK"],
    )
    defaults.update(overrides)
    return Candidate(**defaults)


class ScoringTests(unittest.TestCase):
    def setUp(self):
        self.cfg = ScoringConfig(weights=dict(DEFAULT_WEIGHTS), spot_max_age_minutes=15)

    def test_weights_sum_to_100(self):
        self.assertEqual(sum(DEFAULT_WEIGHTS.values()), 100)

    def test_fresh_needed_high_snr_scores_high(self):
        candidate = make_candidate(best_snr_db=30, confirming_sources={"mock", "dx_cluster", "rbn"})
        result = score_candidate(candidate, self.cfg, is_needed_dxcc=lambda c: True)
        self.assertGreaterEqual(result.total, 90)
        self.assertEqual(len(result.reasons), 4)

    def test_stale_spot_loses_freshness_points(self):
        now = time.time()
        candidate = make_candidate(last_seen=now - 20 * 60)  # 20 min > 15 min limit
        result = score_candidate(candidate, self.cfg, is_needed_dxcc=lambda c: True, now=now)
        freshness = next(r for r in result.reasons if r.factor == "freshness")
        self.assertEqual(freshness.points, 0)

    def test_already_worked_scores_lower_than_needed(self):
        needed = score_candidate(make_candidate(), self.cfg, is_needed_dxcc=lambda c: True)
        worked = score_candidate(make_candidate(), self.cfg, is_needed_dxcc=lambda c: False)
        self.assertGreater(needed.total, worked.total)

    def test_missing_snr_gives_neutral_signal_score(self):
        candidate = make_candidate(best_snr_db=None)
        result = score_candidate(candidate, self.cfg, is_needed_dxcc=lambda c: True)
        signal = next(r for r in result.reasons if r.factor == "signal")
        self.assertAlmostEqual(signal.points, self.cfg.weights["signal"] * 0.5, places=1)

    def test_score_is_clamped_between_0_and_100(self):
        candidate = make_candidate(best_snr_db=1000)
        result = score_candidate(candidate, self.cfg, is_needed_dxcc=lambda c: True)
        self.assertLessEqual(result.total, 100)
        self.assertGreaterEqual(result.total, 0)

    def test_more_confirming_sources_increase_score(self):
        one_source = score_candidate(
            make_candidate(confirming_sources={"mock"}), self.cfg, is_needed_dxcc=lambda c: True
        )
        three_sources = score_candidate(
            make_candidate(confirming_sources={"mock", "dx_cluster", "rbn"}),
            self.cfg,
            is_needed_dxcc=lambda c: True,
        )
        self.assertGreater(three_sources.total, one_source.total)


if __name__ == "__main__":
    unittest.main()
