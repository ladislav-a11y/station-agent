import time
import unittest

from station_agent.dxcc import PREFIX_TABLE
from station_agent.models import Candidate
from station_agent.scoring import DEFAULT_WEIGHTS, ScoringConfig, score_candidate
from station_agent.propagation import PropagationContext


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


REASON_FACTORS = {
    "freshness",
    "sources",
    "needed_dxcc",
    "signal",
    "reliability",
    "propagation",
    "path_dx",
}


class ScoringTests(unittest.TestCase):
    def setUp(self):
        self.cfg = ScoringConfig(weights=dict(DEFAULT_WEIGHTS), spot_max_age_minutes=15)

    def test_weights_sum_to_100(self):
        self.assertEqual(sum(DEFAULT_WEIGHTS.values()), 100)

    def test_fresh_needed_high_snr_scores_high(self):
        candidate = make_candidate(
            best_snr_db=30,
            confirming_sources={"mock", "dx_cluster", "rbn"},
            spotters={"OK1KT", "DL2ABC"},
            distance_km=18_000.0,
            bearing_deg=90.0,
        )
        result = score_candidate(
            candidate,
            self.cfg,
            is_needed_dxcc=lambda c: True,
            band_activity={"20m": 6},
        )
        self.assertGreaterEqual(result.total, 90)
        self.assertEqual(len(result.reasons), 7)
        self.assertEqual({r.factor for r in result.reasons}, REASON_FACTORS)

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

    def test_more_independent_spotters_increase_reliability_points(self):
        one_spotter = score_candidate(
            make_candidate(spotters={"OK1KT"}), self.cfg, is_needed_dxcc=lambda c: True
        )
        two_spotters = score_candidate(
            make_candidate(spotters={"OK1KT", "DL2ABC"}), self.cfg, is_needed_dxcc=lambda c: True
        )
        r1 = next(r for r in one_spotter.reasons if r.factor == "reliability")
        r2 = next(r for r in two_spotters.reasons if r.factor == "reliability")
        self.assertGreater(r2.points, r1.points)

    def test_unknown_spotter_gives_neutral_reliability_not_penalty(self):
        result = score_candidate(make_candidate(spotters=set()), self.cfg, is_needed_dxcc=lambda c: True)
        reliability = next(r for r in result.reasons if r.factor == "reliability")
        self.assertAlmostEqual(reliability.points, self.cfg.weights["reliability"] * 0.5, places=1)

    def test_one_confirmed_spotter_outscores_unknown_spotter(self):
        """Regrese: jeden potvrzený spotter musí dát VÍC bodů než neznámý
        spotter (neutrální 0.5 podíl váhy) -- skutečná evidence nesmí
        skórovat stejně jako placeholder pro chybějící kontext."""
        unknown = score_candidate(make_candidate(spotters=set()), self.cfg, is_needed_dxcc=lambda c: True)
        one = score_candidate(make_candidate(spotters={"OK1KT"}), self.cfg, is_needed_dxcc=lambda c: True)
        r_unknown = next(r for r in unknown.reasons if r.factor == "reliability")
        r_one = next(r for r in one.reasons if r.factor == "reliability")
        self.assertGreater(r_one.points, r_unknown.points)

    def test_busier_band_increases_propagation_points(self):
        quiet = score_candidate(
            make_candidate(band="20m"), self.cfg, is_needed_dxcc=lambda c: True, band_activity={"20m": 1}
        )
        busy = score_candidate(
            make_candidate(band="20m"), self.cfg, is_needed_dxcc=lambda c: True, band_activity={"20m": 6}
        )
        p_quiet = next(r for r in quiet.reasons if r.factor == "propagation")
        p_busy = next(r for r in busy.reasons if r.factor == "propagation")
        self.assertGreater(p_busy.points, p_quiet.points)

    def test_missing_band_activity_gives_neutral_propagation_not_penalty(self):
        result = score_candidate(make_candidate(), self.cfg, is_needed_dxcc=lambda c: True, band_activity=None)
        propagation = next(r for r in result.reasons if r.factor == "propagation")
        self.assertAlmostEqual(propagation.points, self.cfg.weights["propagation"] * 0.5, places=1)

    def test_hourly_snapshot_is_the_propagation_input(self):
        context = PropagationContext(
            kp=2.0, solar_flux=150.0, observed_at=1_700_000_000.0,
            source="fixture", qth_locator="JN79FG",
            band_quality={"20m": 0.8}, explanation="všechny vstupy",
        )
        result = score_candidate(
            make_candidate(band="20m"), self.cfg, is_needed_dxcc=lambda c: True,
            band_activity={"20m": 1}, propagation=context,
        )
        reason = next(r for r in result.reasons if r.factor == "propagation")
        self.assertEqual(reason.points, self.cfg.weights["propagation"] * 0.8)
        self.assertIn("hodinový model 20m=0.800", reason.detail)

    def test_farther_distance_increases_path_dx_points(self):
        near = score_candidate(make_candidate(distance_km=500.0), self.cfg, is_needed_dxcc=lambda c: True)
        far = score_candidate(make_candidate(distance_km=15_000.0), self.cfg, is_needed_dxcc=lambda c: True)
        p_near = next(r for r in near.reasons if r.factor == "path_dx")
        p_far = next(r for r in far.reasons if r.factor == "path_dx")
        self.assertGreater(p_far.points, p_near.points)

    def test_missing_distance_gives_neutral_path_dx_not_penalty(self):
        result = score_candidate(make_candidate(distance_km=None), self.cfg, is_needed_dxcc=lambda c: True)
        path_dx = next(r for r in result.reasons if r.factor == "path_dx")
        self.assertAlmostEqual(path_dx.points, self.cfg.weights["path_dx"] * 0.5, places=1)


if __name__ == "__main__":
    unittest.main()
