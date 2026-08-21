"""Transparentní scoring kandidátů 0-100.

Skóre je součet čtyř faktorů, každý s vlastní váhou z configu a lidsky
čitelným zdůvodněním (ScoreReason). Žádná "black box" logika -- rozpis
důvodů je to, co se zobrazuje v GUI vedle každého kandidáta.
"""

from __future__ import annotations

import time

from station_agent.config import ScoringConfig
from station_agent.models import Candidate, ScoreReason, ScoreResult

DEFAULT_WEIGHTS = {
    "freshness": 25,
    "sources": 20,
    "needed_dxcc": 35,
    "signal": 20,
}


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


def score_candidate(
    candidate: Candidate,
    cfg: ScoringConfig,
    *,
    is_needed_dxcc,
    now: float | None = None,
) -> ScoreResult:
    """Spočítá skóre kandidáta a vrátí ScoreResult s rozpisem důvodů.

    ``is_needed_dxcc`` je callable(candidate) -> bool (typicky napojené na
    station_agent.db, viz aggregator.py), aby scoring.py nezávisel přímo na
    SQLite vrstvě.
    """
    now = time.time() if now is None else now
    reasons = [
        _freshness_reason(candidate, cfg, now),
        _sources_reason(candidate, cfg),
        _needed_dxcc_reason(candidate, cfg, is_needed_dxcc(candidate)),
        _signal_reason(candidate, cfg),
    ]
    total = sum(r.points for r in reasons)
    total_clamped = max(0, min(100, round(total)))
    return ScoreResult(total=total_clamped, reasons=reasons)
