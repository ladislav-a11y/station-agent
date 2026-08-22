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
from station_agent.adapters.polling import DEFAULT_BACKOFF_MAX_SECONDS, PolledSource
from station_agent.bearing import bearing_and_distance
from station_agent.config import ScoringConfig
from station_agent.db import Database
from station_agent.dxcc import callsign_to_dxcc
from station_agent.models import Candidate, Spot
from station_agent.scoring import score_candidate

logger = logging.getLogger(__name__)

# Tolerance "přibližné frekvence" při slučování spotů do jednoho kandidáta --
# různí spottery/skimmery hlásí mírně odlišnou frekvenci téže stanice
# (zaokrouhlení na klávesnici, drift VFO, přesnost skimmeru). Nad touto
# hranicí už jde o jinou skutečnou frekvenci/QSO i pro stejný
# callsign+band+mód (např. stanice se v pásmu přeladila jinam, nebo jde o
# dvě různé souběžné SSB QSO na stejném pásmu) -- viz DoD "slučovat pouze
# při shodě ... + přibližné frekvence + časového okna ...". SSB má širší
# toleranci odpovídající typické šířce hlasového kanálu (~3 kHz), CW/digi
# užší (spoty na těchto módech se čtou/měří přesněji).
SSB_FREQ_MERGE_TOLERANCE_HZ = 3_000.0
DEFAULT_FREQ_MERGE_TOLERANCE_HZ = 700.0

# Časové okno pro sloučení -- dva spoty téhož callsign+band+mód+frekvence
# dál od sebe v čase, než toto okno, se považují za oddělené pozorování
# (např. stanice byla spotnutá, zmizela z pásma, a o hodinu později se
# objevila znovu -- to má být nový kandidát, ne umělé natažení "first_seen"
# přes celou tu dobu). Nezávislé na ``scoring.spot_max_age_minutes`` (ten
# omezuje, jak staré spoty se vůbec berou v úvahu vůči "teď"; tohle omezuje
# rozestup MEZI jednotlivými spoty navzájem).
DEFAULT_MERGE_TIME_WINDOW_SECONDS = 300.0


def _freq_tolerance_for_mode(mode: str) -> float:
    return SSB_FREQ_MERGE_TOLERANCE_HZ if mode == "SSB" else DEFAULT_FREQ_MERGE_TOLERANCE_HZ


def _cluster_by_freq_and_time(
    spots: list[Spot], freq_tolerance_hz: float, time_window_seconds: float
) -> list[list[Spot]]:
    """Rozdělí spoty (už předfiltrované na stejný callsign+band+kompatibilní
    mód) do shluků podle přibližné frekvence A časového okna zároveň.

    Použije union-find nad dvojicemi spotů, které jsou si navzájem blízké
    v obou rozměrech -- díky tomu vznikne shluk i řetězením přes víc spotů
    (A blízko B blízko C, i když A a C už by samy o sobě mimo toleranci
    byly), což lépe odpovídá reálnému postupnému driftu/zaokrouhlování než
    porovnání proti jedinému pevnému kotevnímu bodu."""
    n = len(spots)
    parent = list(range(n))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i: int, j: int) -> None:
        ri, rj = find(i), find(j)
        if ri != rj:
            parent[ri] = rj

    for i in range(n):
        for j in range(i + 1, n):
            if (
                abs(spots[i].freq_hz - spots[j].freq_hz) <= freq_tolerance_hz
                and abs(spots[i].timestamp - spots[j].timestamp) <= time_window_seconds
            ):
                union(i, j)

    clusters: dict[int, list[Spot]] = defaultdict(list)
    for i, spot in enumerate(spots):
        clusters[find(i)].append(spot)
    return list(clusters.values())


def group_spots_into_candidates(
    spots: list[Spot],
    *,
    time_window_seconds: float = DEFAULT_MERGE_TIME_WINDOW_SECONDS,
) -> list[Candidate]:
    """Seskupí spoty do kandidátů.

    Sloučení do jednoho kandidáta vyžaduje shodu callsign + band +
    kompatibilní (normalizovaný, viz models.Spot.__post_init__) mód +
    přibližnou frekvenci + časové okno (viz ``_cluster_by_freq_and_time``).
    Zdroj, který daný mód strukturálně nevidí (např. PSKReporter u SSB),
    prostě není mezi ``confirming_sources`` -- to není důvod k nesloučení
    ani k penalizaci, víc zdrojů je jen bonus (viz scoring.py
    ``_sources_reason``)."""
    coarse: dict[tuple[str, str, str], list[Spot]] = defaultdict(list)
    for spot in spots:
        coarse[(spot.callsign, spot.band, spot.mode)].append(spot)

    candidates = []
    for (callsign, band, mode), group in coarse.items():
        freq_tolerance_hz = _freq_tolerance_for_mode(mode)
        for cluster in _cluster_by_freq_and_time(group, freq_tolerance_hz, time_window_seconds):
            cluster.sort(key=lambda s: s.timestamp)
            latest = cluster[-1]
            snr_values = [s.snr_db for s in cluster if s.snr_db is not None]
            candidates.append(
                Candidate(
                    callsign=callsign,
                    freq_hz=latest.freq_hz,
                    mode=mode,
                    band=band,
                    first_seen=cluster[0].timestamp,
                    last_seen=latest.timestamp,
                    confirming_sources={s.source for s in cluster},
                    best_snr_db=max(snr_values) if snr_values else None,
                    comments=[s.comment for s in cluster if s.comment],
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
        source_poll_interval_seconds: float = 60.0,
        source_backoff_max_seconds: float = DEFAULT_BACKOFF_MAX_SECONDS,
    ):
        self.sources = sources
        self.db = db
        self.scoring_cfg = scoring_cfg
        self.qth_latlon = qth_latlon
        self.pollers: list[PolledSource] = [
            PolledSource(
                source,
                interval_seconds=source_poll_interval_seconds,
                backoff_max_seconds=source_backoff_max_seconds,
            )
            for source in sources
        ]

    def poll_once(self, now: float | None = None) -> list[Spot]:
        """Vytáhne spoty ze všech zdrojů (nejvýš jednou za jejich
        ``interval_seconds`` -- viz ``PolledSource``), nově stažené uloží
        do DB a vrátí spoty použitelné pro sestavení kandidátů (čerstvé,
        nebo cache z posledního úspěšného fetche, když se v tomto cyklu
        na síť nesahalo kvůli throttlingu/backoffu)."""
        now = time.time() if now is None else now
        all_spots: list[Spot] = []
        for poller in self.pollers:
            spots_for_candidates, freshly_fetched = poller.poll(now)
            for spot in freshly_fetched:
                self.db.insert_spot(spot)
            all_spots.extend(spots_for_candidates)
        return all_spots

    def source_status(self, now: float | None = None) -> list[dict]:
        now = time.time() if now is None else now
        return [poller.status_dict(now) for poller in self.pollers]

    def close(self) -> None:
        """Zastaví vlákna živých streamovacích zdrojů (DX Cluster, RBN) --
        volá se při vypnutí aplikace. Zdroje bez ``close()`` (HTTP-based
        PSKReporter, mock) se prostě přeskočí."""
        for poller in self.pollers:
            close = getattr(poller.source, "close", None)
            if callable(close):
                close()

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
