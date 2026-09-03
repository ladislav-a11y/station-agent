"""Transparentní scoring kandidátů 0-100.

Skóre je součet sedmi faktorů, každý s vlastní váhou z configu a lidsky
čitelným zdůvodněním (ScoreReason). Žádná "black box" logika -- rozpis
důvodů je to, co se zobrazuje v GUI vedle každého kandidáta.

Faktory freshness/sources/needed_dxcc/signal vychází výhradně z vlastností
jednoho kandidáta. reliability/propagation/path_dx navíc používají reálnou
evidenci: nezávislé spottery, hodinový propagation snapshot připravený mimo
scoring z NOAA Kp/SFI a QTH, a vzdálenost k QTH. Tento modul sám síť nikdy
nevolá. Když kontext chybí, používá zdokumentovaný neutrální nebo lokální
fallback, nikoli vymyšlená data.
"""

from __future__ import annotations

import time

from station_agent.config import DEFAULT_SCORING_WEIGHTS as DEFAULT_WEIGHTS
from station_agent.config import ScoringConfig
from station_agent.models import Candidate, ScoreReason, ScoreResult
from station_agent.propagation import PropagationContext

# Vzdálenost blížící se antipodální (~20 015 km) považujeme za "plné DX" pro
# účely path_dx faktoru -- dál už fyzicky nejde.
MAX_REALISTIC_DISTANCE_KM = 20_000.0

# Kolik nezávislých spotterů už považujeme za plně spolehlivé potvrzení
# (víc už skóre dál nezvyšuje -- viz _reliability_reason).
RELIABLE_SPOTTER_COUNT = 2

# Kolik odlišných stanic na stejném pásmu už bereme jako jasný signál
# otevřené propagace (viz aggregator.band_activity a _propagation_reason).
BUSY_BAND_STATION_COUNT = 5


def _freshness_reason(candidate: Candidate, cfg: ScoringConfig, now: float) -> ScoreReason:
    max_age_s = max(1.0, cfg.spot_max_age_minutes * 60.0)
    age_s = max(0.0, now - candidate.last_seen)
    fraction = max(0.0, 1.0 - age_s / max_age_s)
    weight = cfg.weights.get("freshness", 0)
    points = round(weight * fraction, 1)
    return ScoreReason(
        factor="freshness",
        points=points,
        max_points=weight,
        detail=f"spot starý {int(age_s)} s (limit čerstvosti {int(max_age_s)} s)",
    )


def _sources_reason(candidate: Candidate, cfg: ScoringConfig) -> ScoreReason:
    n = len(candidate.confirming_sources)
    fraction = min(1.0, n / 3.0)
    weight = cfg.weights.get("sources", 0)
    points = round(weight * fraction, 1)
    sources_txt = ", ".join(sorted(candidate.confirming_sources)) or "žádný"
    return ScoreReason(
        factor="sources",
        points=points,
        max_points=weight,
        detail=f"{n} potvrzující zdroj(e): {sources_txt}",
    )


def _needed_dxcc_reason(candidate: Candidate, cfg: ScoringConfig, is_needed: bool) -> ScoreReason:
    weight = cfg.weights.get("needed_dxcc", 0)
    dxcc_name = candidate.dxcc.name if candidate.dxcc else "neznámá entita"
    if is_needed:
        points = float(weight)
        detail = f"{dxcc_name}: nová/potřebná DXCC entita"
    else:
        points = round(weight * 0.2, 1)
        detail = f"{dxcc_name}: již dříve spojeno (worked)"
    return ScoreReason(factor="needed_dxcc", points=points, max_points=weight, detail=detail)


def _signal_reason(candidate: Candidate, cfg: ScoringConfig) -> ScoreReason:
    weight = cfg.weights.get("signal", 0)
    if candidate.best_snr_db is None:
        points = round(weight * 0.5, 1)
        return ScoreReason(
            factor="signal",
            points=points,
            max_points=weight,
            detail="SNR není k dispozici (neutrální hodnocení)",
        )
    # 0 dB -> 0 bodů, 30+ dB -> plný počet bodů, lineárně mezi tím.
    fraction = max(0.0, min(1.0, candidate.best_snr_db / 30.0))
    points = round(weight * fraction, 1)
    return ScoreReason(
        factor="signal",
        points=points,
        max_points=weight,
        detail=f"nejlepší SNR {candidate.best_snr_db:.0f} dB",
    )


def _reliability_reason(candidate: Candidate, cfg: ScoringConfig) -> ScoreReason:
    """Spolehlivost evidence -- kolik NEZÁVISLÝCH spotterů/skimmerů/přijímačů
    stanici potvrdilo (napříč zdroji i uvnitř jednoho zdroje). Jeden
    ojedinělý spotter může mít překlep/chybu; víc odlišných lidí/skimmerů
    hlásících stejný callsign na stejné frekvenci je silnější evidence."""
    weight = cfg.weights.get("reliability", 0)
    n_spotters = len(candidate.spotters)
    if n_spotters == 0:
        points = round(weight * 0.5, 1)
        return ScoreReason(
            factor="reliability",
            points=points,
            max_points=weight,
            detail="spotter neznámý (neutrální hodnocení spolehlivosti)",
        )
    # Known evidence must always outscore the "unknown" neutral baseline (0.5)
    # above -- even a single confirmed spotter is strictly better than no
    # spotter data at all, so the scale starts at 0.5 and climbs to 1.0 at
    # RELIABLE_SPOTTER_COUNT independent spotters, rather than passing through
    # the same 0.5 point at n_spotters == 1.
    fraction = min(1.0, 0.5 + 0.5 * n_spotters / RELIABLE_SPOTTER_COUNT)
    points = round(weight * fraction, 1)
    spotters_txt = ", ".join(sorted(candidate.spotters))
    return ScoreReason(
        factor="reliability",
        points=points,
        max_points=weight,
        detail=f"{n_spotters} nezávislý(ch) spotter(ů): {spotters_txt}",
    )


def _propagation_reason(
    candidate: Candidate, cfg: ScoringConfig, band_activity: dict[str, int] | None,
    propagation: PropagationContext | None = None,
) -> ScoreReason:
    """Use the prepared hourly outlook; fall back to observed band activity."""
    weight = cfg.weights.get("propagation", 0)
    if propagation is not None and candidate.band in propagation.band_quality:
        fraction = propagation.band_quality[candidate.band]
        points = round(weight * fraction, 1)
        return ScoreReason(
            factor="propagation",
            points=points,
            max_points=weight,
            detail=(f"hodinový model {candidate.band}={fraction:.3f}; "
                    f"{propagation.explanation}; zdroj {propagation.source}"),
        )
    if band_activity is None:
        points = round(weight * 0.5, 1)
        return ScoreReason(
            factor="propagation",
            points=points,
            max_points=weight,
            detail="aktivita pásma není k dispozici (neutrální hodnocení propagace)",
        )
    count = band_activity.get(candidate.band, 0)
    # 1 stanice na pásmu (kandidát sám) = zatím žádný signál otevření pásma.
    fraction = max(0.0, min(1.0, (count - 1) / (BUSY_BAND_STATION_COUNT - 1)))
    points = round(weight * fraction, 1)
    return ScoreReason(
        factor="propagation",
        points=points,
        max_points=weight,
        detail=f"{count} odlišných stanic na {candidate.band}; hodinový model není dostupný",
    )


def _path_dx_reason(candidate: Candidate, cfg: ScoringConfig) -> ScoreReason:
    """Hodnota "DX" cesty -- vzdálenost od nakonfigurovaného QTH uživatele
    (viz bearing.py/aggregator.attach_dxcc_and_bearing). Bez nakonfigurovaného
    QTH candidate.distance_km chybí -> neutrální hodnocení, ne penalizace."""
    weight = cfg.weights.get("path_dx", 0)
    if candidate.distance_km is None:
        points = round(weight * 0.5, 1)
        return ScoreReason(
            factor="path_dx",
            points=points,
            max_points=weight,
            detail="vzdálenost k QTH není k dispozici (neutrální hodnocení DX cesty)",
        )
    fraction = max(0.0, min(1.0, candidate.distance_km / MAX_REALISTIC_DISTANCE_KM))
    points = round(weight * fraction, 1)
    if candidate.bearing_deg is not None:
        detail = f"vzdálenost {candidate.distance_km:.0f} km, bearing {candidate.bearing_deg:.0f}° od QTH"
    else:
        detail = f"vzdálenost {candidate.distance_km:.0f} km od QTH"
    return ScoreReason(factor="path_dx", points=points, max_points=weight, detail=detail)


def score_candidate(
    candidate: Candidate,
    cfg: ScoringConfig,
    *,
    is_needed_dxcc,
    now: float | None = None,
    band_activity: dict[str, int] | None = None,
    propagation: PropagationContext | None = None,
) -> ScoreResult:
    """Spočítá skóre kandidáta a vrátí ScoreResult s rozpisem důvodů.

    ``is_needed_dxcc`` je callable(candidate) -> bool (typicky napojené na
    station_agent.db, viz aggregator.py), aby scoring.py nezávisel přímo na
    SQLite vrstvě. ``band_activity`` je volitelná mapa {band: počet odlišných
    stanic} pro _propagation_reason -- když chybí (např. scoring jednoho
    kandidáta mimo kontext celého seznamu), faktor je neutrální.
    """
    now = time.time() if now is None else now
    reasons = [
        _freshness_reason(candidate, cfg, now),
        _sources_reason(candidate, cfg),
        _needed_dxcc_reason(candidate, cfg, is_needed_dxcc(candidate)),
        _signal_reason(candidate, cfg),
        _reliability_reason(candidate, cfg),
        _propagation_reason(candidate, cfg, band_activity, propagation),
        _path_dx_reason(candidate, cfg),
    ]
    total = sum(r.points for r in reasons)
    total_clamped = max(0, min(100, round(total)))
    return ScoreResult(total=total_clamped, reasons=reasons)
