"""Převod interních dataclass modelů na JSON-serializovatelné slovníky pro GUI."""

from __future__ import annotations

from station_agent.autotune import TuneDecision
from station_agent.models import Candidate, RigState


def candidate_to_dict(candidate: Candidate) -> dict:
    return {
        "callsign": candidate.callsign,
        "freq_hz": candidate.freq_hz,
        "freq_mhz": round(candidate.freq_hz / 1_000_000, 6),
        "mode": candidate.mode,
        "band": candidate.band,
        "country": candidate.country,
        "locator": candidate.locator,
        "dxcc": (
            {
                "name": candidate.dxcc.name,
                "country": candidate.dxcc.name,
                "prefix": candidate.dxcc.prefix,
                "continent": candidate.dxcc.continent,
                "cq_zone": candidate.dxcc.cq_zone,
            }
            if candidate.dxcc
            else None
        ),
        "age_seconds": round(candidate.age_seconds, 1),
        "confirming_sources": sorted(candidate.confirming_sources),
        "spotters": sorted(candidate.spotters),
        "best_snr_db": candidate.best_snr_db,
        "bearing_deg": (round(candidate.bearing_deg, 1) if candidate.bearing_deg is not None else None),
        "distance_km": (round(candidate.distance_km, 0) if candidate.distance_km is not None else None),
        "score": (
            {
                "total": candidate.score.total,
                "reasons": [
                    {
                        "factor": r.factor,
                        "points": r.points,
                        "max_points": r.max_points,
                        "detail": r.detail,
                    }
                    for r in candidate.score.reasons
                ],
            }
            if candidate.score
            else None
        ),
    }


def rig_state_to_dict(state: RigState | None) -> dict | None:
    if state is None:
        return None
    return {
        "freq_hz": state.freq_hz,
        "mode": state.mode,
        "callsign": state.callsign,
        "tuned_at": state.tuned_at,
        "score": state.score,
        "country": state.country,
        "bearing_deg": state.bearing_deg,
        "distance_km": state.distance_km,
    }


def decision_to_dict(decision: TuneDecision | None) -> dict | None:
    if decision is None:
        return None
    return {
        "action": decision.action,
        "reason": decision.reason,
        "candidate_callsign": decision.candidate.callsign if decision.candidate else None,
    }
