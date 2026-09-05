"""Integrační testy pro AppState -- ověřuje drátování mezi
refresh_candidates(), aggregator.band_activity() a BandOpeningTracker
(viz app_state._check_band_openings), včetně perzistence do DB pro
GET /api/notifications."""

from __future__ import annotations

import unittest

from station_agent.adapters.mock import MockAdapter
from station_agent.aggregator import Aggregator
from station_agent.app_state import AppState, PollingLoop
from station_agent.config import AppConfig, NotificationsConfig
from station_agent.db import Database
from station_agent.models import Candidate, RigState, ScoreResult
from station_agent.propagation import PropagationContext
from station_agent.rig.mock_rig import MockRig
from station_agent.rig.rigctld import RigctldError


def build_app_state(notifications_cfg: NotificationsConfig | None = None) -> AppState:
    config = AppConfig()
    if notifications_cfg is not None:
        config.notifications = notifications_cfg
    db = Database(":memory:")
    rig = MockRig()
    aggregator = Aggregator([MockAdapter()], db, config.scoring, qth_latlon=(50.0755, 14.4378))
    return AppState(config, db, rig, aggregator)


def build_app_state_with_db(
    db: Database, notifications_cfg: NotificationsConfig,
) -> AppState:
    config = AppConfig()
    config.notifications = notifications_cfg
    aggregator = Aggregator(
        [MockAdapter()], db, config.scoring, qth_latlon=(50.0755, 14.4378)
    )
    return AppState(config, db, MockRig(), aggregator)


class BandOpeningIntegrationTests(unittest.TestCase):
    def test_restart_restores_cooldown_and_global_hourly_limit(self):
        cfg = NotificationsConfig(
            enabled=True, min_distinct_stations=2,
            cooldown_minutes=30.0, max_per_hour=2,
        )
        db = Database(":memory:")
        db.log_band_opening("20m", 3, ts=990.0)
        db.log_band_opening("40m", 3, ts=995.0)

        app_state = build_app_state_with_db(db, cfg)
        events = app_state.band_opening_tracker.check(
            {"20m": 3, "15m": 3}, now=1000.0
        )

        self.assertEqual(events, [])
        app_state.aggregator.close()
        app_state.db.close()

    def test_restart_preserves_transition_deduplication_after_cooldown(self):
        cfg = NotificationsConfig(
            enabled=True, min_distinct_stations=2,
            cooldown_minutes=30.0, max_per_hour=10,
        )
        db = Database(":memory:")
        db.log_band_opening("20m", 3, ts=1000.0)

        app_state = build_app_state_with_db(db, cfg)
        continuously_open = app_state.band_opening_tracker.check(
            {"20m": 3}, now=3001.0
        )
        app_state.band_opening_tracker.check({"20m": 1}, now=3002.0)
        reopened = app_state.band_opening_tracker.check({"20m": 3}, now=3003.0)

        self.assertEqual(continuously_open, [])
        self.assertEqual(len(reopened), 1)
        app_state.aggregator.close()
        app_state.db.close()

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

    def test_band_opening_reason_contains_available_propagation_evidence(self):
        app_state = build_app_state(
            NotificationsConfig(
                enabled=True, min_distinct_stations=2,
                cooldown_minutes=30.0, max_per_hour=10,
            )
        )
        context = PropagationContext(
            kp=2.0,
            solar_flux=150.0,
            observed_at=1000.0,
            source="NOAA fixture",
            qth_locator="JN79FG",
            band_quality={"20m": 0.82},
        )

        class FixturePropagationService:
            @property
            def context(self):
                return context

        app_state.propagation = FixturePropagationService()
        app_state._check_band_openings(
            [
                Candidate(
                    callsign="JA1XYZ", freq_hz=14_195_000, mode="SSB", band="20m",
                    first_seen=1000.0, last_seen=1000.0, spotters={"A"},
                ),
                Candidate(
                    callsign="W1AW", freq_hz=14_200_000, mode="SSB", band="20m",
                    first_seen=1000.0, last_seen=1000.0, spotters={"B"},
                ),
            ],
            now=1000.0,
        )

        event = app_state.band_opening_tracker.events[0]
        self.assertIn("Kp 2.0", event.reason)
        self.assertIn("SFI 150.0", event.reason)
        self.assertIn("QTH JN79FG", event.reason)
        self.assertIn("kvalita pásma 82 %", event.reason)
        self.assertIn("stáří dat 0 min", event.reason)
        self.assertIn("zdroj NOAA fixture", event.reason)
        self.assertEqual(app_state.db.recent_band_openings()[0]["reason"], event.reason)
        app_state.aggregator.close()
        app_state.db.close()

    def test_band_opening_reason_explains_missing_propagation_data(self):
        app_state = build_app_state(
            NotificationsConfig(
                enabled=True, min_distinct_stations=2,
                cooldown_minutes=30.0, max_per_hour=10,
            )
        )
        app_state.propagation = None
        app_state._check_band_openings(
            [
                Candidate(
                    callsign="JA1XYZ", freq_hz=14_195_000, mode="SSB", band="20m",
                    first_seen=1000.0, last_seen=1000.0, spotters={"A"},
                ),
                Candidate(
                    callsign="W1AW", freq_hz=14_200_000, mode="SSB", band="20m",
                    first_seen=1000.0, last_seen=1000.0, spotters={"B"},
                ),
            ],
            now=1000.0,
        )

        self.assertIn(
            "propagation data nejsou dostupná",
            app_state.band_opening_tracker.events[0].reason,
        )
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


class CurrentStationScoreFreshnessTests(unittest.TestCase):
    """Regrese: skóre aktuálně naladěné stanice nesmí zůstat zamrzlé na
    hodnotě z okamžiku výběru -- AutoTuneEngine.decide() ho porovnává
    s průběžně přepočítávanými kandidáty (viz autotune.py pravidlo 7),
    takže se musí aktualizovat stejně jako u ostatních kandidátů."""

    def test_sync_current_score_updates_from_matching_candidate(self):
        app_state = build_app_state()
        app_state.current_rig_state = RigState(
            freq_hz=14_195_000, mode="SSB", tuned_at=1000.0, callsign="JA1XYZ", score=10,
        )
        candidate = Candidate(
            callsign="JA1XYZ", freq_hz=14_195_000, mode="SSB", band="20m",
            first_seen=1000.0, last_seen=1000.0, score=ScoreResult(total=77, reasons=[]),
        )

        app_state._sync_current_score([candidate])

        self.assertEqual(app_state.current_rig_state.score, 77)
        app_state.aggregator.close()
        app_state.db.close()

    def test_sync_current_score_preserves_last_known_when_station_not_among_candidates(self):
        app_state = build_app_state()
        app_state.current_rig_state = RigState(
            freq_hz=14_195_000, mode="SSB", tuned_at=1000.0, callsign="JA1XYZ", score=10,
        )

        app_state._sync_current_score([])

        self.assertEqual(app_state.current_rig_state.score, 10)
        app_state.aggregator.close()
        app_state.db.close()

    def test_refresh_candidates_updates_score_of_currently_tuned_station(self):
        """End-to-end: dřív refresh_candidates() přepočítal skóre jen pro
        ostatní kandidáty a current_rig_state.score zůstal navždy takový,
        jaký byl v okamžiku ladění (apply_decision) -- i po refreshi, který
        pro tu samou stanici spočítal jiné skóre."""
        app_state = build_app_state()
        app_state.refresh_candidates(now=1_700_000_000.0)
        app_state.current_rig_state = RigState(
            freq_hz=14_195_000, mode="SSB", tuned_at=1_700_000_000.0,
            callsign="JA1XYZ", score=1,
        )

        app_state.refresh_candidates(now=1_700_000_050.0)

        updated = next(c for c in app_state.latest_candidates if c.callsign == "JA1XYZ")
        self.assertEqual(app_state.current_rig_state.score, updated.score.total)
        self.assertNotEqual(app_state.current_rig_state.score, 1)
        app_state.aggregator.close()
        app_state.db.close()


class PollingLoopRigctldConnectionErrorTests(unittest.TestCase):
    """Regrese pro ConnectionResetError WinError 10054 při autotune volání
    rigctld: polling smyčka musí přerušené spojení k rigu rozlišit od
    ostatních neočekávaných chyb aplikace (RigctldClient._command ho
    signalizuje jako RigctldError, viz rig/rigctld.py) a zvládnout ho bez
    pádu vlákna, jen stručným varováním -- příští cyklus se sám znovu
    připojí, není proto potřeba celý traceback jako u skutečné chyby."""

    def _run_single_iteration(self, app_state) -> None:
        loop = PollingLoop(app_state, interval_seconds=0)

        def stop_after_first_wait(timeout=None):
            loop._stop_event.set()
            return True

        loop._stop_event.wait = stop_after_first_wait
        loop._run()

    def test_rigctld_connection_error_is_logged_as_warning_and_loop_survives(self):
        calls: list[int] = []

        class FailingAppState:
            def refresh_candidates(self, now=None):
                pass

            def run_autotune_cycle(self, now=None):
                calls.append(1)
                raise RigctldError(
                    "spojení s rigctld (127.0.0.1:4532) bylo přerušeno: "
                    "[WinError 10054] Vzdálený hostitel násilně přerušil "
                    "existující připojení"
                )

        with self.assertLogs("station_agent.app_state", level="WARNING") as captured:
            self._run_single_iteration(FailingAppState())

        self.assertEqual(calls, [1], "cyklus musí proběhnout přesně jednou a chybu nesmí polknout dřív")
        self.assertEqual(len(captured.records), 1)
        self.assertEqual(captured.records[0].levelname, "WARNING")
        self.assertIn("rigctld", captured.output[0])

    def test_unrelated_exception_still_logged_with_full_traceback(self):
        """Rozlišení musí platit oběma směry: nesouvisející chyba (mimo rozsah
        tohoto ticketu) musí dál procházet přes logger.exception() beze
        změny chování."""

        class OtherlyFailingAppState:
            def refresh_candidates(self, now=None):
                pass

            def run_autotune_cycle(self, now=None):
                raise RuntimeError("neočekávaná chyba mimo rigctld spojení")

        with self.assertLogs("station_agent.app_state", level="ERROR") as captured:
            self._run_single_iteration(OtherlyFailingAppState())

        self.assertEqual(captured.records[0].levelname, "ERROR")
        self.assertIsNotNone(captured.records[0].exc_info)


if __name__ == "__main__":
    unittest.main()
