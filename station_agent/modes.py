"""Normalizace provozních módů na množinu podporovanou GUI filtrem."""

from __future__ import annotations

# Pořadí odpovídá požadovanému pořadí filtrů v GUI.
SUPPORTED_MODES: list[str] = [
    "SSB",
    "FT8",
    "FT4",
    "CW",
    "RTTY",
    "PSK31",
    "PSK63",
    "OTHER_DIGITAL",
]

# Aliasy, jak módy hlásí reálné zdroje (DX cluster/RBN/PSKReporter).
_ALIASES: dict[str, str] = {
    "USB": "SSB",
    "LSB": "SSB",
    "SSB": "SSB",
    "PHONE": "SSB",
    "FT8": "FT8",
    "FT4": "FT4",
    "CW": "CW",
    "RTTY": "RTTY",
    "RTTYM": "RTTY",
    "PSK31": "PSK31",
    "BPSK31": "PSK31",
    "PSK63": "PSK63",
    "BPSK63": "PSK63",
}


def normalize_mode(raw: str) -> str:
    """Převede libovolný textový mód na jednu z SUPPORTED_MODES.

    Neznámé/nerozpoznané módy (JT65, MSK144, JS8, PSK125, ...) spadají do
    katalogové položky "OTHER_DIGITAL", což odpovídá GUI filtru "Other
    Digital". Prázdný vstup je také OTHER_DIGITAL.
    """
    key = (raw or "").strip().upper()
    return _ALIASES.get(key, "OTHER_DIGITAL")
