"""Mapování frekvence na amatérské KV pásmo.

Pokrývá pásma požadovaná v GUI filtru (80/40/30/20/17/15/12/10 m). Meze
odpovídají obecnému IARU pásmovému plánu (region 1); pro jiné regiony se
mohou lišit v jednotkách kHz, což pro účely spot agregace a scoringu není
podstatné.
"""

from __future__ import annotations

from dataclasses import dataclass

from station_agent.modes import normalize_mode

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


@dataclass(frozen=True)
class ModeFrequencyRule:
    """Jeden nepřekrývající se úsek doporučení IARU Region 1."""

    rule_id: str
    lower_hz: int
    upper_hz: int
    allowed_families: frozenset[str]
    max_bandwidth_hz: int
    source_revision: str = "IARU-R1-HF-2020-10-16"


@dataclass(frozen=True)
class ModeFrequencyValidation:
    valid: bool
    band: str | None
    normalized_mode: str
    rule_id: str | None
    reason: str
    source: str


_CW = frozenset({"CW"})
_NARROW = frozenset({"CW", "DIGITAL"})
_ALL = frozenset({"CW", "DIGITAL", "SSB"})

# Intervaly jsou polootevřené; pouze poslední horní mez každého pásma je při
# vyhledání pravidla zahrnuta. Katalog je konzervativní provozní profil podle
# IARU Region 1, nikoli tvrzení o úplné právní způsobilosti operátora.
MODE_FREQUENCY_RULES: tuple[ModeFrequencyRule, ...] = (
    ModeFrequencyRule("iaru-r1-2020-160m-1800-1838-narrow", 1_800_000, 1_838_000, _NARROW, 500),
    ModeFrequencyRule("iaru-r1-2020-160m-1838-2000-all", 1_838_000, 2_000_000, _ALL, 2700),
    ModeFrequencyRule("iaru-r1-2020-80m-3500-3600-narrow", 3_500_000, 3_600_000, _NARROW, 2700),
    ModeFrequencyRule("iaru-r1-2020-80m-3600-3800-all", 3_600_000, 3_800_000, _ALL, 2700),
    ModeFrequencyRule("iaru-r1-2020-60m-5351-5366-all", 5_351_000, 5_366_000, _ALL, 2700),
    ModeFrequencyRule("iaru-r1-2020-40m-7000-7040-cw", 7_000_000, 7_040_000, _CW, 500),
    ModeFrequencyRule("iaru-r1-2020-40m-7040-7050-narrow", 7_040_000, 7_050_000, _NARROW, 2700),
    ModeFrequencyRule("iaru-r1-2020-40m-7050-7200-all", 7_050_000, 7_200_000, _ALL, 2700),
    ModeFrequencyRule("iaru-r1-2020-30m-10100-10150-narrow", 10_100_000, 10_150_000, _NARROW, 500),
    ModeFrequencyRule("iaru-r1-2020-20m-14000-14100-narrow", 14_000_000, 14_100_000, _NARROW, 2700),
    ModeFrequencyRule("iaru-r1-2020-20m-14100-14350-all", 14_100_000, 14_350_000, _ALL, 2700),
    ModeFrequencyRule("iaru-r1-2020-17m-18068-18111-narrow", 18_068_000, 18_111_000, _NARROW, 500),
    ModeFrequencyRule("iaru-r1-2020-17m-18111-18168-all", 18_111_000, 18_168_000, _ALL, 2700),
    ModeFrequencyRule("iaru-r1-2020-15m-21000-21125-narrow", 21_000_000, 21_125_000, _NARROW, 2700),
    ModeFrequencyRule("iaru-r1-2020-15m-21125-21450-all", 21_125_000, 21_450_000, _ALL, 2700),
    ModeFrequencyRule("iaru-r1-2020-12m-24890-24931-narrow", 24_890_000, 24_931_000, _NARROW, 500),
    ModeFrequencyRule("iaru-r1-2020-12m-24931-24990-all", 24_931_000, 24_990_000, _ALL, 2700),
    ModeFrequencyRule("iaru-r1-2020-10m-28000-28300-narrow", 28_000_000, 28_300_000, _NARROW, 2700),
    ModeFrequencyRule("iaru-r1-2020-10m-28300-29700-all", 28_300_000, 29_700_000, _ALL, 2700),
    ModeFrequencyRule("iaru-r1-2020-6m-50000-54000-all", 50_000_001, 54_000_000, _ALL, 2700),
)


def validate_mode_frequency(
    freq_hz: int, mode: str, *, region: str = "IARU-R1"
) -> ModeFrequencyValidation:
    """Ověří, zda se mód vejde do příslušného provozního segmentu."""
    normalized = normalize_mode(mode)
    source = "IARU-R1-HF-2020-10-16"
    if region != "IARU-R1":
        return ModeFrequencyValidation(False, None, normalized, None, f"nepodporovaný region {region}", source)
    if isinstance(freq_hz, bool) or not isinstance(freq_hz, int) or freq_hz <= 0:
        return ModeFrequencyValidation(False, None, normalized, None, "kmitočet musí být kladné celé číslo v Hz", source)

    band = freq_to_band(freq_hz)
    if band is None:
        return ModeFrequencyValidation(False, None, normalized, None, "kmitočet je mimo podporovanou amatérskou alokaci", source)

    band_upper = BAND_LIMITS_HZ[band][1]
    matches = [
        rule for rule in MODE_FREQUENCY_RULES
        if rule.lower_hz <= freq_hz < rule.upper_hz
        or (freq_hz == band_upper == rule.upper_hz)
    ]
    if len(matches) != 1:
        return ModeFrequencyValidation(False, band, normalized, None, "katalog nemá pro kmitočet právě jedno pravidlo", source)
    rule = matches[0]
    family = "SSB" if normalized == "SSB" else "CW" if normalized == "CW" else "DIGITAL"
    if family not in rule.allowed_families:
        return ModeFrequencyValidation(False, band, normalized, rule.rule_id, f"mód {normalized} není v tomto segmentu povolen", rule.source_revision)

    # Station Agent nastavuje pod 10 MHz LSB a od 10 MHz USB. Celý hlasový
    # profil se musí vejít do jediného all-mode segmentu.
    if family == "SSB":
        occupied_lower = freq_hz - rule.max_bandwidth_hz if freq_hz < 10_000_000 else freq_hz
        occupied_upper = freq_hz if freq_hz < 10_000_000 else freq_hz + rule.max_bandwidth_hz
        if occupied_lower < rule.lower_hz or occupied_upper > rule.upper_hz:
            return ModeFrequencyValidation(False, band, normalized, rule.rule_id, "obsazené spektrum SSB přesahuje hranici segmentu", rule.source_revision)

    return ModeFrequencyValidation(True, band, normalized, rule.rule_id, "kombinace odpovídá provoznímu segmentu", rule.source_revision)


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
