"""Sdílené pomocné funkce pro telnet-stylové adaptéry (DX Cluster, RBN)."""

from __future__ import annotations

import math
from typing import Literal


def normalize_reliability_percent(
    raw_value: object,
    *,
    unit: Literal["fraction", "percent"],
) -> float | None:
    """Normalizuje explicitní reliability údaj providera na procenta.

    Jednotka je povinná, aby se hodnoty 0..1 nikdy neinterpretovaly odhadem.
    Neplatný nebo chybějící údaj znamená ``None`` a zachová dosavadní
    chování providerů bez tohoto metadatového pole.
    """
    if raw_value is None or isinstance(raw_value, bool):
        return None
    try:
        value = float(raw_value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(value):
        return None
    if unit == "fraction":
        if not 0.0 <= value <= 1.0:
            return None
        value *= 100.0
    elif not 0.0 <= value <= 100.0:
        return None
    return value

from datetime import datetime, timedelta, timezone


def resolve_hhmm_timestamp(hhmm: str, now: float) -> float:
    """DX cluster / RBN udávají jen HH:MM v UTC bez data -- doplní dnešní
    datum, a pokud by výsledek byl >2 min v budoucnosti (přechod přes
    půlnoc UTC), posune se o den zpět."""
    hour, minute = int(hhmm[:2]), int(hhmm[2:])
    now_dt = datetime.fromtimestamp(now, tz=timezone.utc)
    candidate = now_dt.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if candidate.timestamp() > now + 120:
        candidate -= timedelta(days=1)
    return candidate.timestamp()
