"""DXCC lookup přes radioamatérská country-file data a bezpečné fallbacky."""
from __future__ import annotations

import logging
import csv
import json
import os
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from station_agent.dxcc import _base_call, callsign_to_dxcc
from station_agent.models import DXCCEntity

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _Log4OMPrefix:
    prefix: str
    exact_match: bool
    entity: DXCCEntity
    latitude: float | None = None
    longitude: float | None = None
    continent: str = ""


class _Log4OMCountryFile:
    """Read-only resolver for the current Log4OM2 country database."""

    def __init__(self, ctyfile_path: Path):
        self.path = ctyfile_path
        self._prefixes = self._load(ctyfile_path)

    def lookup(self, callsign: str) -> DXCCEntity | None:
        raw_call = (callsign or "").strip().upper()
        call = _base_call(raw_call)
        if not call:
            return None
        matches = [
            item for item in self._prefixes
            if ((raw_call == item.prefix or call == item.prefix)
                if item.exact_match else call.startswith(item.prefix))
        ]
        if not matches:
            return None
        matches.sort(key=lambda item: (len(item.prefix), item.exact_match), reverse=True)
        item = matches[0]
        entity = item.entity
        return DXCCEntity(
            name=entity.name,
            prefix=item.prefix,
            continent=item.continent or entity.continent,
            latitude=item.latitude if item.latitude is not None else entity.latitude,
            longitude=item.longitude if item.longitude is not None else entity.longitude,
            cq_zone=entity.cq_zone,
        )

    @staticmethod
    def _load(ctyfile_path: Path) -> list[_Log4OMPrefix]:
        with ctyfile_path.open("r", encoding="utf-8-sig") as handle:
            raw = json.load(handle)
        if not isinstance(raw, list) or not raw:
            raise ValueError("Log4OM2 country file has no entity list")

        names = _load_country_names(ctyfile_path.with_name("country.xml"))
        if not names:
            names = _load_arrl_names(ctyfile_path.with_name("arrl_dxcc.csv"))
        records: list[_Log4OMPrefix] = []
        for entity_raw in raw:
            if not isinstance(entity_raw, dict):
                continue
            try:
                dxcc_number = int(entity_raw["Dxcc"])
                root_coordinates = entity_raw["Coordinates"]
                root_latitude = float(root_coordinates["Latitude"])
                root_longitude = float(root_coordinates["Longitude"])
                cq_zone = int(entity_raw.get("CQZone") or 0)
                name = names[dxcc_number]
            except (KeyError, TypeError, ValueError):
                continue
            if not name:
                continue
            continent = str(entity_raw.get("Continent") or "").strip().upper()
            entity = DXCCEntity(
                name=name,
                prefix="",
                continent=continent,
                latitude=root_latitude,
                longitude=root_longitude,
                cq_zone=cq_zone,
            )
            for prefix_raw in entity_raw.get("Prefixes", []):
                if not isinstance(prefix_raw, dict):
                    continue
                prefix = str(prefix_raw.get("Callsign") or "").strip().upper()
                if not prefix or any(char in prefix for char in "*?[]()|^$\\"):
                    continue
                latitude, longitude = _valid_coordinates(prefix_raw.get("Coordinates"))
                records.append(_Log4OMPrefix(
                    prefix=prefix,
                    exact_match=bool(prefix_raw.get("ExactMatch", False)),
                    entity=entity,
                    latitude=latitude,
                    longitude=longitude,
                    continent=str(prefix_raw.get("Continent") or "").strip().upper(),
                ))
        if not records:
            raise ValueError("Log4OM2 country file has no usable prefix records")
        return records


def _valid_coordinates(raw: object) -> tuple[float | None, float | None]:
    if not isinstance(raw, dict):
        return None, None
    try:
        latitude = float(raw["Latitude"])
        longitude = float(raw["Longitude"])
    except (KeyError, TypeError, ValueError):
        return None, None
    if latitude == 0.0 and longitude == 0.0:
        return None, None
    if not (-90.0 <= latitude <= 90.0 and -180.0 <= longitude <= 180.0):
        return None, None
    return latitude, longitude


def _load_country_names(path: Path) -> dict[int, str]:
    if not path.is_file():
        return {}
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError):
        return {}
    names: dict[int, str] = {}
    for country in root.iter():
        if country.tag.rsplit("}", 1)[-1] != "Country":
            continue
        values = {
            child.tag.rsplit("}", 1)[-1]: (child.text or "").strip()
            for child in country
        }
        try:
            dxcc = int(values.get("Dxcc", ""))
        except ValueError:
            continue
        if values.get("CountryName"):
            names[dxcc] = values["CountryName"]
    return names


def _load_arrl_names(path: Path) -> dict[int, str]:
    if not path.is_file():
        return {}
    names: dict[int, str] = {}
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            for row in csv.reader(handle, delimiter=";"):
                if len(row) < 2:
                    continue
                try:
                    names[int(row[0])] = row[1].strip().title()
                except ValueError:
                    continue
    except OSError:
        return {}
    return names


def _country_file_candidates() -> list[Path]:
    candidates: list[Path] = []
    configured = os.environ.get("LOG4OM2_CTYFILE", "").strip()
    if configured:
        candidates.append(Path(configured))
    appdata = os.environ.get("APPDATA", "").strip()
    if appdata:
        candidates.append(Path(appdata) / "Log4OM2" / "ctyfile.json")
    candidates.append(Path.home() / "AppData" / "Roaming" / "Log4OM2" / "ctyfile.json")
    unique: list[Path] = []
    for path in candidates:
        resolved = path.expanduser()
        if resolved not in unique:
            unique.append(resolved)
    return unique


class CountryLookup:
    """Preferuje volitelný pyhamtools country-file backend; nikdy nehádá."""

    def __init__(
        self,
        network_fallback: Callable[[str], DXCCEntity | None] | None = None,
        country_file_path: str | Path | None = None,
    ):
        self.network_fallback = network_fallback
        self.country_file_path = Path(country_file_path) if country_file_path else None
        self._log4om_country_file: _Log4OMCountryFile | None = None
        self._callinfo = None
        self._initialization_attempted = False

    @property
    def country_file_available(self) -> bool:
        self._initialize()
        return self._log4om_country_file is not None or self._callinfo is not None

    def lookup(self, callsign: str) -> DXCCEntity | None:
        call = (callsign or "").strip().upper()
        if not call:
            return None
        self._initialize()
        if self._log4om_country_file is not None:
            try:
                entity = self._log4om_country_file.lookup(call)
                if entity is not None:
                    return entity
            except Exception as exc:
                logger.warning("Log4OM2 country lookup failed for %s: %s", call, exc)
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
        paths = [self.country_file_path] if self.country_file_path else []
        for path in paths + _country_file_candidates():
            if path is None or not path.is_file():
                continue
            try:
                self._log4om_country_file = _Log4OMCountryFile(path)
                logger.info("Using Log4OM2 country database: %s", path)
                break
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                logger.warning("Cannot load Log4OM2 country database %s: %s", path, exc)
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
