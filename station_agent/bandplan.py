"""Mapování frekvence na amatérské KV pásmo.

Pokrývá pásma požadovaná v GUI filtru (80/40/30/20/17/15/12/10 m). Meze
odpovídají obecnému IARU pásmovému plánu (region 1); pro jiné regiony se
mohou lišit v jednotkách kHz, což pro účely spot agregace a scoringu není
podstatné.
"""

from __future__ import annotations

# pásmo -> (dolní mez Hz, horní mez Hz)
BAND_LIMITS_HZ: dict[str, tuple[int, int]] = {
    "80m": (3_500_000, 3_800_000),
    "40m": (7_000_000, 7_200_000),
    "30m": (10_100_000, 10_150_000),
    "20m": (14_000_000, 14_350_000),
    "17m": (18_068_000, 18_168_000),
    "15m": (21_000_000, 21_450_000),
    "12m": (24_890_000, 24_990_000),
    "10m": (28_000_000, 29_700_000),
}

# Pořadí odpovídá požadovanému pořadí filtrů v GUI.
SUPPORTED_BANDS: list[str] = ["80m", "40m", "30m", "20m", "17m", "15m", "12m", "10m"]


def freq_to_band(freq_hz: int) -> str | None:
    """Vrátí název pásma pro danou frekvenci v Hz, nebo None mimo rozsah."""
    for band, (lo, hi) in BAND_LIMITS_HZ.items():
        if lo <= freq_hz <= hi:
            return band
    return None


def band_to_default_freq_hz(band: str) -> int | None:
    """Vrátí dolní mez pásma -- rozumný default pro přeladění na pásmo."""
    limits = BAND_LIMITS_HZ.get(band)
    return limits[0] if limits else None
