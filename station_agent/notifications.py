"""Sledování band-opening událostí napříč celým během Station Agenta.

Tracker porovnává počty odlišných stanic mezi po sobě jdoucími cykly a
generuje jednu notifikaci pro KAŽDÉ pásmo, které právě přešlo ze zavřeného
do otevřeného stavu (``cfg.min_distinct_stations``). Dokud pásmo zůstává
nepřetržitě otevřené, žádná další notifikace nevzniká -- teprve po skutečném
uzavření (pokles pod práh, nebo úplná absence v aktuálním cyklu) a novém
otevření se pásmo může znovu ohlásit, a to až po uplynutí
``cfg.cooldown_minutes`` od poslední notifikace pro totéž pásmo. Napříč
všemi pásmy navíc platí tvrdý klouzavý strop ``cfg.max_per_hour`` za
poslední hodinu, aby souběžné otevření mnoha pásem nezaplavilo GUI.
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


def _event_band_and_ts(previous_event) -> tuple[str, float]:
    if hasattr(previous_event, "keys"):
        return previous_event["band"], previous_event["ts"]
    return previous_event.band, previous_event.ts


class BandOpeningTracker:
    """Stavový sledovač otevírání pásem -- jedna instance na běh aplikace
    (viz app_state.AppState), volá se z každého ``refresh_candidates()``
    cyklu s aktuálním ``aggregator.band_activity(candidates)``.

    ``previous_events`` (dřívější notifikace, typicky obnovené z perzistentní
    historie) se použijí k obnově cooldownu jednotlivých pásem a klouzavého
    hodinového stropu, aby restart procesu neobešel ochranu proti záplavě
    notifikací."""

    def __init__(self, cfg: NotificationsConfig, previous_events=()):
        self.cfg = cfg
        self._last_activity: dict[str, int] = {}
        self._last_fired: dict[str, float] = {}
        self._fired_ts: list[float] = []
        for previous_event in previous_events:
            band, ts = _event_band_and_ts(previous_event)
            self._last_fired[band] = max(self._last_fired.get(band, ts), ts)
            self._fired_ts.append(ts)
        # Historie všech notifikací vygenerovaných touto instancí -- GUI
        # (viz web/server.py) z ní zobrazuje všechny relevantní události,
        # ne jen tu poslední.
        self.events: list[BandOpeningEvent] = []

    def check(self, band_activity: dict[str, int], now: float | None = None) -> list[BandOpeningEvent]:
        """Vrátí všechny nově otevřené pásmo v tomto cyklu (může jich být
        i více najednou), s respektováním cooldownu na pásmo a globálního
        hodinového stropu."""
        if not self.cfg.enabled:
            return []
        now = time.time() if now is None else now
        cooldown_seconds = self.cfg.cooldown_minutes * 60
        self._fired_ts = [ts for ts in self._fired_ts if ts >= now - 3600]

        fired: list[BandOpeningEvent] = []
        for band, count in band_activity.items():
            previous_count = self._last_activity.get(band, 0)
            was_open = previous_count >= self.cfg.min_distinct_stations
            is_open = count >= self.cfg.min_distinct_stations
            self._last_activity[band] = count

            if not is_open or was_open:
                continue
            last_fired = self._last_fired.get(band)
            if last_fired is not None and (now - last_fired) < cooldown_seconds:
                continue
            if len(self._fired_ts) >= self.cfg.max_per_hour:
                continue

            change = count - previous_count
            event = BandOpeningEvent(
                band=band, station_count=count, station_count_change=change, ts=now,
                reason=(
                    f"aktivita na pásmu {band} vzrostla o {change} na {count} "
                    f"odlišných stanic (práh {self.cfg.min_distinct_stations})"
                ),
            )
            fired.append(event)
            self._last_fired[band] = now
            self._fired_ts.append(now)

        # Pásmo, které v tomto cyklu vůbec nemá aktivitu, se chová jako
        # zavřené -- jinak by po znovuobjevení nešlo rozpoznat nové otevření.
        for band in self._last_activity:
            if band not in band_activity:
                self._last_activity[band] = 0

        self.events.extend(fired)
        return fired
