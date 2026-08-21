"""DX Cluster (telnet) adaptér.

Parsování standardního řádku DX clusteru (formát "DX de <SPOTTER>:") je
plně implementované a testované na fixture datech -- viz
``tests/test_adapters_parsing.py``. Živé telnet spojení na reálný cluster
NENÍ implementováno (PENDING), protože ho nejde ověřit bez skutečné sítě a
reálného serveru -- viz README.md "Stav externích zdrojů" a AGENTS.md
pravidlo 6 ("Nefalšuj externí služby").
"""

from __future__ import annotations

import re
import time

from station_agent.adapters._common import resolve_hhmm_timestamp
from station_agent.adapters.base import PendingSpotSource
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


class DXClusterAdapter(PendingSpotSource):
    name = "dx_cluster"
    pending_reason = (
        "Telnet klient na reálný DX cluster server nebyl implementován/ověřen. "
        "Parser řádků (parse_spot_line) je funkční a otestovaný na fixture datech."
    )

    def __init__(self, host: str = "", port: int = 7300):
        self.host = host
        self.port = port
