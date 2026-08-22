"""Reverse Beacon Network (telnet) adaptér.

Stejně jako u DX Clusteru (viz dx_cluster.py) je parsování řádku plně
implementované a testované na fixture datech. Živé telnet spojení na
oficiální agregovaný telnet server RBN (``telnet.reversebeacon.net:7000``,
viz https://www.reversebeacon.net/pages/telnet) používá stejný sdílený
generický klient ``LiveTelnetSpotSource`` jako DX Cluster -- skutečný TCP
socket, login callsignem, čtení řádků a vlastní reconnect/backoff nezávislý
na ostatních zdrojích. ``fetch()`` vyhazuje ``SourceNotReadyError`` (GUI
stav "pending"), dokud adaptér poprvé skutečně nenaváže spojení a
nenaparsuje aspoň jeden reálný spot -- viz README.md "Stav externích
zdrojů" a AGENTS.md pravidlo 6.
"""

from __future__ import annotations

import re
import time

from station_agent.adapters._common import resolve_hhmm_timestamp
from station_agent.adapters.telnet_source import LiveTelnetSpotSource
from station_agent.models import Spot

# Příklad řádku RBN skimmeru:
# "DX de RBN-1-#:    7024.3  DL1ABC       CW    12 dB  25 WPM  CQ      1200Z"
_LINE_RE = re.compile(
    r"^DX de (?P<spotter>[A-Za-z0-9/#\-]+):\s+"
    r"(?P<freq_khz>\d+(?:\.\d+)?)\s+"
    r"(?P<callsign>[A-Za-z0-9/]+)\s+"
    r"(?P<mode>CW|RTTY|FT8|FT4|PSK\d*)\s+"
    r"(?P<snr>\d+)\s*dB"
    r"(?P<rest>.*?)\s*"
    r"(?P<hhmm>\d{4})Z\s*$"
)


def parse_rbn_line(line: str, now: float | None = None) -> Spot | None:
    """Naparsuje jeden řádek RBN skimmeru na Spot, nebo None pokud nesedí formát."""
    now = time.time() if now is None else now
    match = _LINE_RE.match(line.rstrip("\r\n"))
    if not match:
        return None
    freq_hz = int(round(float(match.group("freq_khz")) * 1000))
    return Spot(
        callsign=match.group("callsign"),
        freq_hz=freq_hz,
        mode=match.group("mode"),
        timestamp=resolve_hhmm_timestamp(match.group("hhmm"), now),
        source="rbn",
        snr_db=float(match.group("snr")),
        comment=match.group("rest").strip(),
        spotter=match.group("spotter"),
    )


DEFAULT_HOST = "telnet.reversebeacon.net"
DEFAULT_PORT = 7000


class RBNAdapter(LiveTelnetSpotSource):
    name = "rbn"
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
        return parse_rbn_line(line)
