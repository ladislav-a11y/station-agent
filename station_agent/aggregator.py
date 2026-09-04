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
from typing import Callable

from station_agent.adapters.base import SpotSource
from station_agent.adapters.polling import DEFAULT_BACKOFF_MAX_SECONDS, PolledSource
from station_agent.bearing import bearing_and_distance, maidenhead_to_latlon
from station_agent.config import ScoringConfig
from station_agent.db import Database
from station_agent.dxcc import callsign_to_dxcc
from station_agent.models import Candidate, DXCCEntity, Spot
from station_agent.propagation import PropagationContext
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
            latest_with_country = next((s for s in reversed(cluster) if s.country), None)
            latest_with_locator = next((s for s in reversed(cluster) if s.locator), None)
            latest_with_bearing = next((s for s in reversed(cluster) if s.bearing_deg is not None), None)
            latest_with_distance = next((s for s in reversed(cluster) if s.distance_km is not None), None)
            candidates.append(
                Candidate(
                    callsign=callsign,
                    freq_hz=latest.freq_hz,
                    mode=mode,
                    band=band,
                    first_seen=cluster[0].timestamp,
                    last_seen=latest.timestamp,
                    confirming_sources={s.source for s in cluster},
                    spotters={s.spotter for s in cluster if s.spotter},
                    best_snr_db=max(snr_values) if snr_values else None,
                    comments=[s.comment for s in cluster if s.comment],
                    country=latest_with_country.country if latest_with_country else None,
                    locator=latest_with_locator.locator if latest_with_locator else None,
                    bearing_deg=latest_with_bearing.bearing_deg if latest_with_bearing else None,
                    distance_km=latest_with_distance.distance_km if latest_with_distance else None,
                )
            )
    return candidates


def attach_dxcc_and_bearing(
    candidates: list[Candidate],
    qth_latlon: tuple[float, float] | None,
    dxcc_fallback: Callable[[str], DXCCEntity | None] | None = None,
) -> None:
    """Doplní chybějící zemi a trasu bez přepsání evidence ze zdroje.

    Lokátor konkrétní stanice je přesnější než referenční bod DXCC entity,
    proto se pro výpočet používá přednostně. ``Spot`` ale hodnotu lokátoru
    pouze normalizuje; její Maidenhead formát ověřuje až tato fáze při
    převodu na souřadnice. Hodnota odmítnutá převodníkem proto zůstává
    zachovaná jako původní evidence ze zdroje, nepoužije se pro geometrii
    a bezpečně se přejde na DXCC referenční bod. Varování se tedy týká
    lokátoru DX kandidáta dodaného zdrojem, nikoli konfigurovaného QTH.

    ``dxcc_fallback`` je volitelný druhý krok, který se zavolá jen když
    rychlá offline ``callsign_to_dxcc`` (PREFIX_TABLE) pro daný callsign
    nic nenajde -- typicky ``QRZClient.lookup`` (viz adapters/qrz.py). Nikdy
    nenahrazuje offline výsledek, jen ho doplňuje, a nikdy nevyhazuje
    výjimku (viz kontrakt ``QRZClient.lookup``), takže chybějící/nedostupný
    fallback nezmění nic na existujícím fail-safe chování (``None`` -> "?"
    v GUI, ne vymyšlená hodnota).
    """
    for candidate in candidates:
        entity = callsign_to_dxcc(candidate.callsign)
        if entity is None and dxcc_fallback is not None:
            entity = dxcc_fallback(candidate.callsign)
        candidate.dxcc = entity
        if not candidate.country and entity is not None:
            candidate.country = entity.name
        if qth_latlon is None or (
            candidate.bearing_deg is not None and candidate.distance_km is not None
        ):
            continue

        target_latlon = None
        if candidate.locator:
            try:
                target_latlon = maidenhead_to_latlon(candidate.locator)
            except ValueError as exc:
                logger.warning(
                    "Lokátor kandidáta %r pro %s nelze použít; "
                    "použije se referenční bod DXCC, pokud je známý: %s",
                    candidate.locator,
                    candidate.callsign,
                    exc,
                )
        if target_latlon is None and entity is not None:
            target_latlon = (entity.latitude, entity.longitude)
        if target_latlon is not None:
            bearing, distance = bearing_and_distance(
                qth_latlon[0], qth_latlon[1], target_latlon[0], target_latlon[1]
            )
            if candidate.bearing_deg is None:
                candidate.bearing_deg = bearing
            if candidate.distance_km is None:
                candidate.distance_km = distance


def band_activity(candidates: list[Candidate]) -> dict[str, int]:
    """Počet odlišných stanic aktuálně spotnutých na každém pásmu -- lokálně
    odvozený indikátor "otevření pásma" pro _propagation_reason ve
    scoring.py. Žádná externí služba (solar flux/K-index) se nevolá --
    AGENTS.md zakazuje fingovat data z nenapojených externích zdrojů, takže
    se vychází výhradně z reálně přijatých spotů."""
    activity: dict[str, set[str]] = defaultdict(set)
    for candidate in candidates:
        activity[candidate.band].add(candidate.callsign)
    return {band: len(calls) for band, calls in activity.items()}


def attach_scores(
    candidates: list[Candidate], scoring_cfg: ScoringConfig, db: Database, now: float | None = None,
    propagation: PropagationContext | None = None,
) -> None:
    """Spočítá a doplní ScoreResult pro každého kandidáta -- in place."""

    def is_needed(candidate: Candidate) -> bool:
        if candidate.dxcc is None:
            return True  # neznámá entita -> raději upozornit, ať operátor ověří
        return not db.is_worked(candidate.dxcc.name)

    activity = band_activity(candidates)
    for candidate in candidates:
        candidate.score = score_candidate(
            candidate, scoring_cfg, is_needed_dxcc=is_needed, now=now, band_activity=activity,
            propagation=propagation,
        )


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
        propagation: PropagationContext | None = None,
        dxcc_fallback: Callable[[str], DXCCEntity | None] | None = None,
    ):
        self.sources = sources
        self.db = db
        self.scoring_cfg = scoring_cfg
        self.qth_latlon = qth_latlon
        self.propagation = propagation
        self.dxcc_fallback = dxcc_fallback
        self.pollers: list[PolledSource] = [
            PolledSource(
                source,
                # Některé zdroje (viz SpotSource.min_poll_interval_seconds,
                # např. PSKReporterAdapter) potřebují přísnější minimum, než
                # jaké má uživatel nastavené v configu -- zabraňuje to HTTP
                # 429 i při nízkém polling.source_interval_seconds.
                interval_seconds=max(source_poll_interval_seconds, source.min_poll_interval_seconds),
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
            self.db.insert_spots(freshly_fetched)
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
        attach_dxcc_and_bearing(candidates, self.qth_latlon, dxcc_fallback=self.dxcc_fallback)
        attach_scores(candidates, self.scoring_cfg, self.db, now=now, propagation=self.propagation)
        candidates.sort(key=lambda c: c.score.total if c.score else 0, reverse=True)
        return candidates
