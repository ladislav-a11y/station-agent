"""PSKReporter adaptér.

Na rozdíl od DX Clusteru a RBN (viz dx_cluster.py, rbn.py), které vyžadují
udržované telnet spojení na proudový server, je PSKReporter jednoduché
"HTTP GET -> XML" query API (viz https://www.pskreporter.info/pskdev.html).
To jde implementovat a spustit jako skutečný, kompletní HTTP klient bez
nutnosti dlouhotrvajícího spojení -- proto je tento adaptér ŽIVĚ funkční
(``fetch()`` reálně stahuje a parsuje aktuální data), zatímco DX Cluster a
RBN zůstávají PENDING (viz AGENTS.md pravidlo 6 a README "Stav externích
zdrojů").

Parsování XML reportu (formát "receptionReport" prvků) je odděleno do
``parse_pskreporter_report()`` a plně testováno na fixture datech -- viz
``tests/test_adapters_parsing.py``. Síťová vrstva (``fetch_pskreporter_xml``)
je testována proti skutečnému lokálnímu HTTP serveru (real socket, real
HTTP GET) v ``tests/test_adapters_live.py``, aby šlo ověřit, že adaptér
opravdu provádí síťový přenos, aniž by testy vyžadovaly přístup k
internetu (viz AGENTS.md "Testy běží bez internetu").
"""

from __future__ import annotations

import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

from station_agent.adapters.base import RateLimitedError, SpotSource
from station_agent.models import Spot

DEFAULT_QUERY_URL = "https://retrieve.pskreporter.info/query"
DEFAULT_TIMEOUT_S = 15.0
USER_AGENT = "station-agent/1.0 (DX asistent; https://www.pskreporter.info/pskdev.html)"


def parse_pskreporter_report(xml_text: str) -> list[Spot]:
    """Naparsuje XML odpověď PSKReporter query API na seznam Spot.

    Očekávaná struktura (zjednodušeně):
        <receptionReports>
          <receptionReport senderCallsign="OK1ABC" receiverCallsign="W1AW"
                            frequency="14074000" mode="FT8"
                            flowStartSeconds="1700000000" sNR="-10" />
          ...
        </receptionReports>

    ``senderCallsign`` je stanice, která vysílala (tedy DX kandidát),
    ``receiverCallsign`` je stanice, která ji přijala (obdoba "spotter").
    Řádky bez frekvence/callsignu/timestampu se přeskočí.
    """
    root = ET.fromstring(xml_text)
    spots: list[Spot] = []
    for elem in root.iter("receptionReport"):
        callsign = elem.get("senderCallsign")
        freq_raw = elem.get("frequency")
        flow_start = elem.get("flowStartSeconds")
        if not callsign or not freq_raw or not flow_start:
            continue
        snr_raw = elem.get("sNR")
        spots.append(
            Spot(
                callsign=callsign,
                freq_hz=int(freq_raw),
                mode=elem.get("mode", ""),
                timestamp=float(flow_start),
                source="pskreporter",
                snr_db=float(snr_raw) if snr_raw not in (None, "") else None,
                spotter=elem.get("receiverCallsign", "") or "",
                locator=elem.get("senderLocator") or None,
            )
        )
    return spots


def _parse_retry_after(value: str | None) -> float | None:
    """Naparsuje hodnotu HTTP hlavičky ``Retry-After`` -- podle RFC 7231 to
    může být buď počet sekund, nebo HTTP-date. Vrátí ``None``, pokud
    hlavička chybí nebo ji nejde naparsovat (volající pak použije vlastní
    exponenciální backoff)."""
    if not value:
        return None
    value = value.strip()
    try:
        return max(float(value), 0.0)
    except ValueError:
        pass
    try:
        dt = parsedate_to_datetime(value)
    except (TypeError, ValueError, IndexError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return max((dt - datetime.now(timezone.utc)).total_seconds(), 0.0)


def fetch_pskreporter_xml(
    query_url: str,
    params: dict[str, str] | None = None,
    timeout_s: float = DEFAULT_TIMEOUT_S,
) -> str:
    """Provede reálný HTTP GET na PSKReporter (nebo kompatibilní) query API
    a vrátí tělo odpovědi jako text. Toto je jediné místo v adaptéru, které
    mluví se sítí -- oddělené od ``parse_pskreporter_report``, aby šel
    parser testovat čistě na fixture datech a síťová vrstva samostatně proti
    lokálnímu testovacímu HTTP serveru (viz tests/test_adapters_live.py).

    HTTP 429 (Too Many Requests) se nepropaguje jako obecná ``HTTPError``,
    ale jako ``RateLimitedError`` s ``retry_after_seconds`` naparsovaným
    z ``Retry-After`` hlavičky (pokud ji server poslal) -- polling vrstva
    (``adapters/polling.py``) díky tomu ví, jak dlouho má počkat, než zdroj
    zkusí znovu.
    """
    url = query_url
    if params:
        separator = "&" if "?" in query_url else "?"
        url = f"{query_url}{separator}{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout_s) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            return response.read().decode(charset)
    except urllib.error.HTTPError as exc:
        exc.read()
        exc.close()
        if exc.code == 429:
            retry_after = _parse_retry_after(exc.headers.get("Retry-After") if exc.headers else None)
            raise RateLimitedError(retry_after_seconds=retry_after) from exc
        raise


class PSKReporterAdapter(SpotSource):
    """Živý zdroj spotů z PSKReporter query API.

    ``fetch()`` reálně provede HTTP GET na ``query_url`` (výchozí
    ``https://retrieve.pskreporter.info/query``) s volitelnými query
    parametry (``params``, např. ``senderCallsign``/``flowStartSeconds`` --
    viz dokumentace PSKReporter query API) a naparsuje odpověď přes
    ``parse_pskreporter_report``. Síťová chyba (timeout, DNS, HTTP chyba)
    se propaguje jako výjimka -- adaptér při selhání sítě nikdy nevrací
    vymyšlená data.
    """

    name = "pskreporter"

    def __init__(
        self,
        query_url: str = DEFAULT_QUERY_URL,
        params: dict[str, str] | None = None,
        timeout_s: float = DEFAULT_TIMEOUT_S,
    ):
        self.query_url = query_url
        self.params = dict(params or {})
        self.timeout_s = timeout_s

    def fetch(self) -> list[Spot]:
        xml_text = fetch_pskreporter_xml(self.query_url, self.params, self.timeout_s)
        return parse_pskreporter_report(xml_text)
