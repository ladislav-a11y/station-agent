"""Sdílený běhový stav aplikace -- drátuje config, DB, adaptéry, rig a
AUTO TUNE dohromady. Používá ho jak CLI/polling smyčka, tak web GUI.
"""

from __future__ import annotations

import logging
import threading
import time

from station_agent.aggregator import Aggregator
from station_agent.autotune import AutoTuneEngine, TuneDecision, apply_decision
from station_agent.config import AppConfig
from station_agent.db import Database
from station_agent.models import Candidate, RigState
from station_agent.rig.base import RigControl

logger = logging.getLogger(__name__)


class AppState:
    def __init__(
        self,
        config: AppConfig,
        db: Database,
        rig: RigControl,
        aggregator: Aggregator,
    ):
        self.config = config
        self.db = db
        self.rig = rig
        self.aggregator = aggregator
        self.autotune_engine = AutoTuneEngine(config.autotune, config.scoring.min_score)
        self.current_rig_state: RigState | None = None
        self.latest_candidates: list[Candidate] = []
        self.last_decision: TuneDecision | None = None
        self.lock = threading.RLock()

    def refresh_candidates(self, now: float | None = None) -> list[Candidate]:
        now = time.time() if now is None else now
        with self.lock:
            self.aggregator.poll_once()
            candidates = self.aggregator.build_candidates(
                allowed_bands=set(self.config.bands),
                allowed_modes=set(self.config.modes),
                now=now,
            )
            self.latest_candidates = candidates
            return candidates

    def run_autotune_cycle(self, now: float | None = None) -> TuneDecision:
        now = time.time() if now is None else now
        with self.lock:
            decision = self.autotune_engine.decide(
                self.latest_candidates,
                self.current_rig_state,
                now=now,
                allowed_bands=set(self.config.bands),
                allowed_modes=set(self.config.modes),
            )
            if decision.action == "TUNE":
                new_state = apply_decision(self.rig, decision, self.db)
                if new_state is not None:
                    self.current_rig_state = new_state
            self.last_decision = decision
            return decision

    def sync_rig_state_from_hardware(self) -> None:
        """Načte aktuální frekvenci/mód z riggu (např. při startu), aby
        AUTO TUNE znal skutečný stav i mimo vlastní historii ladění."""
        with self.lock:
            status = self.rig.get_status()
            if self.current_rig_state is None:
                self.current_rig_state = status


class PollingLoop:
    """Periodicky volá refresh_candidates() + run_autotune_cycle() na pozadí."""

    def __init__(self, app_state: AppState, interval_seconds: float = 10.0):
        self.app_state = app_state
        self.interval_seconds = interval_seconds
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                self.app_state.refresh_candidates()
                self.app_state.run_autotune_cycle()
            except Exception:
                logger.exception("Chyba v polling smyčce")
            self._stop_event.wait(self.interval_seconds)

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, name="station-agent-poll", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None
