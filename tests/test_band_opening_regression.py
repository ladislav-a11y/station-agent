"""Cílené regresní testy pro zobrazování band-opening událostí přes
GET /api/notifications: zobrazení VŠECH událostí (ne jen poslední), povinná
pole každé události, propagation vysvětlení v ``reason``, stav "neověřeno"
u propagation zdroje a zachované cooldown/hodinové limity -- vše ověřeno
přes skutečný běžící HTTP server, ne jen přímým voláním BandOpeningTracker.
"""

from __future__ import annotations

import json
import threading
import unittest
import urllib.request

from station_agent.adapters.mock import MockAdapter
from station_agent.aggregator import Aggregator
from station_agent.app_state import AppState
from station_agent.config import AppConfig, NotificationsConfig, WebConfig
from station_agent.db import Database
from station_agent.models import Candidate
from station_agent.propagation import PropagationContext, PropagationService
from station_agent.rig.mock_rig import MockRig
from station_agent.web.server import create_server

MANDATORY_FIELDS = (
    "ts", "band", "station_count", "station_count_change", "threshold", "reason",
)


def _candidates(band: str, freq_hz_a: int, freq_hz_b: int, now: float) -> list[Candidate]:
    return [
        Candidate(
            callsign="JA1XYZ", freq_hz=freq_hz_a, mode="SSB", band=band,
            first_seen=now, last_seen=now, spotters={"A"},
        ),
        Candidate(
            callsign="W1AW", freq_hz=freq_hz_b, mode="SSB", band=band,
            first_seen=now, last_seen=now, spotters={"B"},
        ),
    ]


class BandOpeningHttpRegressionTests(unittest.TestCase):
    """Každý test si staví vlastní izolovaný AppState/server, aby stav
    jednoho testu (cooldown, hodinový strop, historie událostí) neovlivnil
    ostatní -- band-opening limity jsou stavové napříč voláními."""

    def setUp(self) -> None:
        self.config = AppConfig()
        self.config.web = WebConfig(host="127.0.0.1", port=0)
        self.db = Database(":memory:")
        rig = MockRig()
        aggregator = Aggregator([MockAdapter()], self.db, self.config.scoring, qth_latlon=(50.0755, 14.4378))
        self.app_state = AppState(self.config, self.db, rig, aggregator)
        self.server = create_server(self.app_state)
        self.base_url = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self) -> None:
        self.server.shutdown()
        self.thread.join(timeout=5)
        self.server.server_close()
        self.app_state.aggregator.close()
        self.db.close()

    def _get_notifications(self) -> list[dict]:
        with urllib.request.urlopen(f"{self.base_url}/api/notifications", timeout=5) as resp:
            self.assertEqual(resp.status, 200)
            return json.loads(resp.read())["band_openings"]

    def _set_notifications_config(self, **overrides) -> None:
        defaults = dict(enabled=True, min_distinct_stations=2, cooldown_minutes=0.01, max_per_hour=10)
        defaults.update(overrides)
        self.app_state.config.notifications = NotificationsConfig(**defaults)
        self.app_state.band_opening_tracker = self.app_state.band_opening_tracker.__class__(
            self.app_state.config.notifications
        )

    # -- 1. Obnovené zobrazování VŠECH událostí, ne jen poslední ----------

    def test_all_logged_band_openings_are_displayed_not_only_latest(self):
        self._set_notifications_config()
        self.app_state._check_band_openings(_candidates("20m", 14_195_000, 14_200_000, now=1000.0), now=1000.0)
        self.app_state._check_band_openings(_candidates("40m", 7_100_000, 7_150_000, now=1010.0), now=1010.0)
        self.app_state._check_band_openings(_candidates("15m", 21_200_000, 21_250_000, now=1020.0), now=1020.0)

        events = self._get_notifications()
        self.assertEqual(len(events), 3, "všechny tři otevření musí zůstat viditelná, ne jen poslední")
        # Nejnovější první (web/server.py vrací reversed(events)).
        self.assertEqual([e["band"] for e in events], ["15m", "40m", "20m"])

    # -- 2. Povinná pole každé události ------------------------------------

    def test_band_opening_event_has_all_mandatory_fields_with_correct_types(self):
        self._set_notifications_config()
        self.app_state._check_band_openings(_candidates("20m", 14_195_000, 14_200_000, now=1000.0), now=1000.0)

        events = self._get_notifications()
        self.assertEqual(len(events), 1)
        entry = events[0]
        for field_name in MANDATORY_FIELDS:
            self.assertIn(field_name, entry, f"chybí povinné pole {field_name!r}")
        self.assertEqual(entry["band"], "20m")
        self.assertIsInstance(entry["station_count"], int)
        self.assertIsInstance(entry["station_count_change"], int)
        self.assertIsInstance(entry["threshold"], int)
        self.assertIsInstance(entry["ts"], (int, float))
        self.assertIsInstance(entry["reason"], str)
        self.assertTrue(entry["reason"], "reason nesmí být prázdný řetězec")
        self.assertEqual(entry["threshold"], self.app_state.config.notifications.min_distinct_stations)

    # -- 3. Propagation vysvětlení v reason --------------------------------

    def test_band_opening_reason_carries_propagation_explanation_via_http(self):
        self._set_notifications_config()
        context = PropagationContext(
            kp=2.0, solar_flux=150.0, observed_at=1000.0, source="NOAA fixture",
            qth_locator="JN79FG", band_quality={"20m": 0.82},
        )

        class FixturePropagationService:
            @property
            def context(self):
                return context

        self.app_state.propagation = FixturePropagationService()
        self.app_state._check_band_openings(_candidates("20m", 14_195_000, 14_200_000, now=1000.0), now=1000.0)

        entry = self._get_notifications()[0]
        for expected in ("Kp 2.0", "SFI 150.0", "QTH JN79FG", "kvalita pásma 82 %", "zdroj NOAA fixture"):
            self.assertIn(expected, entry["reason"])

    # -- 4. Stav "neověřeno" propagation zdroje ----------------------------

    def test_band_opening_reason_reports_unverified_propagation_source_via_http(self):
        self._set_notifications_config()

        def failing_fetcher(**_kwargs):
            raise OSError("propagation source unreachable")

        service = PropagationService(qth_locator="JN79FG", fetcher=failing_fetcher)
        service.refresh_if_due(now=1000.0)
        self.assertFalse(service.verified, "fixture musí reprodukovat skutečný neověřený stav")
        self.assertIsNone(service.context)

        self.app_state.propagation = service
        self.app_state._check_band_openings(_candidates("20m", 14_195_000, 14_200_000, now=1000.0), now=1000.0)

        entry = self._get_notifications()[0]
        self.assertIn("propagation data nejsou dostupná", entry["reason"])

    # -- 5. Zachované cooldown/hodinové limity přes HTTP -------------------

    def test_cooldown_suppresses_reopen_notification_via_http(self):
        self._set_notifications_config(cooldown_minutes=30.0, max_per_hour=10)
        self.app_state._check_band_openings(_candidates("20m", 14_195_000, 14_200_000, now=1000.0), now=1000.0)
        self.app_state._check_band_openings([], now=1001.0)  # pásmo se uzavře
        self.app_state._check_band_openings(_candidates("20m", 14_195_000, 14_200_000, now=1002.0), now=1002.0)

        events = self._get_notifications()
        self.assertEqual(len(events), 1, "reopen 1s po zavření musí být potlačen 30min cooldownem")

    def test_hourly_cap_limits_events_across_bands_via_http(self):
        self._set_notifications_config(cooldown_minutes=0.001, max_per_hour=2)
        bands = [
            ("20m", 14_195_000, 14_200_000),
            ("40m", 7_100_000, 7_150_000),
            ("15m", 21_200_000, 21_250_000),
        ]
        for index, (band, freq_a, freq_b) in enumerate(bands):
            self.app_state._check_band_openings(
                _candidates(band, freq_a, freq_b, now=1000.0 + index), now=1000.0 + index
            )

        events = self._get_notifications()
        self.assertEqual(len(events), 2, "hodinový strop 2 musí zastavit třetí notifikaci i přes HTTP")


if __name__ == "__main__":
    unittest.main()
