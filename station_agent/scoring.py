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

Propagace / otevření pásma je DOMINANTNÍ faktor, a to strukturálně, ne jen
váhou: faktory měřící vzdálenou evidenci ("někdo někde stanici slyší" --
sources a reliability) jsou násobeny "hearability gate" odvozeným z téhož
propagation výhledu (viz _hearability_gate). Kandidát bez podmínek pro
slyšitelnost u vlastního QTH tak nemůže nasbírat vysoké skóre jen kvůli
vysokému počtu spotterů, ať jsou váhy v configu jakékoli; kandidát na
otevřeném pásmu je zařazen výš. Gate se neaplikuje, když propagace není
známa (neutrální fallback) nebo když ji uživatel váhou 0 vypnul.
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

# Reliabilita spotu podle principu Log4OM2 (DX Cluster "spot reliability"
# filtr): spolehlivost se neodvozuje z toho, KTERÝ provider/cluster spot
# poslal (identita zdroje k tomu nic neříká -- viz
# DX_PROVIDER_RELIABILITY_RESEARCH.md), ale z vlastností a potvrzení spotu
# samotného -- kolik NA SOBĚ NEZÁVISLÝCH spotterů nahlásilo stejnou stanici
# na stejném pásmu/módu v rámci časového okna slučování
# (aggregator.DEFAULT_MERGE_TIME_WINDOW_SECONDS). Log4OM2 v Cluster filtru
# označí spot jako "reliable" od nakonfigurovaného počtu takových nezávislých
# potvrzení -- zde je ekvivalentem `candidate.spotters` a tento práh.
# Kolik nezávislých spotterů už považujeme za plně spolehlivé potvrzení
# (víc už skóre dál nezvyšuje -- viz _reliability_reason a is_reliable_spot).
RELIABLE_SPOTTER_COUNT = 2

# Kolik odlišných stanic na stejném pásmu už bereme jako jasný signál
# otevřené propagace (viz aggregator.band_activity a _propagation_reason).
BUSY_BAND_STATION_COUNT = 5

# Faktory, které měří pouze VZDÁLENOU evidenci -- kolik zdrojů/spotterů
# stanici někde slyší. Bez otevřeného pásma u vlastního QTH tato evidence
# nic neříká o šanci na spojení, proto jsou jejich body násobeny hearability
# gate z propagation výhledu (viz _hearability_gate). freshness/needed_dxcc/
# signal/path_dx gate nemají: nejsou počtem spotterů a jejich hodnota se
# s propagací nemění (novost DXCC platí i na zavřeném pásmu).
HEARABILITY_GATED_FACTORS = ("sources", "reliability")


def _hearability_gate(cfg: ScoringConfig, outlook: float | None) -> float | None:
    """Podíl 0-1, kterým se násobí body HEARABILITY_GATED_FACTORS.

    ``outlook`` je propagation podíl z _propagation_outlook (None = propagace
    neznámá, tj. neutrální fallback). Vrací None (gate se neaplikuje), když:
    - propagace není známa -- chybějící kontext nesmí penalizovat (viz
      DATA_CONTRACT.md sekce 3), nebo
    - uživatel propagaci vypnul váhou 0 -- pak nemá ani gatovat.
    Jinak je gate přímo propagation podíl: zavřené pásmo (0.0) evidenci
    spotterů úplně vynuluje, plně otevřené (1.0) ji nechá beze změny."""
    if outlook is None or cfg.weights.get("propagation", 0) <= 0:
        return None
    return max(0.0, min(1.0, outlook))


def _apply_hearability_gate(points: float, detail: str, gate: float | None) -> tuple[float, str]:
    """Škáluje body vzdálené evidence gate podílem a rozšíří detail tak, aby
    bylo v GUI vidět, PROČ kandidát s mnoha spottery body nedostal."""
    if gate is None or gate >= 1.0:
        return points, detail
    gated = round(points * gate, 1)
    return gated, f"{detail}; pásmo bez podmínek (propagace {gate:.2f}) -> evidence omezena x{gate:.2f}"


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


def _sources_reason(
    candidate: Candidate, cfg: ScoringConfig, gate: float | None = None,
) -> ScoreReason:
    n = len(candidate.confirming_sources)
    fraction = min(1.0, n / 3.0)
    weight = cfg.weights.get("sources", 0)
    points = round(weight * fraction, 1)
    sources_txt = ", ".join(sorted(candidate.confirming_sources)) or "žádný"
    points, detail = _apply_hearability_gate(
        points, f"{n} potvrzující zdroj(e): {sources_txt}", gate,
    )
    return ScoreReason(factor="sources", points=points, max_points=weight, detail=detail)


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


def _reliability_reason(
    candidate: Candidate, cfg: ScoringConfig, gate: float | None = None,
) -> ScoreReason:
    """Spolehlivost evidence -- kolik NEZÁVISLÝCH spotterů/skimmerů/přijímačů
    stanici potvrdilo (napříč zdroji i uvnitř jednoho zdroje). Jeden
    ojedinělý spotter může mít překlep/chybu; víc odlišných lidí/skimmerů
    hlásících stejný callsign na stejné frekvenci je silnější evidence
    (princip Log4OM2 "spot reliability" filtru -- viz RELIABLE_SPOTTER_COUNT
    výše a is_reliable_spot).

    ``gate`` (viz _hearability_gate) škáluje i neutrální fallback pro
    neznámého spottera -- jinak by na zavřeném pásmu "spotter neznámý"
    skóroval víc než potvrzení spotteři, což by obrátilo záruku
    test_one_confirmed_spotter_outscores_unknown_spotter."""
    weight = cfg.weights.get("reliability", 0)
    n_spotters = len(candidate.spotters)
    if n_spotters == 0:
        points = round(weight * 0.5, 1)
        points, detail = _apply_hearability_gate(
            points, "spotter neznámý (neutrální hodnocení spolehlivosti)", gate,
        )
        return ScoreReason(factor="reliability", points=points, max_points=weight, detail=detail)
    # Known evidence must always outscore the "unknown" neutral baseline (0.5)
    # above -- even a single confirmed spotter is strictly better than no
    # spotter data at all, so the scale starts at 0.5 and climbs to 1.0 at
    # RELIABLE_SPOTTER_COUNT independent spotters, rather than passing through
    # the same 0.5 point at n_spotters == 1.
    fraction = min(1.0, 0.5 + 0.5 * n_spotters / RELIABLE_SPOTTER_COUNT)
    points = round(weight * fraction, 1)
    spotters_txt = ", ".join(sorted(candidate.spotters))
    points, detail = _apply_hearability_gate(
        points, f"{n_spotters} nezávislý(ch) spotter(ů): {spotters_txt}", gate,
    )
    return ScoreReason(factor="reliability", points=points, max_points=weight, detail=detail)


def is_reliable_spot(candidate: Candidate) -> bool:
    """Log4OM2-styl kontroly reliability spotu pro konzumenty mimo scoring
    (GUI detail kandidáta, viz web/serialization.py) -- stejný práh
    nezávislých spotterů jako `_reliability_reason`, ale jako jednoduchý
    bool místo bodového rozpisu. Vždy vypočítatelné z lokální evidence
    (žádný "provider neodpověděl" stav), na rozdíl od dřívějšího
    DX-provider `reliability_percent` pole."""
    return len(candidate.spotters) >= RELIABLE_SPOTTER_COUNT


def _propagation_outlook(
    candidate: Candidate, band_activity: dict[str, int] | None,
    propagation: PropagationContext | None,
) -> tuple[float | None, str]:
    """Podíl otevření pásma 0-1 a jeho zdůvodnění. Use the prepared hourly
    outlook; fall back to observed band activity. None = propagace není
    známa (neutrální fallback), což zároveň vypíná hearability gate."""
    if propagation is not None and candidate.band in propagation.band_quality:
        fraction = propagation.band_quality[candidate.band]
        return fraction, (f"hodinový model {candidate.band}={fraction:.3f}; "
                          f"{propagation.explanation}; zdroj {propagation.source}")
    if band_activity is None:
        return None, "aktivita pásma není k dispozici (neutrální hodnocení propagace)"
    count = band_activity.get(candidate.band, 0)
    # 1 stanice na pásmu (kandidát sám) = zatím žádný signál otevření pásma.
    fraction = max(0.0, min(1.0, (count - 1) / (BUSY_BAND_STATION_COUNT - 1)))
    return fraction, f"{count} odlišných stanic na {candidate.band}; hodinový model není dostupný"


def _propagation_reason(
    candidate: Candidate, cfg: ScoringConfig, band_activity: dict[str, int] | None,
    propagation: PropagationContext | None = None,
    outlook: tuple[float | None, str] | None = None,
) -> ScoreReason:
    weight = cfg.weights.get("propagation", 0)
    fraction, detail = outlook or _propagation_outlook(candidate, band_activity, propagation)
    points = round(weight * (0.5 if fraction is None else fraction), 1)
    return ScoreReason(factor="propagation", points=points, max_points=weight, detail=detail)


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
    kandidáta mimo kontext celého seznamu), faktor je neutrální a hearability
    gate (viz HEARABILITY_GATED_FACTORS) se neaplikuje.
    """
    now = time.time() if now is None else now
    outlook = _propagation_outlook(candidate, band_activity, propagation)
    gate = _hearability_gate(cfg, outlook[0])
    reasons = [
        _freshness_reason(candidate, cfg, now),
        _sources_reason(candidate, cfg, gate),
        _needed_dxcc_reason(candidate, cfg, is_needed_dxcc(candidate)),
        _signal_reason(candidate, cfg),
        _reliability_reason(candidate, cfg, gate),
        _propagation_reason(candidate, cfg, band_activity, propagation, outlook=outlook),
        _path_dx_reason(candidate, cfg),
    ]
    total = sum(r.points for r in reasons)
    total_clamped = max(0, min(100, round(total)))
    return ScoreResult(total=total_clamped, reasons=reasons)
