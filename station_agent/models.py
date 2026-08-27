"""Sdílené datové modely používané napříč projektem."""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from station_agent.bandplan import canonical_digital_dial_frequency, freq_to_band
from station_agent.modes import normalize_mode


@dataclass
class Spot:
    """Jeden spot z jednoho zdroje (DX cluster, RBN, PSKReporter, mock, ...)."""

    callsign: str
    freq_hz: int
    mode: str
    timestamp: float  # unix epoch seconds (UTC)
    source: str
    snr_db: float | None = None
    comment: str = ""
    spotter: str = ""
    band: str = ""

    def __post_init__(self) -> None:
        self.callsign = self.callsign.strip().upper()
        self.mode = normalize_mode(self.mode)
        self.freq_hz = canonical_digital_dial_frequency(self.freq_hz, self.mode)
        if not self.band:
            self.band = freq_to_band(self.freq_hz) or "unknown"


@dataclass
class DXCCEntity:
    """Zjednodušená DXCC entita -- viz station_agent/dxcc.py pro tabulku."""

    name: str
    prefix: str
    continent: str
    latitude: float
    longitude: float
    cq_zone: int = 0


@dataclass
class ScoreReason:
    factor: str
    points: float
    max_points: float
    detail: str


@dataclass
class ScoreResult:
    total: int
    reasons: list[ScoreReason] = field(default_factory=list)


@dataclass
class Candidate:
    """Sloučený pohled na jednu DX stanici napříč zdroji spotů."""

    callsign: str
    freq_hz: int
    mode: str
    band: str
    first_seen: float
    last_seen: float
    confirming_sources: set[str] = field(default_factory=set)
    best_snr_db: float | None = None
    comments: list[str] = field(default_factory=list)
    dxcc: DXCCEntity | None = None
    bearing_deg: float | None = None
    distance_km: float | None = None
    score: ScoreResult | None = None

    @property
    def age_seconds(self) -> float:
        return max(0.0, time.time() - self.last_seen)


@dataclass
class RigState:
    """Aktuální (mock nebo reálný) stav riggu, jak ho vidí AUTO TUNE."""

    freq_hz: int
    mode: str
    tuned_at: float
    callsign: str | None = None
    score: int | None = None
