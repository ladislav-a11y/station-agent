"""Log4OM2 integrace -- POUZE předvyplnění řádku v deníku, nikdy uložení QSO.

Sestavení "prefill" payloadu (funkce ``build_prefill_fields`` a
``build_prefill_xml``) je čistá, plně testovaná logika. Odeslání UDP
paketu (``send_prefill``) je funkční kód nad stdlib socketem (testovaný
proti lokálnímu UDP listeneru v tests/test_log4om.py), ale formát je
navržený podle veřejně známého "click to tune" broadcast stylu (kompatibilní
s N1MM-style spot packetem, který Log4OM2 umí přijímat) a NEBYL ověřen proti
běžící instanci Log4OM2 -- viz README.md "Stav externích zdrojů". Endpoint
je v configu defaultně ``enabled: false``.

Tento modul záměrně NEOBSAHUJE žádnou funkci, která by QSO ukládala nebo
potvrzovala v deníku -- to musí vždy udělat operátor ručně v Log4OM2.
"""

from __future__ import annotations

import socket
from xml.sax.saxutils import escape

from station_agent.models import Candidate


def build_prefill_fields(candidate: Candidate, station_callsign: str = "") -> dict[str, str]:
    """Sestaví slovník polí pro předvyplnění řádku v deníku (žádné uložení)."""
    fields = {
        "app": "StationAgent",
        "purpose": "prefill-only",
        "operator_call": station_callsign,
        "dx_call": candidate.callsign,
        "frequency_mhz": f"{candidate.freq_hz / 1_000_000:.6f}",
        "band": candidate.band,
        "mode": candidate.mode,
        "dxcc": candidate.dxcc.name if candidate.dxcc else "",
        "bearing_deg": f"{candidate.bearing_deg:.0f}" if candidate.bearing_deg is not None else "",
    }
    return fields


def build_prefill_xml(fields: dict[str, str]) -> str:
    """Serializuje prefill pole do jednoduchého XML packetu ("spot" styl).

    Formát je vědomě jednoduchý a lidsky čitelný; hlavní pole (dxcall,
    frequency, mode) odpovídají běžné konvenci "click to tune" spot
    packetů. Neobsahuje žádné pole pro potvrzení/uložení QSO.
    """
    parts = ["<spot>"]
    for key, value in fields.items():
        parts.append(f"<{key}>{escape(str(value))}</{key}>")
    parts.append("</spot>")
    return "".join(parts)


def send_prefill(xml_payload: str, host: str, port: int, timeout: float = 2.0) -> int:
    """Odešle prefill XML jako jeden UDP packet. Vrací počet odeslaných bajtů.

    UDP je "fire and forget" -- nečeká se na potvrzení od Log4OM2 a nic se
    tím v deníku neukládá, pouze (case-by-case, dle nastavení Log4OM2)
    předvyplní rozpracovaný řádek pro operátora.
    """
    payload = xml_payload.encode("utf-8")
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.settimeout(timeout)
        return sock.sendto(payload, (host, port))


class Log4OMBridge:
    """Pending-verifikace bridge pro Log4OM2 prefill (viz docstring modulu)."""

    def __init__(self, host: str, port: int, station_callsign: str = ""):
        self.host = host
        self.port = port
        self.station_callsign = station_callsign

    def prefill(self, candidate: Candidate) -> int:
        fields = build_prefill_fields(candidate, self.station_callsign)
        xml_payload = build_prefill_xml(fields)
        return send_prefill(xml_payload, self.host, self.port)
