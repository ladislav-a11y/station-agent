"""Hourly, evidence-backed propagation context from public space-weather APIs."""

from __future__ import annotations

import json
import logging
import math
import threading
import time
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone

from station_agent.bearing import maidenhead_to_latlon

logger = logging.getLogger(__name__)

DEFAULT_KP_URL = "https://services.swpc.noaa.gov/products/noaa-planetary-k-index.json"
DEFAULT_SFI_URL = "https://services.swpc.noaa.gov/json/f107_cm_flux.json"


@dataclass(frozen=True)
class PropagationContext:
    kp: float | None
    solar_flux: float | None
    observed_at: float
    source: str
    qth_locator: str | None = None
    band_quality: dict[str, float] = field(default_factory=dict)
    explanation: str = ""

    @property
    def age_seconds(self) -> float:
        return max(0.0, time.time() - self.observed_at)


def _latest_numeric(rows: list, key: str | tuple[str, ...]) -> float | None:
    """Read the newest value from dict rows or NOAA's header + array format."""
    keys = (key,) if isinstance(key, str) else key
    if rows and isinstance(rows[0], list):
        header = [str(value).strip().lower() for value in rows[0]]
        wanted = {candidate.lower() for candidate in keys}
        indexes = [index for index, name in enumerate(header) if name in wanted]
        for row in reversed(rows[1:]):
            if not isinstance(row, list):
                continue
            for index in indexes:
                if index < len(row):
                    try:
                        return float(row[index])
                    except (TypeError, ValueError):
                        pass
        return None
    dict_rows = [row for row in rows if isinstance(row, dict)]
    if dict_rows and any("time_tag" in row for row in dict_rows):
        dict_rows.sort(key=lambda row: str(row.get("time_tag", "")))
    for row in reversed(dict_rows):
        normalized_row = {str(name).strip().lower(): value for name, value in row.items()}
        for candidate in (name.lower() for name in keys):
            try:
                return float(normalized_row[candidate])
            except (KeyError, TypeError, ValueError):
                continue
    return None


def calculate_band_quality(
    kp: float,
    solar_flux: float,
    qth_locator: str | None,
    observed_at: float,
) -> tuple[dict[str, float], str]:
    """Build an explainable 0..1 hourly HF outlook for the configured QTH."""
    longitude = 0.0
    locator_detail = "QTH neznámé, použit UTC sluneční čas"
    if qth_locator:
        _latitude, longitude = maidenhead_to_latlon(qth_locator)
        locator_detail = f"QTH {qth_locator.upper()}"

    utc_hour = datetime.fromtimestamp(observed_at, tz=timezone.utc).hour
    local_solar_hour = (utc_hour + longitude / 15.0) % 24.0
    daylight = max(0.0, math.cos(math.pi * (local_solar_hour - 12.0) / 12.0))
    night = 1.0 - daylight
    flux = max(0.0, min(1.0, (solar_flux - 65.0) / 135.0))
    geomagnetic = max(0.0, min(1.0, 1.0 - kp / 9.0))

    profiles = {
        "160m": (0.10, 0.90, 0.10), "80m": (0.15, 0.85, 0.15),
        "60m": (0.30, 0.70, 0.25), "40m": (0.45, 0.55, 0.35),
        "30m": (0.60, 0.40, 0.50), "20m": (0.75, 0.25, 0.65),
        "17m": (0.85, 0.15, 0.75), "15m": (0.90, 0.10, 0.85),
        "12m": (0.95, 0.05, 0.95), "10m": (1.00, 0.00, 1.00),
        "6m": (1.00, 0.00, 1.00),
    }
    quality: dict[str, float] = {}
    for band, (day_weight, night_weight, flux_weight) in profiles.items():
        time_component = day_weight * daylight + night_weight * night
        ionization = (1.0 - flux_weight) + flux_weight * flux
        propagation_potential = max(0.01, time_component * ionization)
        quality[band] = round(max(0.0, min(1.0, propagation_potential * geomagnetic)), 3)
    explanation = (
        f"{locator_detail}; lokální sluneční čas {local_solar_hour:.1f} h; "
        f"Kp={kp:.1f}; SFI={solar_flux:.1f}; geomagnetický faktor={geomagnetic:.2f}; "
        f"denní faktor={daylight:.2f}"
    )
    return quality, explanation


def fetch_noaa_context(
    kp_url: str = DEFAULT_KP_URL,
    sfi_url: str = DEFAULT_SFI_URL,
    timeout_s: float = 15.0,
    qth_locator: str | None = None,
    now: float | None = None,
) -> PropagationContext:
    """Fetch current NOAA data; network errors are propagated, never faked."""
    def load(url: str) -> list:
        request = urllib.request.Request(url, headers={"User-Agent": "station-agent/1.0"})
        with urllib.request.urlopen(request, timeout=timeout_s) as response:
            return json.loads(response.read().decode("utf-8"))

    kp_rows = load(kp_url)
    sfi_rows = load(sfi_url)
    kp = _latest_numeric(kp_rows, ("kp_index", "kp"))
    sfi = _latest_numeric(sfi_rows, ("f10.7", "flux", "adjusted_flux", "solar_flux"))
    if kp is None or sfi is None:
        raise ValueError("NOAA response neobsahuje číselné Kp a SFI")
    observed_at = time.time() if now is None else now
    band_quality, explanation = calculate_band_quality(kp, sfi, qth_locator, observed_at)
    return PropagationContext(
        kp=kp, solar_flux=sfi, observed_at=observed_at, source="NOAA SWPC",
        qth_locator=qth_locator, band_quality=band_quality, explanation=explanation,
    )


class PropagationService:
    """Thread-safe hourly cache used by scoring and the GUI."""

    def __init__(self, qth_locator: str | None = None, refresh_seconds: float = 3600.0,
                 fetcher=fetch_noaa_context, kp_url: str = DEFAULT_KP_URL,
                 sfi_url: str = DEFAULT_SFI_URL):
        self.qth_locator = qth_locator
        self.refresh_seconds = refresh_seconds
        self.fetcher = fetcher
        self.kp_url = kp_url
        self.sfi_url = sfi_url
        self._context: PropagationContext | None = None
        self._last_attempt_at: float | None = None
        self._lock = threading.Lock()

    def refresh_if_due(self, now: float | None = None) -> PropagationContext | None:
        now = time.time() if now is None else now
        with self._lock:
            if self._last_attempt_at is not None and now - self._last_attempt_at < self.refresh_seconds:
                return self._context
            self._last_attempt_at = now
            try:
                self._context = self.fetcher(kp_url=self.kp_url, sfi_url=self.sfi_url,
                                             qth_locator=self.qth_locator, now=now)
            except Exception:
                logger.exception("Propagation data refresh failed; retaining prior evidence")
            return self._context

    @property
    def context(self) -> PropagationContext | None:
        with self._lock:
            return self._context
