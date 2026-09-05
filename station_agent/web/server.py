"""Webové GUI -- HTTP server VÝHRADNĚ na localhost.

Bezpečnost je vynucená v kódu (ne jen v configu, viz AGENTS.md pravidlo 5):
``create_server`` odmítne cokoli jiného než loopback adresu, ať už je
v config.yaml cokoliv.
"""

from __future__ import annotations

import json
import logging
import math
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from station_agent.app_state import AppState, PollingLoop
from station_agent.bandplan import SUPPORTED_BANDS
from station_agent.modes import SUPPORTED_MODES
from station_agent.web.serialization import candidate_to_dict, decision_to_dict, rig_state_to_dict

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"
LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}

_STATIC_CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
}

# Klient (prohlížeč) může kdykoli zavřít spojení uprostřed zápisu odpovědi
# (zavřená karta, refresh, ...). Na Windows se to hlásí jako WinError 10053
# ("Software caused connection abort"), který Python mapuje na
# ConnectionAbortedError; na jiných platformách typicky BrokenPipeError/
# ConnectionResetError. Jde o benigní, běžné odpojení klienta -- nesmí
# skončit dlouhým tracebackem v konzoli (viz _is_benign_disconnect níže).
_BENIGN_DISCONNECT_ERRORS = (ConnectionAbortedError, BrokenPipeError, ConnectionResetError)
_BENIGN_DISCONNECT_WINERRORS = {10053, 10054, 10038}


def _is_benign_disconnect(exc: BaseException) -> bool:
    if isinstance(exc, _BENIGN_DISCONNECT_ERRORS):
        return True
    return isinstance(exc, OSError) and getattr(exc, "winerror", None) in _BENIGN_DISCONNECT_WINERRORS


def _autotune_remaining_seconds(app_state: AppState) -> float | None:
    """Kolik sekund AUTO TUNE ještě musí držet aktuální stanici.

    ``min_hold_seconds`` je prodleva mezi automatickými přeladěními, nikoli
    časový limit režimu HOLD. HOLD ladění blokuje bez odpočtu.
    """
    cfg = app_state.config.autotune
    state = app_state.current_rig_state
    if not cfg.enabled or cfg.hold or state is None:
        return None
    return round(max(0.0, cfg.min_hold_seconds - (time.time() - state.tuned_at)), 1)


def _build_status(app_state: AppState) -> dict:
    cfg = app_state.config
    with app_state.lock:
        propagation = app_state.propagation.context if app_state.propagation else None
        return {
            "rig": rig_state_to_dict(app_state.current_rig_state),
            "autotune": {
                "enabled": cfg.autotune.enabled,
                "hold": cfg.autotune.hold,
                # Zachování API klíče pro starší klienty; HOLD nemá časový limit.
                "hold_remaining_seconds": None,
                "autotune_remaining_seconds": _autotune_remaining_seconds(app_state),
                "min_hold_seconds": cfg.autotune.min_hold_seconds,
                "min_score_delta": cfg.autotune.min_score_delta,
            },
            "min_score": cfg.scoring.min_score,
            "bands": cfg.bands,
            "modes": cfg.modes,
            "rig_mode": cfg.rig.mode,
            "propagation": {
                "kp": propagation.kp if propagation else None,
                "solar_flux": propagation.solar_flux if propagation else None,
                "observed_at": propagation.observed_at if propagation else None,
                "source": propagation.source if propagation else None,
                "qth_locator": propagation.qth_locator if propagation else None,
                "band_quality": propagation.band_quality if propagation else {},
                "explanation": propagation.explanation if propagation else None,
            },
            "last_decision": decision_to_dict(app_state.last_decision),
            "sources": app_state.aggregator.source_status(),
            "presets": [
                {"key": key, "label": preset.label, "bands": preset.bands, "modes": preset.modes}
                for key, preset in cfg.presets.items()
            ],
        }


def _perform_shutdown(
    app_state: AppState, polling_loop: PollingLoop | None, http_server: ThreadingHTTPServer
) -> None:
    """Bezpečné ukončení vyžádané tlačítkem "Ukončit" v GUI.

    Pořadí je závazné (viz DoD): nejdřív zastavit polling a webový server,
    pak uzavřít spojení (agregátor živých zdrojů, rig) a teprve pak vyčistit
    obsah databáze -- v tomto pořadí nemůže žádný souběžný poll ani HTTP
    request zapsat do DB uprostřed čištění. Běží v samostatném vlákně (viz
    volání níže v do_POST), aby handler mohl klientovi nejdřív odeslat
    potvrzení a až pak se server sám zastavil (ThreadingHTTPServer.shutdown()
    blokuje, dokud serve_forever() ve vlákně, které ho spustilo, neskončí).
    """
    logger.info("Ukončení Station Agenta vyžádáno z GUI (tlačítko Ukončit)")
    if polling_loop is not None:
        try:
            polling_loop.stop()
        except Exception:
            logger.exception("Zastavení pollingu při ukončení selhalo")
    try:
        http_server.shutdown()
    except Exception:
        logger.exception("Zastavení web serveru při ukončení selhalo")
    with app_state.lock:
        try:
            app_state.aggregator.close()
        except Exception:
            logger.exception("Uzavření zdrojů při ukončení selhalo")
        try:
            app_state.rig.close()
        except Exception:
            logger.exception("Uzavření spojení s riggem při ukončení selhalo")
        try:
            app_state.db.clear_all_data()
        except RuntimeError:
            logger.exception("Vyčištění databáze při ukončení selhalo")
        finally:
            app_state.db.close()


def _make_handler(app_state: AppState, polling_loop: PollingLoop | None = None):
    class Handler(BaseHTTPRequestHandler):
        server_version = "StationAgent/0.1"

        def log_message(self, fmt, *args):  # quieter default logging
            logger.debug("%s - %s", self.address_string(), fmt % args)

        def _safe_send_error(self, status: int, message: str | None = None) -> None:
            try:
                self.send_error(status, message)
            except OSError as exc:
                if not _is_benign_disconnect(exc):
                    raise
                logger.debug("Klient %s se odpojil při zápisu chybové odpovědi: %s", self.address_string(), exc)
                self.close_connection = True

        def _send_json(self, obj, status: int = 200) -> None:
            body = json.dumps(obj).encode("utf-8")
            try:
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except OSError as exc:
                if not _is_benign_disconnect(exc):
                    raise
                logger.debug("Klient %s se odpojil při zápisu odpovědi: %s", self.address_string(), exc)
                self.close_connection = True

        def _send_static(self, rel_path: str) -> None:
            target = (STATIC_DIR / rel_path).resolve()
            if STATIC_DIR.resolve() not in target.parents and target != STATIC_DIR.resolve():
                self._safe_send_error(404)
                return
            if not target.is_file():
                self._safe_send_error(404)
                return
            content_type = _STATIC_CONTENT_TYPES.get(target.suffix, "application/octet-stream")
            body = target.read_bytes()
            try:
                self.send_response(200)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except OSError as exc:
                if not _is_benign_disconnect(exc):
                    raise
                logger.debug("Klient %s se odpojil při zápisu odpovědi: %s", self.address_string(), exc)
                self.close_connection = True

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
            elif path == "/api/notifications":
                with app_state.lock:
                    events = list(app_state.band_opening_tracker.events)
                self._send_json(
                    {
                        "band_openings": [
                            {
                                "ts": event.ts, "band": event.band,
                                "station_count": event.station_count,
                                "station_count_change": event.station_count_change,
                                "reason": event.reason,
                            }
                            for event in reversed(events)
                        ]
                    }
                )
            elif path == "/api/qso/history":
                with app_state.lock:
                    rows = app_state.db.recent_qsos()
                self._send_json(
                    {"history": [
                        {
                            "ts": row["ts"], "callsign": row["callsign"],
                            "freq_hz": row["freq_hz"], "mode": row["mode"],
                            "band": row["band"], "bearing_deg": row["bearing_deg"],
                            "note": row["note"],
                        }
                        for row in rows
                    ]}
                )
            else:
                self._safe_send_error(404)

        def do_POST(self) -> None:  # noqa: N802
            path = urlparse(self.path).path
            if path not in (
                "/api/autotune", "/api/filters", "/api/tune", "/api/qso/history", "/api/shutdown",
            ):
                self._safe_send_error(404)
                return
            if path == "/api/shutdown":
                # Odpověď se posílá hned, ať klient dostane potvrzení dřív,
                # než se server sám zastaví -- viz _perform_shutdown výše.
                self._send_json({"ok": True, "message": "Station Agent se ukončuje"})
                threading.Thread(
                    target=_perform_shutdown,
                    args=(app_state, polling_loop, self.server),
                    name="station-agent-shutdown",
                    daemon=True,
                ).start()
                return
            length = int(self.headers.get("Content-Length", "0") or "0")
            raw = self.rfile.read(length) if length else b"{}"
            try:
                payload = json.loads(raw or b"{}")
            except json.JSONDecodeError:
                self._send_json({"error": "invalid JSON"}, status=400)
                return

            if path == "/api/qso/history":
                callsign = payload.get("callsign")
                freq_hz = payload.get("freq_hz")
                mode = payload.get("mode")
                band = payload.get("band")
                note = payload.get("note", "")
                valid = (
                    isinstance(callsign, str) and bool(callsign.strip())
                    and isinstance(freq_hz, (int, float)) and not isinstance(freq_hz, bool)
                    and math.isfinite(freq_hz) and freq_hz > 0
                    and isinstance(mode, str) and mode in SUPPORTED_MODES
                    and isinstance(band, str) and band in SUPPORTED_BANDS
                    and isinstance(note, str) and len(note) <= 500
                )
                if not valid:
                    self._send_json({"error": "neplatný QSO záznam"}, status=400)
                    return
                with app_state.lock:
                    candidate = next(
                        (c for c in app_state.latest_candidates
                         if c.callsign == callsign.strip().upper()
                         and c.freq_hz == int(freq_hz) and c.mode == mode and c.band == band),
                        None,
                    )
                    if candidate is None:
                        self._send_json({"error": "QSO musí odpovídat aktuálnímu kandidátovi"}, status=409)
                        return
                    app_state.db.log_qso(
                        callsign.strip().upper(), int(freq_hz), mode.strip(), band,
                        candidate.bearing_deg, note.strip(),
                    )
                self._send_json({"ok": True}, status=201)
                return

            if path == "/api/tune":
                callsign = payload.get("callsign")
                freq_hz = payload.get("freq_hz")
                mode = payload.get("mode")
                valid = (
                    isinstance(callsign, str)
                    and callsign.strip() != ""
                    and isinstance(freq_hz, (int, float))
                    and not isinstance(freq_hz, bool)
                    and freq_hz > 0
                    and isinstance(mode, str)
                    and mode.strip() != ""
                )
                if not valid:
                    self._send_json(
                        {"error": "callsign, freq_hz a mode jsou povinné a musí popisovat platného kandidáta"},
                        status=400,
                    )
                    return
                try:
                    app_state.manual_tune(callsign, int(freq_hz), mode)
                except Exception as exc:  # rigctld/hardware chyba
                    logger.exception("Ruční naladění (NALADIT) selhalo")
                    body = _build_status(app_state)
                    body["error"] = str(exc)
                    self._send_json(body, status=502)
                    return
                self._send_json(_build_status(app_state))
                return

            if path == "/api/autotune":
                with app_state.lock:
                    cfg = app_state.autotune_engine.cfg
                    # AUTO TUNE a HOLD jsou vzájemně výlučné (viz DoD) --
                    # zapnutí jednoho vždy vypne druhý, ať přijdou v payloadu
                    # v libovolném pořadí/kombinaci. Zpracujeme "enabled"
                    # nejdřív, aby explicitní "hold": true v témže payloadu
                    # (typicky odeslaném z GUI formuláře) mělo poslední
                    # slovo, pokud by GUI omylem poslalo obě jako true.
                    if "enabled" in payload:
                        cfg.enabled = bool(payload["enabled"])
                        if cfg.enabled:
                            cfg.hold = False
                    if "hold" in payload:
                        cfg.hold = bool(payload["hold"])
                        if cfg.hold:
                            cfg.enabled = False
                    if "min_hold_seconds" in payload:
                        cfg.min_hold_seconds = float(payload["min_hold_seconds"])
                    if "min_score_delta" in payload:
                        cfg.min_score_delta = float(payload["min_score_delta"])
                    if "min_score" in payload:
                        app_state.autotune_engine.min_score = int(payload["min_score"])
                        app_state.config.scoring.min_score = int(payload["min_score"])
            else:  # /api/filters -- GUI checkboxy pro povolené módy/pásma
                with app_state.lock:
                    if "bands" in payload:
                        bands = [b for b in payload["bands"] if b in SUPPORTED_BANDS]
                        app_state.config.bands = bands
                    if "modes" in payload:
                        modes = [m for m in payload["modes"] if m in SUPPORTED_MODES]
                        app_state.config.modes = modes
                    app_state.db.save_filter_preferences(
                        app_state.config.bands, app_state.config.modes
                    )

            self._send_json(_build_status(app_state))

    return Handler


class _QuietThreadingHTTPServer(ThreadingHTTPServer):
    """Jako ``ThreadingHTTPServer``, ale benigní odpojení klienta (zavřená
    karta v prohlížeči apod.) nezaloguje jako dlouhý traceback -- viz
    ``_is_benign_disconnect`` a AGENTS.md/dod bod o WinError 10053."""

    def handle_error(self, request, client_address) -> None:
        exc = sys.exc_info()[1]
        if exc is not None and _is_benign_disconnect(exc):
            logger.debug("Klient %s se odpojil: %s", client_address, exc)
            return
        super().handle_error(request, client_address)


def create_server(app_state: AppState, polling_loop: PollingLoop | None = None) -> ThreadingHTTPServer:
    host = app_state.config.web.host
    if host not in LOOPBACK_HOSTS:
        raise ValueError(
            f"Web GUI smí běžet pouze na localhost, ne na {host!r} -- "
            "toto omezení je vynucené v kódu bez ohledu na config.yaml."
        )
    handler_cls = _make_handler(app_state, polling_loop)
    return _QuietThreadingHTTPServer((host, app_state.config.web.port), handler_cls)
