"""Sdílené pomocné funkce pro telnet-stylové adaptéry (DX Cluster, RBN)."""

from __future__ import annotations

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
