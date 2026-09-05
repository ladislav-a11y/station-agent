"""Regresní testy ručního naladění (tlačítko NALADIT v GUI).

Pokrývá jak AppState.manual_tune() v mock režimu (bez HTTP), tak
POST /api/tune na úrovni backend/API -- viz dod-station-agent-v1.md a
požadavek na praktické ovládání Station Agent v1."""

from __future__ import annotations

import json
import threading
import unittest
import urllib.error
import urllib.request

from station_agent.web import server as server_module
from station_agent.web.server import create_server
from tests.test_web_api import build_test_app_state


class ManualTuneAppStateTests(unittest.TestCase):
    """Mock-mode regrese na úrovni AppState (bez HTTP serveru)."""

    def setUp(self):
        self.app_state = build_test_app_state()

    def tearDown(self):
        self.app_state.db.close()

    def test_manual_tune_valid_candidate_sets_rig_and_state(self):
        candidates = self.app_state.refresh_candidates()
        target = candidates[0]

        decision = self.app_state.manual_tune(target.callsign, target.freq_hz, target.mode)

        self.assertEqual(decision.action, "TUNE")
        self.assertEqual(decision.candidate.callsign, target.callsign)
        self.assertEqual(self.app_state.rig.get_frequency(), target.freq_hz)
        self.assertEqual(self.app_state.rig.get_mode(), target.mode)
        self.assertIsNotNone(self.app_state.current_rig_state)
        self.assertEqual(self.app_state.current_rig_state.callsign, target.callsign)
        # Bearing/vzdálenost/země musí být na rig live k dispozici stejně
        # jako u kandidáta, ne jen v seznamu kandidátů.
        self.assertEqual(self.app_state.current_rig_state.country, target.country)
        self.assertEqual(self.app_state.current_rig_state.bearing_deg, target.bearing_deg)
        self.assertEqual(self.app_state.current_rig_state.distance_km, target.distance_km)
        self.assertIs(self.app_state.last_decision, decision)
        self.assertIn("NALADIT", decision.reason)

        history = self.app_state.db.autotune_history()
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["callsign"], target.callsign)

    def test_manual_tune_rejects_candidate_not_in_current_list(self):
        self.app_state.refresh_candidates()

        decision = self.app_state.manual_tune("NOSUCH1", 99_999_999, "SSB")

        self.assertEqual(decision.action, "NONE")
        self.assertIsNone(decision.candidate)
        self.assertIsNone(self.app_state.current_rig_state)
        self.assertEqual(self.app_state.rig.set_frequency_calls, [])
        self.assertEqual(self.app_state.rig.set_mode_calls, [])

    def test_manual_tune_disables_autotune_and_enables_hold(self):
        """BUG P5/P4: po ručním NALADIT se AUTO TUNE musí vypnout a HOLD
        zapnout, bez ohledu na to, v jakém stavu byly předtím."""
        self.app_state.autotune_engine.cfg.enabled = True
        self.app_state.autotune_engine.cfg.hold = False
        candidates = self.app_state.refresh_candidates()
        target = candidates[0]

        self.app_state.manual_tune(target.callsign, target.freq_hz, target.mode)

        self.assertFalse(self.app_state.autotune_engine.cfg.enabled)
        self.assertTrue(self.app_state.autotune_engine.cfg.hold)
        # config.autotune a autotune_engine.cfg musí být tentýž objekt --
        # jinak by GUI (které čte přes app_state.config) vidělo jiný stav
        # než AutoTuneEngine, který podle cfg skutečně rozhoduje.
        self.assertIs(self.app_state.config.autotune, self.app_state.autotune_engine.cfg)

    def test_manual_tune_then_reenabling_autotune_clears_hold_and_works_again(self):
        """Po ručním NALADIT (AUTO TUNE vypnuté, HOLD zapnuté) musí jít
        AUTO TUNE later znovu ručně zapnout a musí zase normálně fungovat
        (mutual exclusivity vynucená v POST /api/autotune -- viz
        test_web_api.py -- vypne HOLD, jakmile se zapne AUTO TUNE)."""
        candidates = self.app_state.refresh_candidates()
        target = candidates[0]
        self.app_state.manual_tune(target.callsign, target.freq_hz, target.mode)
        self.assertTrue(self.app_state.autotune_engine.cfg.hold)

        # Simuluje POST /api/autotune {"enabled": true} -- stejná
        # vzájemná výlučnost, jakou vynucuje web/server.py.
        self.app_state.autotune_engine.cfg.enabled = True
        self.app_state.autotune_engine.cfg.hold = False

        decision = self.app_state.run_autotune_cycle()
        self.assertNotEqual(decision.action, "ERROR")

    def test_manual_tune_then_hold_never_auto_resumes_autotune_without_operator_action(self):
        """Regrese pro opravený bug "Station Agent se po ručním naladění
        nebo po zapnutí HOLD časem sám vrátí do AUTO TUNE": po ručním
        NALADIT (HOLD zapnuté, AUTO TUNE vypnuté) musí HOLD zůstat aktivní
        i dlouho po uplynutí min_hold_seconds -- polling cyklus (viz
        PollingLoop) ho nesmí sám uvolnit, operátor ho musí uvolnit
        výslovně (POST /api/autotune)."""
        candidates = self.app_state.refresh_candidates()
        target = candidates[0]
        self.app_state.autotune_engine.cfg.min_hold_seconds = 5.0

        self.app_state.manual_tune(target.callsign, target.freq_hz, target.mode)
        self.assertFalse(self.app_state.autotune_engine.cfg.enabled)
        self.assertTrue(self.app_state.autotune_engine.cfg.hold)

        tuned_at = self.app_state.current_rig_state.tuned_at
        decision = self.app_state.run_autotune_cycle(now=tuned_at + 3600.0)

        self.assertFalse(self.app_state.autotune_engine.cfg.enabled)
        self.assertTrue(self.app_state.autotune_engine.cfg.hold)
        self.assertEqual(decision.reason, "AUTO TUNE je vypnuté")

    def test_manual_tune_does_not_toggle_autotune_when_candidate_rejected(self):
        self.app_state.refresh_candidates()
        self.app_state.autotune_engine.cfg.enabled = True
        self.app_state.autotune_engine.cfg.hold = False

        self.app_state.manual_tune("NOSUCH1", 99_999_999, "SSB")

        self.assertTrue(self.app_state.autotune_engine.cfg.enabled)
        self.assertFalse(self.app_state.autotune_engine.cfg.hold)

    def test_manual_tune_rejects_stale_selection_after_candidate_list_changed(self):
        """Reprodukuje reálný scénář: operátor vybere kandidáta v GUI, mezitím
        se seznam obnoví (spot expiroval / filtr se změnil) a kandidát zmizí
        -- NALADIT nesmí přeladit na neexistujícího kandidáta jen podle
        čísel zapamatovaných v prohlížeči."""
        candidates = self.app_state.refresh_candidates()
        target = candidates[0]
        self.app_state.latest_candidates = [c for c in candidates if c.callsign != target.callsign]

        decision = self.app_state.manual_tune(target.callsign, target.freq_hz, target.mode)

        self.assertEqual(decision.action, "NONE")
        self.assertEqual(self.app_state.rig.set_frequency_calls, [])

    def test_manual_tune_reports_no_countdown_while_hold_active(self):
        """Regrese pro odpočet po ručním NALADIT: AUTO TUNE se vypne
        (autotune_remaining_seconds musí být None, viz
        _autotune_remaining_seconds ve web/server.py) a HOLD se zapne.
        HOLD blokuje přeladění bez časového limitu, takže
        hold_remaining_seconds zůstává None i po ručním NALADIT -- API
        klíč je zachovaný jen kvůli starším klientům (viz
        test_web_api.test_status_countdown_runs_only_during_autotune)."""
        candidates = self.app_state.refresh_candidates()
        target = candidates[0]
        self.app_state.autotune_engine.cfg.min_hold_seconds = 120.0

        self.app_state.manual_tune(target.callsign, target.freq_hz, target.mode)

        self.assertFalse(self.app_state.autotune_engine.cfg.enabled)
        self.assertTrue(self.app_state.autotune_engine.cfg.hold)
        self.assertIsNotNone(self.app_state.current_rig_state)
        self.assertEqual(self.app_state.current_rig_state.callsign, target.callsign)

        status = server_module._build_status(self.app_state)
        self.assertIsNone(status["autotune"]["autotune_remaining_seconds"])
        self.assertIsNone(status["autotune"]["hold_remaining_seconds"])


class ManualTuneApiTests(unittest.TestCase):
    """Backend/API regrese pro POST /api/tune."""

    @classmethod
    def setUpClass(cls):
        cls.app_state = build_test_app_state()
        cls.server = create_server(cls.app_state)
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
            return resp.status, json.loads(resp.read())

    def _post_json(self, path: str, payload: dict):
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}{path}", data=data, headers={"Content-Type": "application/json"}, method="POST"
        )
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                return resp.status, json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read())

    def test_post_tune_valid_candidate_tunes_rig_and_reports_status(self):
        _, candidates_data = self._get("/api/candidates")
        target = candidates_data["candidates"][0]

        status, data = self._post_json(
            "/api/tune",
            {"callsign": target["callsign"], "freq_hz": target["freq_hz"], "mode": target["mode"]},
        )

        self.assertEqual(status, 200)
        self.assertEqual(data["rig"]["callsign"], target["callsign"])
        self.assertEqual(data["rig"]["freq_hz"], target["freq_hz"])
        self.assertEqual(data["rig"]["mode"], target["mode"])
        self.assertEqual(data["last_decision"]["action"], "TUNE")
        self.assertEqual(data["last_decision"]["candidate_callsign"], target["callsign"])

    def test_post_tune_missing_fields_returns_400(self):
        status, data = self._post_json("/api/tune", {"callsign": "OK1ABC"})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_post_tune_empty_payload_returns_400(self):
        status, data = self._post_json("/api/tune", {})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_post_tune_unknown_candidate_returns_none_without_moving_rig(self):
        _, status_before = self._get("/api/status")

        status, data = self._post_json(
            "/api/tune", {"callsign": "NOSUCH1", "freq_hz": 1_234_000, "mode": "SSB"}
        )

        self.assertEqual(status, 200)
        self.assertEqual(data["last_decision"]["action"], "NONE")
        self.assertEqual(data["rig"], status_before["rig"])

    def test_get_tune_endpoint_not_allowed(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self._get("/api/tune")
        self.assertEqual(ctx.exception.code, 404)

    def test_post_tune_response_reports_autotune_disabled_and_hold_enabled(self):
        """BUG P4/P5 na úrovni API: odpověď /api/tune (kterou GUI použije
        k synchronizaci checkboxů, viz app.js renderAutotuneState) musí
        hned reportovat enabled=false/hold=true, ne starý stav."""
        self._post_json("/api/autotune", {"enabled": True, "hold": False})

        _, candidates_data = self._get("/api/candidates")
        target = candidates_data["candidates"][0]
        status, data = self._post_json(
            "/api/tune",
            {"callsign": target["callsign"], "freq_hz": target["freq_hz"], "mode": target["mode"]},
        )

        self.assertEqual(status, 200)
        self.assertFalse(data["autotune"]["enabled"])
        self.assertTrue(data["autotune"]["hold"])
        self.assertIsNone(data["autotune"]["autotune_remaining_seconds"])

    def test_post_tune_response_reports_no_countdown_when_hold_active(self):
        """Související regrese: /api/tune po NALADIT nesmí reportovat ani
        autotune_remaining_seconds (AUTO TUNE je vypnuté), ani
        hold_remaining_seconds (HOLD blokuje bez časového limitu)."""
        self._post_json("/api/autotune", {"enabled": True, "hold": False, "min_hold_seconds": 90.0})

        _, candidates_data = self._get("/api/candidates")
        target = candidates_data["candidates"][0]
        status, data = self._post_json(
            "/api/tune",
            {"callsign": target["callsign"], "freq_hz": target["freq_hz"], "mode": target["mode"]},
        )

        self.assertEqual(status, 200)
        self.assertFalse(data["autotune"]["enabled"])
        self.assertTrue(data["autotune"]["hold"])
        self.assertIsNone(data["autotune"]["autotune_remaining_seconds"])
        self.assertIsNone(data["autotune"]["hold_remaining_seconds"])


if __name__ == "__main__":
    unittest.main()
