"""Výběr jediné band-opening notifikace pro aktuální běh aplikace.

Tracker porovnává počty odlišných stanic mezi po sobě jdoucími cykly a drží
jen událost s největším kladným přírůstkem od spuštění procesu. Pásmo musí
současně dosáhnout ``cfg.min_distinct_stations``. Starší databázové události
se záměrně do maxima nezapočítávají, protože hranicí požadavku je start
aktuální instance station agenta.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from station_agent.config import NotificationsConfig


@dataclass
class BandOpeningEvent:
    band: str
    station_count: int
    station_count_change: int
    ts: float
    reason: str = ""


class BandOpeningTracker:
    """Stavový sledovač otevírání pásem -- jedna instance na běh aplikace
    (viz app_state.AppState), volá se z každého ``refresh_candidates()``
    cyklu s aktuálním ``aggregator.band_activity(candidates)``."""

    def __init__(self, cfg: NotificationsConfig, previous_events=()):
        # Parametr zůstává kvůli kompatibilitě volajících ze starší verze;
        # maximum je záměrně omezené na aktuální běh.
        del previous_events
        self.cfg = cfg
        self._last_activity: dict[str, int] = {}
        self.best_event: BandOpeningEvent | None = None

    def check(self, band_activity: dict[str, int], now: float | None = None) -> list[BandOpeningEvent]:
        """Vrátí nového vítěze, pouze pokud překonal dosavadní maximum.

        Změna je kladný rozdíl proti předchozímu pozorování téhož pásma.
        První pozorování se porovnává s nulou, protože sledování začíná se
        spuštěním procesu. ``best_event`` tak po celý běh představuje právě
        jednu band-opening notifikaci s největší zaznamenanou změnou.
        """
        if not self.cfg.enabled:
            return []
        now = time.time() if now is None else now
        events: list[BandOpeningEvent] = []

        for band, count in band_activity.items():
            change = count - self._last_activity.get(band, 0)
            is_open = count >= self.cfg.min_distinct_stations
            if is_open and change > 0:
                event = BandOpeningEvent(
                    band=band, station_count=count, ts=now,
                    station_count_change=change,
                    reason=(
                        f"aktivita na pásmu {band} vzrostla o {change} na {count} "
                        f"odlišných stanic (práh {self.cfg.min_distinct_stations})"
                    ),
                )
                if (
                    self.best_event is None
                    or event.station_count_change > self.best_event.station_count_change
                ):
                    self.best_event = event
                    events = [event]

        self._last_activity = dict(band_activity)

        return events
