"""Slučuje spoty z více adaptérů do kandidátů (Candidate) se scoringem.

Zdroje, které jsou zatím PENDING (viz adapters/base.py), při pollu prostě
nic nevrátí (NotImplementedError se odchytí a zaloguje) -- aggregator tak
funguje i s konfigurací, kde jsou živé adaptéry nastavené, ale zatím
nedokončené.
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict

from station_agent.adapters.base import SpotSource
from station_agent.bearing import bearing_and_distance
from station_agent.config import ScoringConfig
from station_agent.db import Database
from station_agent.dxcc import callsign_to_dxcc
from station_agent.models import Candidate, Spot
from station_agent.scoring import score_candidate

logger = logging.getLogger(__name__)


def group_spots_into_candidates(spots: list[Spot]) -> list[Candidate]:
    """Seskupí spoty stejné stanice+pásma+módu do jednoho Candidate."""
    groups: dict[tuple[str, str, str], list[Spot]] = defaultdict(list)
    for spot in spots:
        groups[(spot.callsign, spot.band, spot.mode)].append(spot)

    candidates = []
    for (callsign, band, mode), group in groups.items():
        group.sort(key=lambda s: s.timestamp)
        latest = group[-1]
        snr_values = [s.snr_db for s in group if s.snr_db is not None]
        candidates.append(
            Candidate(
                callsign=callsign,
                freq_hz=latest.freq_hz,
                mode=mode,
                band=band,
                first_seen=group[0].timestamp,
                last_seen=latest.timestamp,
                confirming_sources={s.source for s in group},
                best_snr_db=max(snr_values) if snr_values else None,
                comments=[s.comment for s in group if s.comment],
            )
        )
    return candidates


def attach_dxcc_and_bearing(
    candidates: list[Candidate], qth_latlon: tuple[float, float] | None
) -> None:
    """Doplní DXCC entitu a (pokud je známé QTH) bearing/vzdálenost -- in place."""
    for candidate in candidates:
        entity = callsign_to_dxcc(candidate.callsign)
        candidate.dxcc = entity
        if entity is not None and qth_latlon is not None:
            bearing, distance = bearing_and_distance(
                qth_latlon[0], qth_latlon[1], entity.latitude, entity.longitude
            )
            candidate.bearing_deg = bearing
            candidate.distance_km = distance


def attach_scores(
    candidates: list[Candidate], scoring_cfg: ScoringConfig, db: Database, now: float | None = None
) -> None:
    """Spočítá a doplní ScoreResult pro každého kandidáta -- in place."""

    def is_needed(candidate: Candidate) -> bool:
        if candidate.dxcc is None:
            return True  # neznámá entita -> raději upozornit, ať operátor ověří
        return not db.is_worked(candidate.dxcc.name)

    for candidate in candidates:
        candidate.score = score_candidate(candidate, scoring_cfg, is_needed_dxcc=is_needed, now=now)


class Aggregator:
    """Drátuje dohromady zdroje spotů, DB a scoring do seznamu kandidátů."""

    def __init__(
        self,
        sources: list[SpotSource],
        db: Database,
        scoring_cfg: ScoringConfig,
        qth_latlon: tuple[float, float] | None = None,
    ):
        self.sources = sources
        self.db = db
        self.scoring_cfg = scoring_cfg
        self.qth_latlon = qth_latlon

    def poll_once(self) -> list[Spot]:
        """Vytáhne spoty ze všech zdrojů, uloží je do DB, vrátí souhrn."""
        all_spots: list[Spot] = []
        for source in self.sources:
            try:
                spots = source.fetch()
            except NotImplementedError as exc:
                logger.info("Zdroj %s je pending, přeskočeno: %s", source.name, exc)
                continue
            except Exception:
                logger.exception("Zdroj %s selhal při fetch()", source.name)
                continue
            for spot in spots:
                self.db.insert_spot(spot)
            all_spots.extend(spots)
        return all_spots

    def build_candidates(
        self,
        spots: list[Spot] | None = None,
        *,
        allowed_bands: set[str] | None = None,
        allowed_modes: set[str] | None = None,
        now: float | None = None,
    ) -> list[Candidate]:
        now = time.time() if now is None else now
        if spots is None:
            spots = self.db.recent_spots(self.scoring_cfg.spot_max_age_minutes * 60, now=now)

        if allowed_bands is not None:
            spots = [s for s in spots if s.band in allowed_bands]
        if allowed_modes is not None:
            spots = [s for s in spots if s.mode in allowed_modes]

        candidates = group_spots_into_candidates(spots)
        attach_dxcc_and_bearing(candidates, self.qth_latlon)
        attach_scores(candidates, self.scoring_cfg, self.db, now=now)
        candidates.sort(key=lambda c: c.score.total if c.score else 0, reverse=True)
        return candidates
