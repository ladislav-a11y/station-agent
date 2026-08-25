"""DX Cluster (telnet) adaptĂ©r.



ParsovĂˇnĂ­ standardnĂ­ho Ĺ™Ăˇdku DX clusteru (formĂˇt "DX de <SPOTTER>:") je

plnÄ› implementovanĂ© a testovanĂ© na fixture datech -- viz

``tests/test_adapters_parsing.py``. Ĺ˝ivĂ© telnet spojenĂ­ pouĹľĂ­vĂˇ sdĂ­lenĂ˝

generickĂ˝ klient ``LiveTelnetSpotSource`` (``adapters/telnet_source.py``) --

skuteÄŤnĂ˝ TCP socket, login callsignem, ÄŤtenĂ­ Ĺ™ĂˇdkĹŻ a reconnect/backoff

nezĂˇvislĂ˝ na ostatnĂ­ch zdrojĂ­ch. ``fetch()`` vyhazuje ``SourceNotReadyError``

(GUI stav "pending"), dokud adaptĂ©r poprvĂ© skuteÄŤnÄ› nenavĂˇĹľe spojenĂ­ a

nenaparsuje aspoĹ jeden reĂˇlnĂ˝ spot -- viz README.md "Stav externĂ­ch

zdrojĹŻ" a AGENTS.md pravidlo 6 ("NefalĹˇuj externĂ­ sluĹľby").



VĂ˝chozĂ­ ``host``/``port`` (``DEFAULT_HOST``/``DEFAULT_PORT``) ukazujĂ­ na

bÄ›ĹľnÄ› pouĹľĂ­vanĂ˝ veĹ™ejnĂ˝ AR-Cluster uzel (telnet pĹ™Ă­stupnĂ˝ bez hesla, jen

s pĹ™ihlĂˇĹˇenĂ­m callsignem) -- operĂˇtor si v ``config.yaml`` mĹŻĹľe nastavit

jinĂ˝, typicky geograficky bliĹľĹˇĂ­ cluster; seznam veĹ™ejnĂ˝ch uzlĹŻ viz

https://www.ng3k.com/Misc/cluster.html.

"""



from __future__ import annotations



import re

import time



from station_agent.adapters._common import resolve_hhmm_timestamp

from station_agent.adapters.telnet_source import LiveTelnetSpotSource

from station_agent.models import Spot



# PĹ™Ă­klad Ĺ™Ăˇdku:

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

    """ZkusĂ­ najĂ­t mĂłd v komentĂˇĹ™i spotu. DX cluster formĂˇt mĂłd

    nevyĹľaduje, takĹľe spotteĹ™i ho ÄŤasto (ne)zapisujĂ­ do komentĂˇĹ™e --

    pokud tam nenĂ­, vracĂ­ se prĂˇzdnĂ˝ Ĺ™etÄ›zec (-> normalizuje se na

    OTHER_DIGITAL). Toto je zdokumentovanĂ© omezenĂ­ textovĂ©ho formĂˇtu.

    """

    upper = comment.upper()

    for keyword in _MODE_KEYWORDS:

        if re.search(rf"\b{re.escape(keyword)}\b", upper):

            return keyword

    return ""





def parse_spot_line(line: str, now: float | None = None) -> Spot | None:

    """Naparsuje jeden Ĺ™Ăˇdek DX clusteru na Spot, nebo None pokud nesedĂ­ formĂˇt."""

    now = time.time() if now is None else now

    match = _LINE_RE.match(line.rstrip("\r\n")) or _LIVE_LINE_RE.match(line.rstrip("\r\n"))

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

        spotter=match.groupdict().get("spotter") or match.groupdict().get("end_spotter") or "",

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

        kwargs.pop("name", None)

        kwargs.pop("qth", None)

        kwargs.pop("qra", None)

        super().__init__(host=host, port=port, callsign=callsign, post_login_command="sh/dx", **kwargs)



    def parse_line(self, line: str) -> Spot | None:

        return parse_spot_line(line)



