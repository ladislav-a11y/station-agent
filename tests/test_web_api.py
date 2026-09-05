"""Integrační test webového GUI/API -- ověřuje i to, že server běží
výhradně na loopback adrese (viz AGENTS.md pravidlo 5)."""

from __future__ import annotations

import json
import socket
import sqlite3
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock
import urllib.error
import urllib.request

from station_agent.adapters.mock import MockAdapter
from station_agent.aggregator import Aggregator
from station_agent.app_state import AppState, PollingLoop
from station_agent.config import AppConfig, NotificationsConfig, WebConfig
from station_agent.db import Database
from station_agent.models import RigState
from station_agent.notifications import BandOpeningTracker
from station_agent.propagation import PropagationContext
from station_agent.rig.mock_rig import MockRig
from station_agent.scoring import DEFAULT_WEIGHTS, ScoringConfig
from station_agent.web import server as server_module
from station_agent.web.server import create_server


def build_test_app_state(port: int = 0, scoring_cfg: ScoringConfig | None = None) -> AppState:
    config = AppConfig()
    config.web = WebConfig(host="127.0.0.1", port=port)
    db = Database(":memory:")
    rig = MockRig()
    if scoring_cfg is None:
        scoring_cfg = ScoringConfig(weights=dict(DEFAULT_WEIGHTS), spot_max_age_minutes=15)
    aggregator = Aggregator([MockAdapter()], db, scoring_cfg, qth_latlon=(50.0755, 14.4378))
    return AppState(config, db, rig, aggregator)


class WebApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app_state = build_test_app_state()
        cls.server = create_server(cls.app_state)
        assert cls.server.server_address[0] in ("127.0.0.1", "::1")
        cls.base_url = f"http://127.0.0.1:{cls.server.server_address[1]}"
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.thread.join(timeout=5)
        cls.server.server_close()
        cls.app_state.db.close()

    def _get(self, path: str):
        with urllib.request.urlopen(f"{self.base_url}{path}", timeout=5) as resp:
            return resp.status, resp.headers.get("Content-Type", ""), resp.read()

    def _post_json(self, path: str, payload: dict):
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}{path}", data=data, headers={"Content-Type": "application/json"}, method="POST"
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read())

    def test_server_binds_to_loopback_only(self):
        self.assertIn(self.server.server_address[0], ("127.0.0.1", "::1"))

    def test_index_html_served(self):
        status, content_type, body = self._get("/")
        self.assertEqual(status, 200)
        self.assertIn("text/html", content_type)
        self.assertIn(b"Station Agent", body)

    def test_static_assets_served(self):
        status, content_type, body = self._get("/app.js")
        self.assertEqual(status, 200)
        self.assertIn("javascript", content_type)

        status, content_type, _ = self._get("/style.css")
        self.assertEqual(status, 200)
        self.assertIn("css", content_type)

    def test_gui_has_visible_shutdown_button_wired_to_shutdown_endpoint(self):
        _, _, html = self._get("/")
        page = html.decode("utf-8")
        self.assertIn('id="shutdown-button"', page)
        self.assertIn("Ukončit", page)

        _, _, javascript = self._get("/app.js")
        script = javascript.decode("utf-8")
        self.assertIn('getElementById("shutdown-button")', script)
        self.assertIn('fetch("/api/shutdown"', script)
        self.assertIn("window.confirm(", script)

    def test_autotune_and_hold_use_immediate_rocker_and_reset_manual_selection(self):
        _, _, html = self._get("/")
        page = html.decode("utf-8")
        self.assertIn('type="radio" name="autotune-mode" id="at-enabled"', page)
        self.assertIn('type="radio" name="autotune-mode" id="at-hold"', page)
        self.assertIn('class="autotune-mode-box"', page)

        _, _, javascript = self._get("/app.js")
        script = javascript.decode("utf-8")
        self.assertIn('document.getElementById("at-enabled").addEventListener("change"', script)
        self.assertIn("clearCandidateSelection();", script)
        self.assertIn("updateAutotune();", script)

    def test_gui_shows_distinct_text_for_each_autotune_hold_visibility_state(self):
        """Viditelnost stavu v GUI: rocker přepínač sám o sobě nerozliší
        "obojí vypnuto" od chybějícího "checked" atributu, takže
        renderHoldCountdown (viz app.js) musí pro každý ze tří vzájemně
        výlučných stavů (HOLD aktivní / AUTO TUNE aktivní / obojí vypnuté)
        vypsat textem odlišitelný stav."""
        _, _, javascript = self._get("/app.js")
        script = javascript.decode("utf-8")
        self.assertIn("function renderHoldCountdown()", script)
        self.assertIn('el.textContent = "HOLD aktivní"', script)
        self.assertIn('el.textContent = "AUTO TUNE vypnuto"', script)
        self.assertIn('el.textContent = "AUTO TUNE aktivní"', script)

    def test_candidates_endpoint_returns_scored_candidates(self):
        status, content_type, body = self._get("/api/candidates")
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertIn("candidates", data)
        self.assertGreater(len(data["candidates"]), 0)
        first = data["candidates"][0]
        for key in ("callsign", "freq_hz", "mode", "band", "age_seconds", "confirming_sources", "score"):
            self.assertIn(key, first)
        self.assertIn("reasons", first["score"])

    def test_status_endpoint_reports_bands_modes_and_autotune(self):
        status, _, body = self._get("/api/status")
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertEqual(data["bands"], self.app_state.config.bands)
        self.assertEqual(data["modes"], self.app_state.config.modes)
        self.assertIn("autotune", data)
        self.assertIn("min_score", data)
        self.assertEqual(data["rig_mode"], "mock")

    def test_status_endpoint_reports_source_status(self):
        self.app_state.refresh_candidates()
        status, _, body = self._get("/api/status")
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertIn("sources", data)
        names = [s["name"] for s in data["sources"]]
        self.assertIn("mock", names)
        mock_status = next(s for s in data["sources"] if s["name"] == "mock")
        for key in ("status", "last_error", "last_success_age_seconds", "backoff_remaining_seconds", "cached_spot_count"):
            self.assertIn(key, mock_status)
        self.assertEqual(mock_status["status"], "ok")

    def test_status_endpoint_reports_presets(self):
        status, _, body = self._get("/api/status")
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertIn("presets", data)
        self.assertTrue(data["presets"])
        for preset in data["presets"]:
            for key in ("key", "label", "bands", "modes"):
                self.assertIn(key, preset)

    def test_status_endpoint_reports_bearing_distance_country_for_tuned_rig(self):
        """Bearing/vzdálenost/země musí být u rig live, ne jen u kandidátů."""
        self.app_state.current_rig_state = RigState(
            freq_hz=14_195_000, mode="SSB", tuned_at=1000.0, callsign="DX1AA",
            score=50, country="Testlandia", bearing_deg=123.4, distance_km=5678.0,
        )
        try:
            status, _, body = self._get("/api/status")
            self.assertEqual(status, 200)
            rig = json.loads(body)["rig"]
            self.assertEqual(rig["country"], "Testlandia")
            self.assertEqual(rig["bearing_deg"], 123.4)
            self.assertEqual(rig["distance_km"], 5678.0)
        finally:
            self.app_state.current_rig_state = None

        _, _, javascript = self._get("/app.js")
        script = javascript.decode("utf-8")
        self.assertIn("rig.country", script)

    def test_status_and_gui_expose_current_kp_in_header_corner(self):
        context = PropagationContext(
            kp=4.0, solar_flux=130.0, observed_at=1_700_000_000.0,
            source="NOAA fixture", qth_locator="JN79FG",
            band_quality={"20m": 0.5}, explanation="fixture",
        )

        class FixturePropagationService:
            @property
            def context(self):
                return context

        self.app_state.propagation = FixturePropagationService()
        status, _, body = self._get("/api/status")
        self.assertEqual(status, 200)
        propagation = json.loads(body)["propagation"]
        self.assertEqual(propagation["kp"], 4.0)
        self.assertTrue(propagation["verified"])
        self.assertEqual(propagation["status"], "verified")

        _, _, html = self._get("/")
        page = html.decode("utf-8")
        self.assertIn('id="propagation-status"', page)
        self.assertIn('id="propagation-summary"', page)
        self.assertIn('id="propagation-bands"', page)
        _, _, javascript = self._get("/app.js")
        script = javascript.decode("utf-8")
        self.assertIn("renderPropagation(status)", script)
        self.assertIn("`Kp: ${p.kp.toFixed(1)}", script)
        self.assertIn("p.solar_flux.toFixed(1)", script)
        self.assertIn("Object.entries(p.band_quality || {})", script)

    def test_status_marks_failed_propagation_source_as_unverified(self):
        class FailedPropagationService:
            context = None
            verified = False
            last_error = "OSError: offline"

        self.app_state.propagation = FailedPropagationService()
        status, _, body = self._get("/api/status")
        self.assertEqual(status, 200)
        propagation = json.loads(body)["propagation"]
        self.assertFalse(propagation["verified"])
        self.assertEqual(propagation["status"], "unverified")
        self.assertEqual(propagation["error"], "OSError: offline")
        self.assertIsNone(propagation["kp"])
        self.assertIsNone(propagation["solar_flux"])
        self.assertEqual(propagation["band_quality"], {})

    def test_notifications_endpoint_reports_logged_band_openings(self):
        self.app_state.band_opening_tracker = BandOpeningTracker(
            NotificationsConfig(
                enabled=True, min_distinct_stations=2,
                cooldown_minutes=30.0, max_per_hour=10,
            )
        )
        event = self.app_state.band_opening_tracker.check({"20m": 6}, now=1000.0)[0]
        second = self.app_state.band_opening_tracker.check(
            {"20m": 6, "40m": 4}, now=1010.0
        )[0]

        status, _, body = self._get("/api/notifications")
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertEqual(len(data["band_openings"]), 2)
        entry = data["band_openings"][0]
        self.assertEqual(entry["band"], second.band)
        self.assertEqual(entry["station_count"], second.station_count)
        self.assertEqual(entry["station_count_change"], 4)
        self.assertEqual(entry["threshold"], 2)
        self.assertIn("ts", entry)
        self.assertEqual(data["band_openings"][1]["band"], event.band)

    def test_gui_renders_every_logged_band_opening(self):
        _, _, javascript = self._get("/app.js")
        script = javascript.decode("utf-8")
        self.assertIn("for (const event of data.band_openings)", script)
        self.assertNotIn("data.band_openings[0]", script)
        for required_field in (
            "event.band", "event.ts", "event.station_count",
            "event.station_count_change", "event.threshold", "event.reason",
        ):
            self.assertIn(required_field, script)

    def test_qso_history_requires_explicit_post_and_preserves_bearing(self):
        self.app_state.refresh_candidates()
        candidate = self.app_state.latest_candidates[0]
        _, _, body = self._get("/api/qso/history")
        before = len(json.loads(body)["history"])
        status, data = self._post_json(
            "/api/qso/history",
            {"callsign": candidate.callsign, "freq_hz": candidate.freq_hz,
             "mode": candidate.mode, "band": candidate.band, "bearing_deg": -999},
        )
        self.assertEqual(status, 201)
        self.assertTrue(data["ok"])
        _, _, body = self._get("/api/qso/history")
        history = json.loads(body)["history"]
        self.assertEqual(len(history), before + 1)
        self.assertEqual(history[0]["callsign"], candidate.callsign)
        self.assertEqual(history[0]["bearing_deg"], candidate.bearing_deg)

    def test_qso_history_rejects_non_candidate_and_non_finite_frequency(self):
        self.app_state.refresh_candidates()
        for payload in (
            {"callsign": "FAKE", "freq_hz": 14195000, "mode": "SSB", "band": "20m"},
            {"callsign": "FAKE", "freq_hz": float("inf"), "mode": "SSB", "band": "20m"},
        ):
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                self._post_json("/api/qso/history", payload)
            self.assertIn(ctx.exception.code, (400, 409))

    def test_post_autotune_updates_settings(self):
        status, data = self._post_json(
            "/api/autotune", {"enabled": True, "min_score": 42, "min_hold_seconds": 30, "min_score_delta": 3}
        )
        self.assertEqual(status, 200)
        self.assertTrue(data["autotune"]["enabled"])
        self.assertEqual(data["min_score"], 42)

        _, _, body = self._get("/api/status")
        refreshed = json.loads(body)
        self.assertTrue(refreshed["autotune"]["enabled"])
        self.assertEqual(refreshed["min_score"], 42)
        self.assertEqual(refreshed["autotune"]["min_hold_seconds"], 30)
        self.assertEqual(refreshed["autotune"]["min_score_delta"], 3)

    def test_post_autotune_enabled_true_forces_hold_off(self):
        """AUTO TUNE a HOLD jsou vzájemně výlučné -- zapnutí AUTO TUNE musí
        vždy vypnout HOLD, i kdyby HOLD byl předtím zapnutý."""
        self._post_json("/api/autotune", {"enabled": False, "hold": True})
        status, data = self._post_json("/api/autotune", {"enabled": True})
        self.assertEqual(status, 200)
        self.assertTrue(data["autotune"]["enabled"])
        self.assertFalse(data["autotune"]["hold"])

    def test_post_autotune_hold_true_forces_enabled_off(self):
        self._post_json("/api/autotune", {"enabled": True, "hold": False})
        status, data = self._post_json("/api/autotune", {"hold": True})
        self.assertEqual(status, 200)
        self.assertFalse(data["autotune"]["enabled"])
        self.assertTrue(data["autotune"]["hold"])

    def test_post_autotune_both_true_in_same_payload_hold_wins(self):
        status, data = self._post_json("/api/autotune", {"enabled": True, "hold": True})
        self.assertEqual(status, 200)
        self.assertFalse(data["autotune"]["enabled"])
        self.assertTrue(data["autotune"]["hold"])

    def test_status_countdown_runs_only_during_autotune(self):
        self.app_state.current_rig_state = RigState(
            freq_hz=14_195_000, mode="SSB", tuned_at=900.0, callsign="DX1AA", score=50,
        )
        self.app_state.config.autotune.min_hold_seconds = 120.0
        self._post_json("/api/autotune", {"enabled": True, "hold": False})
        with mock.patch.object(server_module.time, "time", return_value=950.0):
            _, _, body = self._get("/api/status")
        data = json.loads(body)
        self.assertEqual(data["autotune"]["autotune_remaining_seconds"], 70.0)
        self.assertIsNone(data["autotune"]["hold_remaining_seconds"])

        self._post_json("/api/autotune", {"enabled": False, "hold": False})
        _, _, body = self._get("/api/status")
        data = json.loads(body)
        self.assertIsNone(data["autotune"]["autotune_remaining_seconds"])

        self._post_json("/api/autotune", {"hold": True})
        _, _, body = self._get("/api/status")
        data = json.loads(body)
        self.assertIsNone(data["autotune"]["autotune_remaining_seconds"])
        self.assertIsNone(data["autotune"]["hold_remaining_seconds"])

    def test_explicit_hold_via_api_without_manual_tune_never_auto_resumes_autotune(self):
        """HOLD zapnutý explicitně přes POST /api/autotune (bez ručního
        NALADIT) nesmí AUTO TUNE nikdy sám znovu aktivovat -- ani po
        dlouhé době, ani když by min_hold_seconds/min_score_delta jinak
        přeladění dovolily. Pokrývá jinou cestu než ruční NALADIT (viz
        tests/test_manual_tune.py), konkrétně explicitní zapnutí HOLD
        operátorem přes formulář/GUI bez výběru kandidáta."""
        self.app_state.refresh_candidates()
        self.app_state.config.autotune.min_hold_seconds = 10.0
        self.app_state.config.autotune.min_score_delta = 0
        self.app_state.autotune_engine.min_score = 0

        status, data = self._post_json("/api/autotune", {"enabled": False, "hold": True})
        self.assertEqual(status, 200)
        self.assertFalse(data["autotune"]["enabled"])
        self.assertTrue(data["autotune"]["hold"])

        base_now = time.time()
        for elapsed in (0.0, 60.0, 3600.0, 86_400.0):
            decision = self.app_state.run_autotune_cycle(now=base_now + elapsed)
            self.assertEqual(decision.action, "NONE")
            self.assertEqual(decision.reason, "AUTO TUNE je vypnuté")
            self.assertFalse(self.app_state.config.autotune.enabled)
            self.assertTrue(self.app_state.config.autotune.hold)

        _, _, body = self._get("/api/status")
        refreshed = json.loads(body)
        self.assertFalse(refreshed["autotune"]["enabled"])
        self.assertTrue(refreshed["autotune"]["hold"])

    def test_unknown_path_is_404(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self._get("/does-not-exist")
        self.assertEqual(ctx.exception.code, 404)

    def test_no_ptt_endpoint_exists(self):
        for path in ("/api/ptt", "/api/tx", "/api/transmit", "/ptt"):
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                self._get(path)
            self.assertEqual(ctx.exception.code, 404)

    def test_post_filters_updates_bands_and_modes(self):
        original_bands = list(self.app_state.config.bands)
        original_modes = list(self.app_state.config.modes)
        try:
            allowed_modes = ["SSB", "FT8", "RTTY", "PSK31", "PSK63", "OTHER_DIGITAL"]  # bez CW
            allowed_bands = ["20m", "17m", "15m", "12m", "10m"]  # bez 40m
            status, data = self._post_json("/api/filters", {"bands": allowed_bands, "modes": allowed_modes})
            self.assertEqual(status, 200)
            self.assertEqual(data["bands"], allowed_bands)
            self.assertEqual(data["modes"], allowed_modes)
            self.assertEqual(
                self.app_state.db.load_filter_preferences(),
                (allowed_bands, allowed_modes),
            )

            _, _, body = self._get("/api/status")
            refreshed = json.loads(body)
            self.assertEqual(refreshed["bands"], allowed_bands)
            self.assertEqual(refreshed["modes"], allowed_modes)
        finally:
            self._post_json("/api/filters", {"bands": original_bands, "modes": original_modes})

    def test_post_filters_ignores_unknown_values(self):
        original_bands = list(self.app_state.config.bands)
        original_modes = list(self.app_state.config.modes)
        try:
            status, data = self._post_json(
                "/api/filters", {"bands": ["20m", "not-a-band"], "modes": ["FT8", "XYZ"]}
            )
            self.assertEqual(status, 200)
            self.assertEqual(data["bands"], ["20m"])
            self.assertEqual(data["modes"], ["FT8"])
        finally:
            self._post_json("/api/filters", {"bands": original_bands, "modes": original_modes})


class AutoTuneRespectsGuiFiltersTests(unittest.TestCase):
    """Regrese: praktický test GUI odhalil, že AUTO TUNE naladil ZS6DEF na
    7.030 MHz CW, přestože GUI mělo CW i 40m vypnuté a tabulka kandidátů
    byla filtrovaná správně. Příčina: GUI filtry (checkboxy) se nikdy
    neposílaly na backend, takže AutoTuneEngine dostával kandidáty
    postavené nad výchozí (neomezenou) sadou módů/pásem z configu."""

    def setUp(self):
        # Tenhle test ověřuje routing filtrů do AUTO TUNE, ne scoring
        # matematiku -- propagation faktor (viz scoring.py) záměrně
        # odměňuje stanice na aktuálně "rušnějším" pásmu, což by s
        # DEFAULT_WEIGHTS mohlo náhodně přeřadit pořadí mock kandidátů podle
        # toho, kolik jich zrovna sdílí pásmo (viz spotters/band_activity).
        # Proto tu používáme scoring config s propagation váhou 0 (přesunutou
        # do signal), aby test zůstal deterministický vůči SNR mock dat a
        # dál skutečně reprodukoval nahlášený filter-routing bug.
        weights = dict(DEFAULT_WEIGHTS)
        weights["signal"] += weights.pop("propagation", 0)
        scoring_cfg = ScoringConfig(weights=weights, spot_max_age_minutes=15)
        self.app_state = build_test_app_state(scoring_cfg=scoring_cfg)
        self.server = create_server(self.app_state)
        self.base_url = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.thread.join(timeout=5)
        self.server.server_close()
        self.app_state.db.close()

    def _post_json(self, path: str, payload: dict):
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}{path}", data=data, headers={"Content-Type": "application/json"}, method="POST"
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read())

    def _enable_autotune(self):
        self._post_json(
            "/api/autotune",
            {"enabled": True, "hold": False, "min_score": 0, "min_hold_seconds": 0, "min_score_delta": 0},
        )

    def test_zs6def_cw_wins_unfiltered_but_must_not_be_picked_when_cw_and_40m_disabled(self):
        # Nejprve ověříme, že mock ZS6DEF/7.030 CW má skutečně nejvyšší
        # skóre, aby test věrně reprodukoval nahlášenou situaci -- bez
        # tohoto předpokladu by test nic neověřoval.
        self.app_state.refresh_candidates()
        best_unfiltered = self.app_state.latest_candidates[0]
        self.assertEqual(best_unfiltered.callsign, "ZS6DEF")
        self.assertEqual(best_unfiltered.mode, "CW")
        self.assertEqual(best_unfiltered.band, "40m")

        self._enable_autotune()
        # GUI: SSB, FT8, RTTY, PSK31, PSK63, Other Digital zapnuté, CW vypnuté;
        # 20m/17m/15m/12m/10m zapnuté, 40m vypnuté.
        status, _ = self._post_json(
            "/api/filters",
            {
                "modes": ["SSB", "FT8", "RTTY", "PSK31", "PSK63", "OTHER_DIGITAL"],
                "bands": ["20m", "17m", "15m", "12m", "10m"],
            },
        )
        self.assertEqual(status, 200)

        candidates = self.app_state.refresh_candidates()
        self.assertTrue(all(c.mode != "CW" for c in candidates))
        self.assertTrue(all(c.band != "40m" for c in candidates))
        self.assertFalse(any(c.callsign == "ZS6DEF" for c in candidates))

        decision = self.app_state.run_autotune_cycle()
        self.assertEqual(decision.action, "TUNE")
        self.assertIsNotNone(decision.candidate)
        self.assertNotEqual(decision.candidate.callsign, "ZS6DEF")
        self.assertNotEqual(decision.candidate.mode, "CW")
        self.assertNotEqual(decision.candidate.band, "40m")
        self.assertEqual(self.app_state.rig.get_mode(), decision.candidate.mode)
        self.assertNotEqual(self.app_state.rig.get_mode(), "CW")

    def test_filter_change_takes_effect_at_runtime(self):
        self._enable_autotune()

        # 1) Se všemi módy/pásmy povolenými AUTO TUNE naladí ZS6DEF (CW, 40m).
        self.app_state.refresh_candidates()
        first_decision = self.app_state.run_autotune_cycle()
        self.assertEqual(first_decision.action, "TUNE")
        self.assertEqual(first_decision.candidate.callsign, "ZS6DEF")

        # 2) Za běhu (bez restartu) uživatel v GUI vypne CW a 40m.
        self._post_json(
            "/api/filters",
            {
                "modes": ["SSB", "FT8", "RTTY", "PSK31", "PSK63", "OTHER_DIGITAL"],
                "bands": ["20m", "17m", "15m", "12m", "10m"],
            },
        )

        candidates = self.app_state.refresh_candidates()
        self.assertFalse(any(c.callsign == "ZS6DEF" for c in candidates))

        second_decision = self.app_state.run_autotune_cycle()
        self.assertEqual(second_decision.action, "TUNE")
        self.assertNotEqual(second_decision.candidate.callsign, "ZS6DEF")
        self.assertNotEqual(second_decision.candidate.mode, "CW")
        self.assertNotEqual(second_decision.candidate.band, "40m")


class _RaisingWfile:
    def __init__(self, exc: BaseException):
        self._exc = exc

    def write(self, data):
        raise self._exc


class BenignClientDisconnectTests(unittest.TestCase):
    """Live test hlásil ConnectionAbortedError/BrokenPipeError/WinError 10053
    při zápisu HTTP odpovědi, když prohlížeč mezitím zavře spojení -- ty se
    musí ošetřit jako benigní odpojení klienta (bez dlouhého tracebacku),
    ne jako neočekávaná chyba serveru. Testuje se přímo na vrstvě
    Handler._send_json/_send_static, protože reprodukovat přesné OS chyby
    přes reálný socket je nedeterministické (timing race)."""

    def setUp(self):
        self.app_state = build_test_app_state()

    def tearDown(self):
        self.app_state.db.close()

    def _handler(self):
        handler_cls = server_module._make_handler(self.app_state)
        handler = handler_cls.__new__(handler_cls)
        handler.client_address = ("127.0.0.1", 55000)
        handler.request_version = "HTTP/1.1"
        handler.command = "GET"
        handler.requestline = "GET / HTTP/1.1"
        handler.close_connection = False
        handler._headers_buffer = []
        return handler

    def _assert_send_json_swallows(self, exc: BaseException):
        handler = self._handler()
        handler.wfile = _RaisingWfile(exc)
        handler._send_json({"ok": True})  # nesmí propagovat výjimku
        self.assertTrue(handler.close_connection)

    def test_send_json_swallows_connection_aborted_error(self):
        self._assert_send_json_swallows(ConnectionAbortedError("client aborted"))

    def test_send_json_swallows_broken_pipe_error(self):
        self._assert_send_json_swallows(BrokenPipeError("broken pipe"))

    def test_send_json_swallows_connection_reset_error(self):
        self._assert_send_json_swallows(ConnectionResetError("connection reset"))

    def test_send_json_swallows_winerror_10053(self):
        exc = OSError("Software caused connection abort")
        exc.winerror = 10053
        self._assert_send_json_swallows(exc)

    def test_send_json_reraises_unrelated_oserror(self):
        handler = self._handler()
        handler.wfile = _RaisingWfile(OSError("nesouvisející chyba"))
        with self.assertRaises(OSError):
            handler._send_json({"ok": True})

    def test_send_static_swallows_connection_aborted_error(self):
        handler = self._handler()
        handler.wfile = _RaisingWfile(ConnectionAbortedError("client aborted"))
        handler._send_static("index.html")  # nesmí propagovat výjimku
        self.assertTrue(handler.close_connection)

    def test_is_benign_disconnect_helper(self):
        self.assertTrue(server_module._is_benign_disconnect(ConnectionAbortedError()))
        self.assertTrue(server_module._is_benign_disconnect(BrokenPipeError()))
        self.assertTrue(server_module._is_benign_disconnect(ConnectionResetError()))
        winerr = OSError()
        winerr.winerror = 10053
        self.assertTrue(server_module._is_benign_disconnect(winerr))
        self.assertFalse(server_module._is_benign_disconnect(ValueError("not an OSError")))
        self.assertFalse(server_module._is_benign_disconnect(OSError("unrelated")))


class AbruptSocketDisconnectIntegrationTests(unittest.TestCase):
    """Doplňkový end-to-end test: klient se odpojí hned po odeslání
    requestu, aniž by si přečetl odpověď -- server nesmí spadnout ani
    přestat obsluhovat další klienty."""

    def setUp(self):
        self.app_state = build_test_app_state()
        self.server = create_server(self.app_state)
        self.host, self.port = self.server.server_address[0], self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.thread.join(timeout=5)
        self.server.server_close()
        self.app_state.db.close()

    def test_server_stays_responsive_after_abrupt_client_disconnect(self):
        sock = socket.create_connection((self.host, self.port), timeout=2)
        sock.sendall(b"GET /api/status HTTP/1.1\r\nHost: localhost\r\n\r\n")
        sock.close()  # odpojíme se dřív, než si přečteme odpověď

        with urllib.request.urlopen(f"http://{self.host}:{self.port}/api/status", timeout=5) as resp:
            self.assertEqual(resp.status, 200)


class ShutdownEndpointTests(unittest.TestCase):
    """POST /api/shutdown je tlačítko "Ukončit" v GUI (DoD): musí v tomto
    pořadí zastavit polling, zastavit web server, uzavřít spojení a teprve
    pak vyčistit obsah databáze -- soubor a schéma zůstávají zachované,
    mažou se jen řádky (viz Database.clear_all_data)."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.db_path = str(Path(self.tmpdir.name) / "station_agent.sqlite3")

        config = AppConfig()
        config.web = WebConfig(host="127.0.0.1", port=0)
        db = Database(self.db_path)
        rig = MockRig()
        scoring_cfg = ScoringConfig(weights=dict(DEFAULT_WEIGHTS), spot_max_age_minutes=15)
        aggregator = Aggregator([MockAdapter()], db, scoring_cfg, qth_latlon=(50.0755, 14.4378))
        self.app_state = AppState(config, db, rig, aggregator)
        self.app_state.refresh_candidates()  # naplní tabulku spots reálnými řádky

        # Zaseje i zbylé DATA_TABLES (AUTO TUNE log, band-opening a QSO
        # historii, worked-DXCC cache, uložené GUI filtry), aby test ověřil
        # skutečné smazání starých záznamů přes shutdown endpoint, ne jen
        # to, že tabulky byly prázdné už předtím (viz DoD -- "nezůstanou
        # staré spoty, AUTO TUNE log, band-opening historie, QSO historie
        # ani jiné aplikační záznamy").
        db.mark_worked("Czech Republic")
        db.log_autotune("OK1ABC", 14_195_000, "SSB", 82, "test reason")
        db.log_band_opening("20m", 6)
        db.log_qso("OK1ABC", 14_195_000, "SSB", "20m")
        db.save_filter_preferences(["20m"], ["SSB"])

        self.polling_loop = PollingLoop(self.app_state, interval_seconds=0.05)
        self.polling_loop.start()

        self.server = create_server(self.app_state, self.polling_loop)
        self.host, self.port = self.server.server_address[0], self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def _wait_until(self, predicate, timeout: float = 5.0, interval: float = 0.02) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if predicate():
                return True
            time.sleep(interval)
        return predicate()

    def test_shutdown_stops_polling_and_server_then_clears_database_content(self):
        check_conn = sqlite3.connect(self.db_path)
        try:
            spots_before = check_conn.execute("SELECT COUNT(*) FROM spots").fetchone()[0]
        finally:
            check_conn.close()
        self.assertGreater(spots_before, 0)

        req = urllib.request.Request(
            f"http://{self.host}:{self.port}/api/shutdown", data=b"{}", method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read())
            self.assertTrue(data["ok"])

        # Polling se zastaví (vlákno se ukončí a PollingLoop.stop() ho vyresetuje na None).
        self.assertTrue(self._wait_until(lambda: self.polling_loop._thread is None))
        # Web server přestane obsluhovat serve_forever().
        self.assertTrue(self._wait_until(lambda: not self.thread.is_alive()))

        def _original_connection_closed() -> bool:
            try:
                self.app_state.db._conn.execute("SELECT 1")
                return False
            except sqlite3.ProgrammingError:
                return True

        # Čeká, až _perform_shutdown skutečně zavolá db.close() -- ne jen na
        # to, že data jsou vyčištěná (commit by mohl proběhnout dřív, než
        # se stihne zavolat close(), a soubor by tak na Windows zůstal
        # otevřený/zamčený pro následný úklid tmpdir).
        self.assertTrue(self._wait_until(_original_connection_closed))

        check_conn = sqlite3.connect(self.db_path)
        try:
            for table in Database.DATA_TABLES:
                count = check_conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                self.assertEqual(count, 0, table)
            # Soubor a schéma zůstávají zachované -- žádná tabulka nezmizela.
            tables = {
                row[0]
                for row in check_conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
        finally:
            check_conn.close()
        for table in Database.DATA_TABLES:
            self.assertIn(table, tables)

        # DoD: čištění při ukončení smí smazat jen řádky v DB, nikdy config
        # ani zdrojový kód -- tmpdir obsahuje výhradně databázový soubor a
        # repozitářový kód zůstává na disku nedotčený.
        self.assertEqual(
            {p.name for p in Path(self.tmpdir.name).iterdir()},
            {Path(self.db_path).name},
        )
        repo_root = Path(__file__).resolve().parent.parent
        self.assertTrue((repo_root / "station_agent" / "db.py").exists())
        self.assertTrue((repo_root / "station_agent" / "web" / "server.py").exists())


class CreateServerSafetyTests(unittest.TestCase):
    def test_rejects_non_loopback_host_even_if_bypassing_dataclass_validation(self):
        app_state = build_test_app_state()
        # WebConfig.__post_init__ by tohle při normální konstrukci odmítl --
        # zde ověřujeme, že create_server() vynucuje loopback i kdyby se
        # konfigurace omylem zmutovala až za běhu.
        app_state.config.web.host = "0.0.0.0"
        with self.assertRaises(ValueError):
            create_server(app_state)
        app_state.db.close()


if __name__ == "__main__":
    unittest.main()
