"""Mapování frekvence na amatérské KV pásmo.

Pokrývá pásma požadovaná v GUI filtru (80/40/30/20/17/15/12/10 m). Meze
odpovídají obecnému IARU pásmovému plánu (region 1); pro jiné regiony se
mohou lišit v jednotkách kHz, což pro účely spot agregace a scoringu není
podstatné.
"""

from __future__ import annotations

# pásmo -> (dolní mez Hz, horní mez Hz)
BAND_LIMITS_HZ: dict[str, tuple[int, int]] = {
    "160m": (1_800_000, 2_000_000),
    "80m": (3_500_000, 3_800_000),
    "60m": (5_351_000, 5_366_000),
    "40m": (7_000_000, 7_200_000),
    "30m": (10_100_000, 10_150_000),
    "20m": (14_000_000, 14_350_000),
    "17m": (18_068_000, 18_168_000),
    "15m": (21_000_000, 21_450_000),
    "12m": (24_890_000, 24_990_000),
    "10m": (28_000_000, 29_700_000),
    # 50.000 MHz itself is kept outside the allocation as a guard edge;
    # normal 6 m amateur frequencies (50.1–54 MHz) are included.
    "6m": (50_000_001, 54_000_000),
}

# Pořadí odpovídá požadovanému pořadí filtrů v GUI.
SUPPORTED_BANDS: list[str] = [
    "160m", "80m", "60m", "40m", "30m", "20m", "17m", "15m", "12m", "10m", "6m"
]


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
# Známé volací frekvence digitálních módů.
DIGITAL_CALLING_FREQUENCIES_HZ: list[tuple[int, int, str]] = [
    (1_840_000, 1_842_000, "FT8"),
    (3_573_000, 3_575_000, "FT8"),
    (5_357_000, 5_359_000, "FT8"),
    (7_073_000, 7_075_000, "FT8"),
    (10_135_000, 10_137_000, "FT8"),
    (14_073_000, 14_075_000, "FT8"),
    (18_099_000, 18_101_000, "FT8"),
    (21_073_000, 21_075_000, "FT8"),
    (24_914_000, 24_916_000, "FT8"),
    (28_073_000, 28_075_000, "FT8"),
    (50_313_000, 50_315_000, "FT8"),
]

# Hrubé IARU Region 1 hlasové segmenty vhodné pro fallback klasifikaci
# DX Cluster spotů, pokud komentář mód neobsahuje.
SSB_SEGMENTS_HZ: list[tuple[int, int]] = [
    (3_600_000, 3_800_000),
    (7_050_000, 7_200_000),
    (14_100_000, 14_350_000),
    (18_111_000, 18_168_000),
    (21_125_000, 21_450_000),
    (24_931_000, 24_990_000),
    (28_300_000, 29_700_000),
]


def infer_mode_from_frequency(freq_hz: int) -> str:
    """Odhadne mód z frekvence, pokud jej zdroj explicitně neuvádí."""

    for lo, hi, mode in DIGITAL_CALLING_FREQUENCIES_HZ:
        if lo <= freq_hz <= hi:
            return mode

    for lo, hi in SSB_SEGMENTS_HZ:
        if lo <= freq_hz <= hi:
            return "SSB"

    return ""
DIGITAL_DIAL_FREQUENCIES_HZ: dict[str, dict[str, list[int]]] = {
    "FT8": {
        "160m": [1_840_000],
        "80m": [3_573_000],
        "60m": [5_357_000],
        "40m": [7_074_000],
        "30m": [10_136_000],
        "20m": [14_074_000, 14_090_000],
        "17m": [18_100_000],
        "15m": [21_074_000],
        "12m": [24_915_000],
        "10m": [28_074_000],
        "6m": [50_313_000],
    },
    "FT4": {
        "160m": [1_840_000],
        "80m": [3_595_000],
        "60m": [5_357_000],
        "40m": [7_090_000],
        "30m": [10_140_000],
        "20m": [14_080_000, 14_140_000],
        "17m": [18_104_000],
        "15m": [21_140_000],
        "12m": [24_919_000],
        "10m": [28_180_000],
        "6m": [50_318_000],
    },
}

def canonical_digital_dial_frequency(
    freq_hz: int,
    mode: str,
    max_audio_offset_hz: int = 4_000,
) -> int:
    """Vrátí známou dial frequency FT8/FT4, pokud spot leží v jejím audio passbandu."""
    mode = mode.upper()
    band = freq_to_band(freq_hz)
    if band is None:
        return freq_hz

    dial_frequencies = DIGITAL_DIAL_FREQUENCIES_HZ.get(mode, {}).get(band, [])
    matches = [
        dial_hz
        for dial_hz in dial_frequencies
        if dial_hz <= freq_hz <= dial_hz + max_audio_offset_hz
    ]
    if not matches:
        return freq_hz

    return min(matches, key=lambda dial_hz: freq_hz - dial_hz)
