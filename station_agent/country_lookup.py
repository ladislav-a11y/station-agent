"""DXCC lookup přes radioamatérská country-file data a bezpečné fallbacky."""
from __future__ import annotations

import logging
from typing import Callable

from station_agent.dxcc import callsign_to_dxcc
from station_agent.models import DXCCEntity

logger = logging.getLogger(__name__)


class CountryLookup:
    """Preferuje volitelný pyhamtools country-file backend; nikdy nehádá."""

    def __init__(self, network_fallback: Callable[[str], DXCCEntity | None] | None = None):
        self.network_fallback = network_fallback
        self._callinfo = None
        self._initialization_attempted = False

    @property
    def country_file_available(self) -> bool:
        self._initialize()
        return self._callinfo is not None

    def lookup(self, callsign: str) -> DXCCEntity | None:
        call = (callsign or "").strip().upper()
        if not call:
            return None
        self._initialize()
        if self._callinfo is not None:
            try:
                entity = self._country_file_entity(call)
                if entity is not None:
                    return entity
            except Exception as exc:
                logger.warning("Country-file lookup pro %s selhal: %s", call, exc)
        entity = callsign_to_dxcc(call)
        if entity is not None:
            return entity
        return self.network_fallback(call) if self.network_fallback is not None else None

    def _initialize(self) -> None:
        if self._initialization_attempted:
            return
        self._initialization_attempted = True
        try:
            from pyhamtools import Callinfo, LookupLib
            self._callinfo = Callinfo(LookupLib(lookuptype="countryfile"))
        except Exception as exc:
            logger.info("Country-file backend není dostupný, používám fallback: %s", exc)

    def _country_file_entity(self, call: str) -> DXCCEntity | None:
        data = self._callinfo.get_all(call)
        if not isinstance(data, dict) or not data.get("country"):
            return None
        try:
            latitude = float(data["latitude"])
            longitude = float(data["longitude"])
        except (KeyError, TypeError, ValueError):
            return None
        try:
            cq_zone = int(data.get("cqz") or data.get("cq_zone") or 0)
        except (TypeError, ValueError):
            cq_zone = 0
        return DXCCEntity(
            name=str(data["country"]).strip(),
            prefix=str(data.get("prefix") or call).strip().upper(),
            continent=str(data.get("continent") or "").strip().upper(),
            latitude=latitude,
            longitude=longitude,
            cq_zone=cq_zone,
        )
