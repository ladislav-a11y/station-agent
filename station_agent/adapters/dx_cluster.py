"""Živý DX Cluster adaptér nad sdíleným telnet klientem.

Parser podporuje standardní řádky ``DX de <SPOTTER>:`` i živý tabulkový
formát W3LPL. Dokud ze skutečného serveru nedorazí první platný spot,
zdroj zůstává ve stavu pending; nikdy jej nenahrazuje vymyšlenými daty.
"""

from __future__ import annotations

import re
import time

from station_agent.adapters._common import resolve_hhmm_timestamp
from station_agent.adapters.telnet_source import LiveTelnetSpotSource
from station_agent.bandplan import infer_mode_from_frequency
from station_agent.models import Spot


# Příklad řádku:
# "DX de OK1KT:     14195.0  JA1XYZ       SSB nice signal          1234Z"
_LINE_RE = re.compile(
    r"^\s*(?:DX de (?P<spotter>[A-Za-z0-9/]+):\s+)?"
    r"(?P<freq_khz>\d+(?:\.\d+)?)\s+"
    r"(?P<callsign>[A-Za-z0-9/]+)\s+"
    r"(?:(?P<date>\d{2}-[A-Za-z]{3}-\d{4})\s+)?"
    r"(?P<comment>.*?)\s+"
    r"(?P<hhmm>\d{4})Z(?:\s+<(?P<end_spotter>[^>]+)>)?\s*$"
)

_LIVE_LINE_RE = re.compile(
    r"^\s*(?P<freq_khz>\d+(?:\.\d+)?)\s+"
    r"(?P<callsign>[A-Za-z0-9/]+)\s+"
    r"(?P<date>\d{2}-[A-Za-z]{3}-\d{4})\s+"
    r"(?P<hhmm>\d{4})Z\s+"
    r"(?P<comment>.*?)"
    r"(?:\s+<(?P<end_spotter>[^>]+)>)?\s*$"
)

_MODE_KEYWORDS = ["FT8", "FT4", "PSK31", "PSK63", "RTTY", "CW", "USB", "LSB", "SSB", "JS8"]


def _extract_mode(comment: str) -> str:
    """Najde mód uvedený v komentáři; jinak vrátí prázdný řetězec."""
    upper = comment.upper()
    for keyword in _MODE_KEYWORDS:
        if re.search(rf"\b{re.escape(keyword)}\b", upper):
            return keyword
    return ""


def parse_spot_line(
    line: str,
    now: float | None = None,
    source_name: str = "dx_cluster",
) -> Spot | None:
    """Naparsuje jeden řádek DX clusteru, nebo vrátí ``None``."""
    now = time.time() if now is None else now
    clean_line = line.rstrip("\r\n\x07")
    match = _LINE_RE.match(clean_line) or _LIVE_LINE_RE.match(clean_line)
    if not match:
        return None
    freq_hz = int(round(float(match.group("freq_khz")) * 1000))
    comment = match.group("comment").strip()
    mode = _extract_mode(comment) or infer_mode_from_frequency(freq_hz)
    return Spot(
        callsign=match.group("callsign"),
        freq_hz=freq_hz,
        mode=mode,
        timestamp=resolve_hhmm_timestamp(match.group("hhmm"), now),
        source=source_name,
        comment=comment,
        spotter=match.groupdict().get("spotter") or match.groupdict().get("end_spotter") or "",
    )


DEFAULT_HOST = "dxc.w3lpl.net"
DEFAULT_PORT = 7373

# Ověřené veřejné full-feed DX Cluster uzly vhodné i pro SSB spoty. Jde o
# konfigurační katalog, nikoli automatický failover: operátor si každý živý
# zdroj musí výslovně zapnout a každý pak zůstává samostatnou evidencí.
RECOMMENDED_PROVIDERS: dict[str, tuple[str, int]] = {
    "dx_cluster": (DEFAULT_HOST, DEFAULT_PORT),
    "dx_cluster_hamserve": ("dxc.hamserve.uk", 7300),
    "dx_cluster_ea7jxh": ("dx.ea7jxh.eu", 7300),
    "dx_cluster_m0mhx": ("dxc.m0mhx.uk", 7300),
}


class DXClusterAdapter(LiveTelnetSpotSource):
    name = "dx_cluster"
    DEFAULT_HOST = DEFAULT_HOST
    DEFAULT_PORT = DEFAULT_PORT

    def __init__(
        self,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
        callsign: str = "",
        source_name: str = "dx_cluster",
        **kwargs,
    ):
        kwargs.pop("name", None)
        kwargs.pop("qth", None)
        kwargs.pop("qra", None)
        self.name = source_name
        super().__init__(host=host, port=port, callsign=callsign, post_login_command="sh/dx", **kwargs)

    def parse_line(self, line: str) -> Spot | None:
        return parse_spot_line(line, source_name=self.name)
