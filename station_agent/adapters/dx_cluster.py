"""DX Cluster (telnet) adaptér.

Parsování standardního řádku DX clusteru (formát "DX de <SPOTTER>:") je
plně implementované a testované na fixture datech -- viz
``tests/test_adapters_parsing.py``. Živé telnet spojení používá sdílený
generický klient ``LiveTelnetSpotSource`` (``adapters/telnet_source.py``) --
skutečný TCP socket, login callsignem, čtení řádků a reconnect/backoff
nezávislý na ostatních zdrojích. ``fetch()`` vyhazuje ``SourceNotReadyError``
(GUI stav "pending"), dokud adaptér poprvé skutečně nenaváže spojení a
nenaparsuje aspoň jeden reálný spot -- viz README.md "Stav externích
zdrojů" a AGENTS.md pravidlo 6 ("Nefalšuj externí služby").

Výchozí ``host``/``port`` (``DEFAULT_HOST``/``DEFAULT_PORT``) ukazují na
běžně používaný veřejný AR-Cluster uzel (telnet přístupný bez hesla, jen
s přihlášením callsignem) -- operátor si v ``config.yaml`` může nastavit
jiný, typicky geograficky bližší cluster; seznam veřejných uzlů viz
https://www.ng3k.com/Misc/cluster.html.
"""

from __future__ import annotations

import re
import time

from station_agent.adapters._common import resolve_hhmm_timestamp
from station_agent.adapters.telnet_source import LiveTelnetSpotSource
from station_agent.models import Spot

# Příklad řádku:
# "DX de OK1KT:     14195.0  JA1XYZ       SSB nice signal          1234Z"
_LINE_RE = re.compile(
    r"^DX de (?P<spotter>[A-Za-z0-9/]+):\s+"
    r"(?P<freq_khz>\d+(?:\.\d+)?)\s+"
    r"(?P<callsign>[A-Za-z0-9/]+)\s+"
    r"(?P<comment>.*?)\s*"
    r"(?P<hhmm>\d{4})Z\s*$"
)

_MODE_KEYWORDS = ["FT8", "FT4", "PSK31", "PSK63", "RTTY", "CW", "USB", "LSB", "SSB", "JS8"]


def _extract_mode(comment: str) -> str:
    """Zkusí najít mód v komentáři spotu. DX cluster formát mód
    nevyžaduje, takže spotteři ho často (ne)zapisují do komentáře --
    pokud tam není, vrací se prázdný řetězec (-> normalizuje se na
    OTHER_DIGITAL). Toto je zdokumentované omezení textového formátu.
    """
    upper = comment.upper()
    for keyword in _MODE_KEYWORDS:
        if re.search(rf"\b{re.escape(keyword)}\b", upper):
            return keyword
    return ""


def parse_spot_line(line: str, now: float | None = None) -> Spot | None:
    """Naparsuje jeden řádek DX clusteru na Spot, nebo None pokud nesedí formát."""
    now = time.time() if now is None else now
    match = _LINE_RE.match(line.rstrip("\r\n"))
    if not match:
        return None
    freq_hz = int(round(float(match.group("freq_khz")) * 1000))
    comment = match.group("comment").strip()
    return Spot(
        callsign=match.group("callsign"),
        freq_hz=freq_hz,
        mode=_extract_mode(comment),
        timestamp=resolve_hhmm_timestamp(match.group("hhmm"), now),
        source="dx_cluster",
        comment=comment,
        spotter=match.group("spotter"),
    )


DEFAULT_HOST = "dxc.w3lpl.net"
DEFAULT_PORT = 7373


class DXClusterAdapter(LiveTelnetSpotSource):
    name = "dx_cluster"
    DEFAULT_HOST = DEFAULT_HOST
    DEFAULT_PORT = DEFAULT_PORT

    def __init__(
        self,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
        callsign: str = "",
        **kwargs,
    ):
        super().__init__(host=host, port=port, callsign=callsign, **kwargs)

    def parse_line(self, line: str) -> Spot | None:
        return parse_spot_line(line)
