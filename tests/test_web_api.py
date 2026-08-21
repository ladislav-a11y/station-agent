"""Integrační test webového GUI/API -- ověřuje i to, že server běží
výhradně na loopback adrese (viz AGENTS.md pravidlo 5)."""

from __future__ import annotations

import json
import threading
import unittest
import urllib.error
import urllib.request

from station_agent.adapters.mock import MockAdapter
from station_agent.aggregator import Aggregator
from station_agent.app_state import AppState
from station_agent.config import AppConfig, WebConfig
from station_agent.db import Database
from station_agent.rig.mock_rig import MockRig
from station_agent.scoring import DEFAULT_WEIGHTS, ScoringConfig
from station_agent.web.server import create_server


def build_test_app_state(port: int = 0) -> AppState:
    config = AppConfig()
    config.web = WebConfig(host="127.0.0.1", port=port)
    db = Database(":memory:")
    rig = MockRig()
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

    def test_unknown_path_is_404(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self._get("/does-not-exist")
        self.assertEqual(ctx.exception.code, 404)

    def test_no_ptt_endpoint_exists(self):
        for path in ("/api/ptt", "/api/tx", "/api/transmit", "/ptt"):
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                self._get(path)
            self.assertEqual(ctx.exception.code, 404)


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
