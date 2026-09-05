"""Sdílený běhový stav aplikace -- drátuje config, DB, adaptéry, rig a
AUTO TUNE dohromady. Používá ho jak CLI/polling smyčka, tak web GUI.
"""

from __future__ import annotations

import logging
import threading
import time

from station_agent.aggregator import Aggregator, band_activity
from station_agent.autotune import AutoTuneEngine, TuneDecision, apply_decision
from station_agent.config import AppConfig
from station_agent.db import Database
from station_agent.models import Candidate, RigState
from station_agent.notifications import BandOpeningTracker
from station_agent.propagation import PropagationService
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
        self.propagation = PropagationService(
            config.station.qth_locator, config.propagation.refresh_seconds,
            kp_url=config.propagation.kp_url, sfi_url=config.propagation.sfi_url,
        ) if config.propagation.enabled else None
        self.autotune_engine = AutoTuneEngine(config.autotune, config.scoring.min_score)
        self.current_rig_state: RigState | None = None
        self.latest_candidates: list[Candidate] = []
        self.last_decision: TuneDecision | None = None
        self.band_opening_tracker = BandOpeningTracker(
            config.notifications,
            db.recent_band_openings(limit=None),
        )
        self.lock = threading.RLock()

    def refresh_candidates(self, now: float | None = None) -> list[Candidate]:
        now = time.time() if now is None else now
        with self.lock:
            self.aggregator.poll_once(now=now)
            # Bez pravidelného mazání starých spotů tabulka `spots` roste bez
            # omezení -- žádný jiný kód v aplikaci staré řádky nečte
            # (candidate se staví jen z okna spot_max_age_minutes, viz
            # aggregator.build_candidates), takže je bezpečné mazat všechno
            # mimo toto okno při každém refresh cyklu. Bez tohoto volání
            # DB reálně naroste na stovky MB/miliony řádků během dní
            # nepřetržitého provozu, což zpomalí každý poll cyklus i start
            # (refresh_candidates běží synchronně před spuštěním web
            # serveru, viz cli.py).
            self.db.purge_older_than(self.config.scoring.spot_max_age_minutes * 60, now=now)
            if self.propagation is None:
                context = None
            else:
                refresh_if_due = getattr(self.propagation, "refresh_if_due", None)
                context = (
                    refresh_if_due(now)
                    if refresh_if_due is not None
                    else self.propagation.context
                )
            self.aggregator.propagation = context
            # Notifikace jsou vlastností živých zdrojů, ne GUI filtru.
            all_candidates = self.aggregator.build_candidates(now=now)
            candidates = [
                c for c in all_candidates
                if c.band in self.config.bands and c.mode in self.config.modes
            ]
            self.latest_candidates = candidates
            self._sync_current_score(candidates)
            if context is None:
                logger.debug("propagation snapshot: nedostupný")
            else:
                qualities = ", ".join(
                    f"{band}={quality:.3f}" for band, quality in context.band_quality.items()
                )
                logger.debug(
                    "propagation snapshot: source=%s observed_at=%.0f kp=%s sfi=%s qth=%s "
                    "model={%s} explanation=%s",
                    context.source, context.observed_at, context.kp, context.solar_flux,
                    context.qth_locator, qualities, context.explanation,
                )
            for candidate in candidates:
                logger.debug(
                    "score %s %s %.3f MHz: total=%s factors=%s propagation=%s",
                    candidate.callsign, candidate.band, candidate.freq_hz / 1_000_000,
                    candidate.score.total if candidate.score else None,
                    "; ".join(f"{r.factor}={r.points}/{r.max_points} ({r.detail})"
                               for r in (candidate.score.reasons if candidate.score else [])),
                    context,
                )
            self._check_band_openings(all_candidates, now=now)
            return candidates

    def _sync_current_score(self, candidates: list[Candidate]) -> None:
        """Skóre aktuálně naladěné stanice nesmí zůstat zamrzlé na hodnotě
        z okamžiku výběru (viz autotune.apply_decision) -- AutoTuneEngine.decide()
        ho v kroku 7 porovnává s průběžně přepočítávanými kandidáty (delta
        vs. min_score_delta), takže musí být stejně čerstvé jako u ostatních
        -- jinak by naladěná stanice mohla vypadat uměle lepší/horší, než
        ve skutečnosti je, a AUTO TUNE by se podle toho rozhodoval špatně.
        Pokud stanice mezi aktuálními kandidáty už není (spot expiroval,
        vypadl z filtrů), poslední známé skóre se zachovává beze změny.
        """
        state = self.current_rig_state
        if state is None or state.callsign is None:
            return
        match = next(
            (
                c for c in candidates
                if c.callsign == state.callsign
                and c.freq_hz == state.freq_hz
                and c.mode == state.mode
            ),
            None,
        )
        if match is not None:
            state.score = match.score.total if match.score else None

    def _check_band_openings(self, candidates: list[Candidate], now: float) -> None:
        """Zavolá BandOpeningTracker nad úplnou aktivitou zdrojů,
        jakou vidí i scoring.py _propagation_reason (viz
        aggregator.band_activity). Každou vrácenou událost uloží do DB jako
        auditní historii -- tracker může v jednom cyklu vrátit i více
        současně otevřených pásem, všechny se zaloguj."""
        activity = band_activity(candidates)
        events = self.band_opening_tracker.check(activity, now=now)
        propagation = self.propagation.context if self.propagation else None
        for event in events:
            if propagation is None:
                propagation_reason = "propagation data nejsou dostupná"
            else:
                details: list[str] = []
                if propagation.kp is not None:
                    details.append(f"Kp {propagation.kp:.1f}")
                if propagation.solar_flux is not None:
                    details.append(f"SFI {propagation.solar_flux:.1f}")
                details.append(
                    f"QTH {propagation.qth_locator.upper()}"
                    if propagation.qth_locator
                    else "QTH neznámé"
                )
                quality = propagation.band_quality.get(event.band)
                if quality is not None:
                    details.append(f"kvalita pásma {quality * 100:.0f} %")
                age_minutes = max(0.0, now - propagation.observed_at) / 60
                details.append(f"stáří dat {age_minutes:.0f} min")
                if propagation.source:
                    details.append(f"zdroj {propagation.source}")
                propagation_reason = ", ".join(details) or "propagation data nejsou dostupná"

            # Tentýž úplný důvod používá živé API/GUI i perzistentní historie.
            event.reason = f"{event.reason}; {propagation_reason}"
            self.db.log_band_opening(
                event.band, event.station_count, event.ts, event.reason
            )

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

    def manual_tune(self, callsign: str, freq_hz: int, mode: str) -> TuneDecision:
        """Ruční naladění vybraného kandidáta (tlačítko NALADIT v GUI).

        Kandidát musí přesně odpovídat (callsign, freq_hz, mode) položce
        aktuálně v ``latest_candidates`` -- to zajišťuje, že se nikdy
        nenaladí na kandidáta, který mezitím zmizel ze seznamu (např. kvůli
        expiraci spotu nebo změně filtrů), i kdyby GUI poslalo zastaralý
        výběr. Volá stejnou ``apply_decision`` cestu jako AUTO TUNE, takže
        prochází přes stejný jediný Hamlib/rigctld klient (viz AGENTS.md
        pravidlo 1) a zapisuje se do stejné historie v DB.
        """
        with self.lock:
            candidate = next(
                (
                    c
                    for c in self.latest_candidates
                    if c.callsign == callsign and c.freq_hz == freq_hz and c.mode == mode
                ),
                None,
            )
            if candidate is None:
                decision = TuneDecision(
                    "NONE",
                    None,
                    f"kandidát {callsign} ({mode}, {freq_hz} Hz) není mezi aktuálně "
                    "zobrazenými kandidáty -- vyber ho znovu ze seznamu a zkus to znovu",
                )
                self.last_decision = decision
                return decision

            decision = TuneDecision(
                "TUNE",
                candidate,
                f"ruční naladění tlačítkem NALADIT na {candidate.callsign} "
                f"({candidate.mode}, {candidate.freq_hz} Hz)",
            )
            try:
                new_state = apply_decision(self.rig, decision, self.db)
            except Exception as exc:
                self.last_decision = TuneDecision(
                    "ERROR", candidate, f"naladění na {candidate.callsign} selhalo: {exc}"
                )
                raise
            if new_state is not None:
                self.current_rig_state = new_state
                # BUG P5/P4: ruční NALADIT musí AUTO TUNE vypnout (jinak by ho
                # mohl hned zase přeladit pryč) a HOLD zapnout (chrání čerstvě
                # naladěnou stanici po min_hold_seconds -- viz odpočet
                # v /api/status a AutoTuneEngine.cfg.hold). enabled/hold jsou
                # vzájemně výlučné, viz web/server.py POST /api/autotune.
                self.autotune_engine.cfg.enabled = False
                self.autotune_engine.cfg.hold = True
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
