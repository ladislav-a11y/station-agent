"""Integrační testy pro AppState -- ověřuje drátování mezi
refresh_candidates(), aggregator.band_activity() a BandOpeningTracker
(viz app_state._check_band_openings), včetně perzistence do DB pro
GET /api/notifications."""

from __future__ import annotations

import unittest

from station_agent.adapters.mock import MockAdapter
from station_agent.aggregator import Aggregator
from station_agent.app_state import AppState
from station_agent.config import AppConfig, NotificationsConfig
from station_agent.db import Database
from station_agent.propagation import PropagationContext
from station_agent.rig.mock_rig import MockRig


def build_app_state(notifications_cfg: NotificationsConfig | None = None) -> AppState:
    config = AppConfig()
    if notifications_cfg is not None:
        config.notifications = notifications_cfg
    db = Database(":memory:")
    rig = MockRig()
    aggregator = Aggregator([MockAdapter()], db, config.scoring, qth_latlon=(50.0755, 14.4378))
    return AppState(config, db, rig, aggregator)


class BandOpeningIntegrationTests(unittest.TestCase):
    def test_hourly_propagation_is_used_by_scoring_and_logged_in_full(self):
        """Regrese pro audit: snapshot nesmí jen existovat vedle scoringu.

        AppState jej musí předat Aggregatoru ještě před build_candidates() a
        terminálový DEBUG rozpis musí obsahovat vstupy modelu i všech sedm
        bodových faktorů každého kandidáta.
        """
        app_state = build_app_state()
        context = PropagationContext(
            kp=3.0,
            solar_flux=145.0,
            observed_at=1_700_000_000.0,
            source="NOAA fixture",
            qth_locator="JN79FG",
            band_quality={"20m": 0.8, "40m": 0.2},
            explanation="QTH JN79FG; Kp=3.0; SFI=145.0; geomagneticky=0.67",
        )

        class FixturePropagationService:
            def refresh_if_due(self, now=None):
                return context

            @property
            def context(self):
                return context

        app_state.propagation = FixturePropagationService()
        with self.assertLogs("station_agent.app_state", level="DEBUG") as captured:
            candidates = app_state.refresh_candidates(now=1_700_000_000.0)

        twenty_m = next(candidate for candidate in candidates if candidate.band == "20m")
        propagation_reason = next(
            reason for reason in twenty_m.score.reasons if reason.factor == "propagation"
        )
        self.assertEqual(propagation_reason.points, app_state.config.scoring.weights["propagation"] * 0.8)
        self.assertIn("NOAA fixture", propagation_reason.detail)
        output = "\n".join(captured.output)
        self.assertIn("kp=3.0", output)
        self.assertIn("sfi=145.0", output)
        self.assertIn("20m=0.800", output)
        for factor in (
            "freshness", "sources", "needed_dxcc", "signal",
            "reliability", "propagation", "path_dx",
        ):
            self.assertIn(f"{factor}=", output)
        app_state.aggregator.close()
        app_state.db.close()

    def test_refresh_candidates_logs_band_opening_when_threshold_crossed(self):
        # Mock data má na 20m 2 odlišné stanice (JA1XYZ, W1AW) -- práh 2 se
        # tedy překročí hned prvním refreshem.
        app_state = build_app_state(
            NotificationsConfig(enabled=True, min_distinct_stations=2, cooldown_minutes=30.0, max_per_hour=10)
        )
        app_state.refresh_candidates(now=1000.0)
        recent = app_state.db.recent_band_openings()
        self.assertTrue(any(row["band"] == "20m" for row in recent))
        app_state.aggregator.close()
        app_state.db.close()

    def test_refresh_candidates_does_not_duplicate_on_next_cycle(self):
        app_state = build_app_state(
            NotificationsConfig(enabled=True, min_distinct_stations=2, cooldown_minutes=30.0, max_per_hour=10)
        )
        app_state.refresh_candidates(now=1000.0)
        first_count = len(app_state.db.recent_band_openings())
        app_state.refresh_candidates(now=1005.0)
        second_count = len(app_state.db.recent_band_openings())
        self.assertEqual(first_count, second_count, "dokud pásmo zůstává otevřené, nesmí přibýt další záznam")
        app_state.aggregator.close()
        app_state.db.close()

    def test_disabled_notifications_never_log_anything(self):
        app_state = build_app_state(
            NotificationsConfig(enabled=False, min_distinct_stations=2, cooldown_minutes=30.0, max_per_hour=10)
        )
        app_state.refresh_candidates(now=1000.0)
        self.assertEqual(app_state.db.recent_band_openings(), [])
        app_state.aggregator.close()
        app_state.db.close()

    def test_high_threshold_never_fires_for_small_mock_dataset(self):
        app_state = build_app_state()  # default min_distinct_stations=5, mock nemá tolik stanic na jednom pásmu
        app_state.refresh_candidates(now=1000.0)
        self.assertEqual(app_state.db.recent_band_openings(), [])
        app_state.aggregator.close()
        app_state.db.close()


if __name__ == "__main__":
    unittest.main()
