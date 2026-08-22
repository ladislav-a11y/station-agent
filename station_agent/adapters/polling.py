"""Odděluje frekvenci dotazování externích zdrojů (PSKReporter, ...) od
frekvence obnovování GUI.

GUI (``/api/candidates``, ``/api/status``) se může dotazovat backendu
klidně každých pár sekund -- ``PolledSource`` ale zaručuje, že se přes
vlastní ``fetch()`` skutečně sáhne na síť nejvýš jednou za nakonfigurovaný
``interval_seconds``. Mezi tím vrací naposledy úspěšně stažená data (cache),
takže GUI má vždy co zobrazit, i když právě neproběhl nový fetch.

Pokud zdroj odpoví HTTP 429 (``RateLimitedError``), přepne se do stavu
"backoff": žádný další pokus se neprovede dřív než po ``Retry-After``
(pokud ho server poslal) nebo po exponenciálně rostoucím intervalu
odvozeném z počtu po sobě jdoucích 429 odpovědí (viz ``_record_rate_limit``).
"""

from __future__ import annotations

import logging
import time

from station_agent.adapters.base import RateLimitedError, SourceNotReadyError, SpotSource
from station_agent.models import Spot

logger = logging.getLogger(__name__)

DEFAULT_BACKOFF_MAX_SECONDS = 1800.0


class PolledSource:
    """Obaluje jeden ``SpotSource`` a řídí, jak často se na něj smí sáhnout."""

    def __init__(
        self,
        source: SpotSource,
        interval_seconds: float = 60.0,
        backoff_max_seconds: float = DEFAULT_BACKOFF_MAX_SECONDS,
    ):
        self.source = source
        self.interval_seconds = max(interval_seconds, 0.0)
        self.backoff_max_seconds = max(backoff_max_seconds, self.interval_seconds)
        self.last_attempt_ts: float | None = None
        self.last_success_ts: float | None = None
        self.cached_spots: list[Spot] = []
        self.last_error: str | None = None
        self.status: str = "pending"  # pending | ok | error | backoff
        self.backoff_until: float | None = None
        self.consecutive_rate_limits: int = 0

    @property
    def name(self) -> str:
        return self.source.name

    def poll(self, now: float | None = None) -> tuple[list[Spot], list[Spot]]:
        """Vrátí ``(spots_pro_kandidáty, čerstvě_stažené_spoty)``.

        První prvek jsou data, se kterými má pracovat aggregator/GUI --
        buď čerstvě stažená, nebo (pokud se v tomto cyklu nefetchovalo
        kvůli throttlingu/backoffu) naposledy úspěšně stažená cache. Druhý
        prvek je neprázdný pouze tehdy, když v tomto volání skutečně došlo
        k novému úspěšnému fetchi -- to je signál pro volajícího, aby tyto
        spoty (a jen tyto) zapsal do DB, místo aby při každém pollu znovu
        vkládal tytéž staré řádky.
        """
        now = time.time() if now is None else now

        if self.backoff_until is not None and now < self.backoff_until:
            return self.cached_spots, []
        if self.last_attempt_ts is not None and now - self.last_attempt_ts < self.interval_seconds:
            return self.cached_spots, []

        self.last_attempt_ts = now
        try:
            spots = self.source.fetch()
        except (NotImplementedError, SourceNotReadyError) as exc:
            self.status = "pending"
            self.last_error = str(exc)
            return self.cached_spots, []
        except RateLimitedError as exc:
            self._record_rate_limit(now, exc)
            return self.cached_spots, []
        except Exception as exc:  # síťová/parse chyba -- viz aggregator.poll_once
            self.consecutive_rate_limits = 0
            self.backoff_until = None
            self.status = "error"
            self.last_error = str(exc)
            logger.warning("Zdroj %s selhal při fetch(): %s", self.name, exc)
            return self.cached_spots, []
        else:
            self.consecutive_rate_limits = 0
            self.backoff_until = None
            self.status = "ok"
            self.last_error = None
            self.last_success_ts = now
            self.cached_spots = spots
            return spots, spots

    def _record_rate_limit(self, now: float, exc: RateLimitedError) -> None:
        self.consecutive_rate_limits += 1
        if exc.retry_after_seconds is not None:
            backoff = max(exc.retry_after_seconds, self.interval_seconds)
        else:
            backoff = self.interval_seconds * (2 ** (self.consecutive_rate_limits - 1))
        backoff = min(backoff, self.backoff_max_seconds)
        self.backoff_until = now + backoff
        self.status = "backoff"
        self.last_error = f"{exc} (backoff {backoff:.0f}s)"
        logger.warning(
            "Zdroj %s vrátil HTTP 429, backoff na %.0f s (pokus č. %d)",
            self.name,
            backoff,
            self.consecutive_rate_limits,
        )

    def status_dict(self, now: float | None = None) -> dict:
        now = time.time() if now is None else now
        backoff_remaining = None
        if self.backoff_until is not None and self.backoff_until > now:
            backoff_remaining = round(self.backoff_until - now, 1)
        age_seconds = None
        if self.last_success_ts is not None:
            age_seconds = round(max(0.0, now - self.last_success_ts), 1)
        return {
            "name": self.name,
            "status": self.status,
            "last_error": self.last_error,
            "last_success_age_seconds": age_seconds,
            "backoff_remaining_seconds": backoff_remaining,
            "cached_spot_count": len(self.cached_spots),
        }
