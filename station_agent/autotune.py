"""AUTO TUNE rozhodovací logika.

Volá výhradně ``RigControl.set_frequency`` / ``set_mode`` (viz
rig/base.py) -- žádná jiná akce nad rigem se z této logiky nikdy nevolá,
a už vůbec ne vysílání (rozhraní RigControl žádnou takovou metodu ani
nemá). Viz AGENTS.md pravidlo 1.

Pravidla (v tomto pořadí):
1. Pokud AUTO TUNE není zapnuté -> NONE.
2. Pokud je aktivní HOLD -> NONE.
3. Žádný kandidát nedosahuje min_score -> NONE.
4. Rig není naladěn na nic konkrétního -> přeladit na nejlepšího kandidáta.
5. Nejlepší kandidát == aktuální stanice -> NONE.
6. Doba na aktuální stanici < min_hold_seconds -> NONE.
7. (nejlepší.score - aktuální.score) < min_score_delta -> NONE.
8. Jinak -> TUNE na nejlepšího kandidáta.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from station_agent.config import AutoTuneConfig
from station_agent.db import Database
from station_agent.models import Candidate, RigState
from station_agent.rig.base import RigControl


@dataclass
class TuneDecision:
    action: str  # "NONE" | "TUNE"
    candidate: Candidate | None
    reason: str


class AutoTuneEngine:
    def __init__(self, cfg: AutoTuneConfig, min_score: int):
        self.cfg = cfg
        self.min_score = min_score

    def decide(
        self,
        candidates: list[Candidate],
        current: RigState | None,
        now: float | None = None,
    ) -> TuneDecision:
        now = time.time() if now is None else now

        if not self.cfg.enabled:
            return TuneDecision("NONE", None, "AUTO TUNE je vypnuté")
        if self.cfg.hold:
            return TuneDecision("NONE", None, "HOLD režim je aktivní -- přeladění zablokováno")

        eligible = [c for c in candidates if c.score and c.score.total >= self.min_score]
        if not eligible:
            return TuneDecision(
                "NONE", None, f"žádný kandidát nedosahuje min_score={self.min_score}"
            )
        eligible.sort(key=lambda c: c.score.total, reverse=True)
        best = eligible[0]

        if current is None or current.callsign is None:
            return TuneDecision(
                "TUNE",
                best,
                f"rig není naladěn na žádnou konkrétní stanici, ladím na {best.callsign} "
                f"(score {best.score.total})",
            )

        if best.callsign == current.callsign:
            return TuneDecision(
                "NONE", None, f"aktuální stanice {current.callsign} je již nejlepší kandidát"
            )

        held_for = now - current.tuned_at
        if held_for < self.cfg.min_hold_seconds:
            return TuneDecision(
                "NONE",
                None,
                f"minimální doba držení ještě neuplynula "
                f"({held_for:.0f}s / {self.cfg.min_hold_seconds:.0f}s)",
            )

        current_score = current.score if current.score is not None else 0
        delta = best.score.total - current_score
        if delta < self.cfg.min_score_delta:
            return TuneDecision(
                "NONE",
                None,
                f"rozdíl skóre {delta} nedosahuje min_score_delta={self.cfg.min_score_delta}",
            )

        return TuneDecision(
            "TUNE",
            best,
            f"přeladění na {best.callsign} (score {best.score.total} vs. aktuální "
            f"{current_score}, delta {delta})",
        )


def apply_decision(
    rig: RigControl, decision: TuneDecision, db: Database | None = None
) -> RigState | None:
    """Provede TUNE rozhodnutí (set_frequency + set_mode) a vrátí nový RigState.

    Pro NONE rozhodnutí nedělá nic a vrací None.
    """
    if decision.action != "TUNE" or decision.candidate is None:
        return None
    candidate = decision.candidate

    rig.set_frequency(candidate.freq_hz)
    rig.set_mode(candidate.mode)

    score_total = candidate.score.total if candidate.score else None
    if db is not None:
        db.log_autotune(candidate.callsign, candidate.freq_hz, candidate.mode, score_total, decision.reason)

    return RigState(
        freq_hz=candidate.freq_hz,
        mode=candidate.mode,
        tuned_at=time.time(),
        callsign=candidate.callsign,
        score=score_total,
    )
