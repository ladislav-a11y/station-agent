"""QRZ.com XML lookup -- obecný síťový fallback pro DXCC/zemi.

Rozsah: `station_agent/dxcc.py::PREFIX_TABLE` je záměrně neúplná offline
tabulka (viz `DIAGNOSIS_DXCC_PREFIX_GAP.md`) -- pro callsign, jehož žádný
prefix v tabulce není, `callsign_to_dxcc()` vrací `None`. Tento modul
poskytuje volitelný, obecný (ne hard-coded pro konkrétní prefix/callsign)
druhý krok: dotázat QRZ.com XML API na konkrétní callsign a z odpovědi
sestavit `DXCCEntity`. Volá se z `aggregator.attach_dxcc_and_bearing()`
jen pro kandidáty, u kterých offline tabulka selhala -- nikdy nenahrazuje
ani nepřepisuje rychlý offline lookup.

Na rozdíl od spotovacích adaptérů (`dx_cluster.py`, `rbn.py`,
`pskreporter.py`) tohle není `SpotSource` -- je to synchronní vyhledávací
klient. QRZ XML API (https://www.qrz.com/XML/current_spec.html) vyžaduje
session key získaný přihlášením uživatelským jménem/heslem
(`qrz.username`/`qrz.password` v config.yaml) -- bez vyplněných
přihlašovacích údajů zůstává fallback vypnutý (viz AGENTS.md pravidlo 6:
žádné volání externí služby bez explicitní volby uživatele, žádná
vymyšlená data).

Stejně jako u PSKReporteru (`adapters/pskreporter.py`) je síťová vrstva
(`fetch_qrz_session_xml`/`fetch_qrz_lookup_xml`) oddělená od parserů
(`parse_qrz_session_key`/`parse_qrz_lookup_xml`), aby šly parsery plně
testovat na fixture XML (`tests/test_qrz_parsing.py`) a síťová vrstva
samostatně proti skutečnému lokálnímu HTTP serveru (`tests/test_qrz_live.py`),
bez přístupu k internetu (viz AGENTS.md "Testy běží bez internetu").
"""

from __future__ import annotations

import logging
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from typing import Callable

from station_agent.models import DXCCEntity

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://xmldata.qrz.com/xml/current/"
DEFAULT_TIMEOUT_S = 10.0
# QRZ session key typicky vydrží platný cca 24 hodin -- cache lookupů drž
# ve stejném řádu, ať se zbytečně nevolá API pro stejný callsign znovu při
# každém obnovení kandidátů (aggregator.build_candidates běží opakovaně).
DEFAULT_CACHE_TTL_SECONDS = 86400.0
# Po síťové/auth chybě nezkoušet znovu okamžitě při každém dalším cyklu
# obnovení kandidátů -- stejný princip jako backoff u ostatních živých
# zdrojů (viz adapters/polling.py), jen jednodušší (pevná prodleva, ne
# exponenciální -- lookup je on-demand pro jednotlivé callsigny, ne
# periodický poll celého zdroje).
DEFAULT_ERROR_COOLDOWN_SECONDS = 300.0
USER_AGENT = "station-agent/1.0 (DX asistent DXCC fallback; https://www.qrz.com/XML/current_spec.html)"


class QRZLookupError(Exception):
    """QRZ XML API vrátilo chybu (např. neplatné přihlašovací údaje)."""


class _QRZSessionExpiredError(Exception):
    """Interní signál: session key vypršel/je neplatný -- QRZClient se podle
    něj pokusí o jedno opětovné přihlášení, než chybu vzdá."""


def _http_get(url: str, timeout_s: float) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout_s) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(charset)


def fetch_qrz_session_xml(
    base_url: str, username: str, password: str, timeout_s: float = DEFAULT_TIMEOUT_S
) -> str:
    """Reálný HTTP GET, který se přihlásí k QRZ XML API a vrátí session XML."""
    params = urllib.parse.urlencode(
        {"username": username, "password": password, "agent": "station-agent"}
    )
    return _http_get(f"{base_url}?{params}", timeout_s)


def fetch_qrz_lookup_xml(
    base_url: str, session_key: str, callsign: str, timeout_s: float = DEFAULT_TIMEOUT_S
) -> str:
    """Reálný HTTP GET, který vyhledá konkrétní callsign přes existující session key."""
    params = urllib.parse.urlencode({"s": session_key, "callsign": callsign})
    return _http_get(f"{base_url}?{params}", timeout_s)


def _find_text(elem: ET.Element | None, tag: str) -> str | None:
    if elem is None:
        return None
    return elem.findtext(f"{{*}}{tag}")


def parse_qrz_session_key(xml_text: str) -> str:
    """Vytáhne session key z odpovědi na přihlášení, nebo vyhodí `QRZLookupError`."""
    root = ET.fromstring(xml_text)
    session = root.find("{*}Session")
    error = _find_text(session, "Error")
    if error:
        raise QRZLookupError(f"QRZ přihlášení selhalo: {error}")
    key = _find_text(session, "Key")
    if not key:
        raise QRZLookupError("QRZ odpověď na přihlášení neobsahuje session key")
    return key


def parse_qrz_lookup_xml(xml_text: str) -> DXCCEntity | None:
    """Naparsuje odpověď QRZ XML API na vyhledání callsignu na `DXCCEntity`.

    `None` znamená legitimní "QRZ o tomto callsignu nic neví" (odpověď typu
    "Not found") -- stejná sémantika jako `station_agent.dxcc.callsign_to_dxcc`,
    žádná vymyšlená hodnota. Kontinent QRZ přímo nevrací, takže
    `DXCCEntity.continent` zůstává `""` (GUI to zobrazí bez závorky, viz
    `web/static/app.js`) -- radši chybějící údaj než odhadnutý.

    Jiná chyba než "Not found" (typicky vypršelá/neplatná session) se
    signalizuje jako `_QRZSessionExpiredError`, aby volající (`QRZClient`)
    mohl zkusit jedno opětovné přihlášení."""
    root = ET.fromstring(xml_text)
    session = root.find("{*}Session")
    error = _find_text(session, "Error")
    callsign_elem = root.find("{*}Callsign")
    if callsign_elem is None:
        if error and error.strip().lower().startswith("not found"):
            return None
        raise _QRZSessionExpiredError(error or "QRZ vyhledání nevrátilo žádná data")

    country = _find_text(callsign_elem, "country")
    lat_text = _find_text(callsign_elem, "lat")
    lon_text = _find_text(callsign_elem, "lon")
    if not country or not lat_text or not lon_text:
        return None
    try:
        lat = float(lat_text)
        lon = float(lon_text)
    except ValueError:
        return None

    cqzone_text = _find_text(callsign_elem, "cqzone")
    try:
        cq_zone = int(cqzone_text) if cqzone_text else 0
    except ValueError:
        cq_zone = 0

    call = (_find_text(callsign_elem, "call") or "").strip().upper()
    return DXCCEntity(name=country, prefix=call, continent="", latitude=lat, longitude=lon, cq_zone=cq_zone)


class QRZClient:
    """Přihlásí se k QRZ XML API a vyhledává `DXCCEntity` pro callsign.

    `lookup()` nikdy nevyhazuje výjimku -- síťová/auth chyba se zaloguje a
    chová se jako "neznámé" (`None`), stejně jako
    `station_agent.dxcc.callsign_to_dxcc`. Výsledky (včetně `None` u
    callsignů, které QRZ nezná) se cachují v paměti podle `cache_ttl_seconds`,
    aby opakované volání z `aggregator.attach_dxcc_and_bearing` (běží při
    každém obnovení kandidátů) nezatěžovalo QRZ zbytečnými dotazy na
    stejný callsign."""

    def __init__(
        self,
        username: str,
        password: str,
        base_url: str = DEFAULT_BASE_URL,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        cache_ttl_seconds: float = DEFAULT_CACHE_TTL_SECONDS,
        error_cooldown_seconds: float = DEFAULT_ERROR_COOLDOWN_SECONDS,
        time_func: Callable[[], float] = time.time,
    ):
        self.username = username
        self.password = password
        self.base_url = base_url
        self.timeout_s = timeout_s
        self.cache_ttl_seconds = cache_ttl_seconds
        self.error_cooldown_seconds = error_cooldown_seconds
        self._time = time_func
        self._session_key: str | None = None
        self._cache: dict[str, tuple[DXCCEntity | None, float]] = {}
        self._retry_not_before: float = 0.0

    def lookup(self, callsign: str) -> DXCCEntity | None:
        call = (callsign or "").strip().upper()
        if not call:
            return None
        now = self._time()
        cached = self._cache.get(call)
        if cached is not None and cached[1] > now:
            return cached[0]
        if now < self._retry_not_before:
            return None
        try:
            entity = self._lookup_uncached(call)
        except Exception as exc:  # síťová/auth chyba -- fail-closed, ne pád aplikace
            logger.warning(
                "QRZ vyhledání pro %s selhalo, zkusí se znovu za %.0f s: %s",
                call,
                self.error_cooldown_seconds,
                exc,
            )
            self._retry_not_before = now + self.error_cooldown_seconds
            return None
        self._cache[call] = (entity, now + self.cache_ttl_seconds)
        return entity

    def _lookup_uncached(self, call: str) -> DXCCEntity | None:
        if self._session_key is None:
            self._session_key = self._authenticate()
        try:
            xml_text = fetch_qrz_lookup_xml(self.base_url, self._session_key, call, self.timeout_s)
            return parse_qrz_lookup_xml(xml_text)
        except _QRZSessionExpiredError:
            self._session_key = self._authenticate()
            xml_text = fetch_qrz_lookup_xml(self.base_url, self._session_key, call, self.timeout_s)
            return parse_qrz_lookup_xml(xml_text)

    def _authenticate(self) -> str:
        xml_text = fetch_qrz_session_xml(self.base_url, self.username, self.password, self.timeout_s)
        return parse_qrz_session_key(xml_text)
