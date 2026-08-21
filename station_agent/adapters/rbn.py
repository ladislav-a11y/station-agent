"""Reverse Beacon Network (telnet) adaptér.

Stejně jako u DX Clusteru (viz dx_cluster.py) je parsování řádku plně
implementované a testované na fixture datech. Živé telnet spojení na
telnet.reversebeacon.net NENÍ implementováno (PENDING) -- viz README.md
"Stav externích zdrojů" a AGENTS.md pravidlo 6.
"""

from __future__ import annotations

import re
import time

from station_agent.adapters._common import resolve_hhmm_timestamp
from station_agent.adapters.base import PendingSpotSource
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


class RBNAdapter(PendingSpotSource):
    name = "rbn"
    pending_reason = (
        "Telnet klient na telnet.reversebeacon.net nebyl implementován/ověřen. "
        "Parser řádků (parse_rbn_line) je funkční a otestovaný na fixture datech."
    )

    def __init__(self, host: str = "", port: int = 7000):
        self.host = host
        self.port = port
