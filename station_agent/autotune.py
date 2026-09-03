"""AUTO TUNE rozhodovací logika.

Volá výhradně ``RigControl.set_frequency`` / ``set_mode`` (viz
rig/base.py) -- žádná jiná akce nad rigem se z této logiky nikdy nevolá,
a už vůbec ne vysílání (rozhraní RigControl žádnou takovou metodu ani
nemá). Viz AGENTS.md pravidlo 1.

Pravidla (v tomto pořadí):
0. Pokud je aktivní HOLD a od naladění aktuální stanice uplynulo aspoň
   ``min_hold_seconds`` -> HOLD sám vyprší (``cfg.hold = False``) a AUTO
   TUNE se sám znovu zapne (``cfg.enabled = True``), načež se pokračuje
   běžným vyhodnocením níže. Bez tohoto kroku by po ručním NALADIT (které
   nastaví HOLD a vypne AUTO TUNE, viz app_state.manual_tune) zůstalo
   AUTO TUNE navždy vypnuté, dokud by ho operátor ručně znovu nezapnul --
   diagnostikovaný bug "autotune se nespustí i po vypršení doby držení".
1. Pokud AUTO TUNE není zapnuté -> NONE.
2. Pokud je aktivní HOLD -> NONE.
2b. Kandidáti mimo aktuálně aktivní ``allowed_bands``/``allowed_modes`` se
    zahodí -- toto filtrování dělá primárně aggregator (viz aggregator.py),
    ale engine ho vynucuje i sám (defense-in-depth), aby výběr AUTO TUNE
    nikdy nezávisel jen na tom, že mu volající předá už filtrovaný seznam.
3. Žádný kandidát nedosahuje min_score -> NONE.
4. Rig není naladěn na nic konkrétního -> přeladit na nejlepšího kandidáta.
4b. Aktuální mód/pásmo riggu už neodpovídá aktivním filtrům (operátor je
    za běhu vypnul) -> přeladit na nejlepšího kandidáta bez ohledu na
    min_hold_seconds/min_score_delta -- AUTO TUNE nesmí zůstat na
    zakázaném módu/pásmu jen proto, že přeladění by "nestálo za to".
5. Nejlepší kandidát == aktuální stanice -> NONE.
6. Doba na aktuální stanici < min_hold_seconds -> NONE.
7. (nejlepší.score - aktuální.score) < min_score_delta -> NONE.
8. Jinak -> TUNE na nejlepšího kandidáta.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from station_agent.bandplan import freq_to_band
from station_agent.config import AutoTuneConfig
from station_agent.db import Database
from station_agent.models import Candidate, RigState
from station_agent.rig.base import RigControl

logger = logging.getLogger(__name__)


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
        allowed_bands: set[str] | None = None,
        allowed_modes: set[str] | None = None,
    ) -> TuneDecision:
        now = time.time() if now is None else now

        if self.cfg.hold and current is not None and (now - current.tuned_at) >= self.cfg.min_hold_seconds:
            logger.debug(
                "HOLD vypršel po %.0fs (min_hold_seconds=%.0f) -- AUTO TUNE se znovu zapíná",
                now - current.tuned_at, self.cfg.min_hold_seconds,
            )
            self.cfg.hold = False
            self.cfg.enabled = True

        if not self.cfg.enabled:
            return TuneDecision("NONE", None, "AUTO TUNE je vypnuté")
        if self.cfg.hold:
            return TuneDecision("NONE", None, "HOLD režim je aktivní -- přeladění zablokováno")

        if allowed_modes is not None:
            candidates = [c for c in candidates if c.mode in allowed_modes]
        if allowed_bands is not None:
            candidates = [c for c in candidates if c.band in allowed_bands]

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

        current_band = freq_to_band(current.freq_hz)
        current_disallowed = (allowed_modes is not None and current.mode not in allowed_modes) or (
            allowed_bands is not None and current_band not in allowed_bands
        )
        if current_disallowed and best.callsign != current.callsign:
            return TuneDecision(
                "TUNE",
                best,
                f"aktuální stanice {current.callsign} ({current.mode}, {current_band}) už "
                f"neodpovídá aktivním filtrům módů/pásem, ladím na {best.callsign} "
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
        country=candidate.country,
        bearing_deg=candidate.bearing_deg,
        distance_km=candidate.distance_km,
    )
