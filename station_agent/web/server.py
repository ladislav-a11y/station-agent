"""Webové GUI -- HTTP server VÝHRADNĚ na localhost.

Bezpečnost je vynucená v kódu (ne jen v configu, viz AGENTS.md pravidlo 5):
``create_server`` odmítne cokoli jiného než loopback adresu, ať už je
v config.yaml cokoliv.
"""

from __future__ import annotations

import json
import logging
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from station_agent.app_state import AppState
from station_agent.web.serialization import candidate_to_dict, decision_to_dict, rig_state_to_dict

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"
LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}

_STATIC_CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
}


def _build_status(app_state: AppState) -> dict:
    cfg = app_state.config
    with app_state.lock:
        return {
            "rig": rig_state_to_dict(app_state.current_rig_state),
            "autotune": {
                "enabled": cfg.autotune.enabled,
                "hold": cfg.autotune.hold,
                "min_hold_seconds": cfg.autotune.min_hold_seconds,
                "min_score_delta": cfg.autotune.min_score_delta,
            },
            "min_score": cfg.scoring.min_score,
            "bands": cfg.bands,
            "modes": cfg.modes,
            "rig_mode": cfg.rig.mode,
            "last_decision": decision_to_dict(app_state.last_decision),
        }


def _make_handler(app_state: AppState):
    class Handler(BaseHTTPRequestHandler):
        server_version = "StationAgent/0.1"

        def log_message(self, fmt, *args):  # quieter default logging
            logger.debug("%s - %s", self.address_string(), fmt % args)

        def _send_json(self, obj, status: int = 200) -> None:
            body = json.dumps(obj).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_static(self, rel_path: str) -> None:
            target = (STATIC_DIR / rel_path).resolve()
            if STATIC_DIR.resolve() not in target.parents and target != STATIC_DIR.resolve():
                self.send_error(404)
                return
            if not target.is_file():
                self.send_error(404)
                return
            content_type = _STATIC_CONTENT_TYPES.get(target.suffix, "application/octet-stream")
            body = target.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802 (stdlib naming)
            path = urlparse(self.path).path
            if path == "/":
                self._send_static("index.html")
            elif path in ("/app.js", "/style.css"):
                self._send_static(path.lstrip("/"))
            elif path == "/api/candidates":
                candidates = app_state.refresh_candidates()
                self._send_json(
                    {"candidates": [candidate_to_dict(c) for c in candidates]}
                )
            elif path == "/api/status":
                self._send_json(_build_status(app_state))
            elif path == "/api/autotune/history":
                with app_state.lock:
                    rows = app_state.db.autotune_history()
                self._send_json(
                    {
                        "history": [
                            {
                                "ts": row["ts"],
                                "callsign": row["callsign"],
                                "freq_hz": row["freq_hz"],
                                "mode": row["mode"],
                                "score": row["score"],
                                "reason": row["reason"],
                            }
                            for row in rows
                        ]
                    }
                )
            else:
                self.send_error(404)

        def do_POST(self) -> None:  # noqa: N802
            path = urlparse(self.path).path
            if path != "/api/autotune":
                self.send_error(404)
                return
            length = int(self.headers.get("Content-Length", "0") or "0")
            raw = self.rfile.read(length) if length else b"{}"
            try:
                payload = json.loads(raw or b"{}")
            except json.JSONDecodeError:
                self._send_json({"error": "invalid JSON"}, status=400)
                return

            with app_state.lock:
                cfg = app_state.autotune_engine.cfg
                if "enabled" in payload:
                    cfg.enabled = bool(payload["enabled"])
                if "hold" in payload:
                    cfg.hold = bool(payload["hold"])
                if "min_hold_seconds" in payload:
                    cfg.min_hold_seconds = float(payload["min_hold_seconds"])
                if "min_score_delta" in payload:
                    cfg.min_score_delta = float(payload["min_score_delta"])
                if "min_score" in payload:
                    app_state.autotune_engine.min_score = int(payload["min_score"])
                    app_state.config.scoring.min_score = int(payload["min_score"])

            self._send_json(_build_status(app_state))

    return Handler


def create_server(app_state: AppState) -> ThreadingHTTPServer:
    host = app_state.config.web.host
    if host not in LOOPBACK_HOSTS:
        raise ValueError(
            f"Web GUI smí běžet pouze na localhost, ne na {host!r} -- "
            "toto omezení je vynucené v kódu bez ohledu na config.yaml."
        )
    handler_cls = _make_handler(app_state)
    return ThreadingHTTPServer((host, app_state.config.web.port), handler_cls)
