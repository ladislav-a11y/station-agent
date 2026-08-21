"""Reálný TCP klient pro Hamlib ``rigctld`` (textový protokol).

Implementuje výhradně čtení/nastavení frekvence a módu -- žádný jiný
příkaz (a tedy ani zapnutí vysílání) není a nesmí být implementován, viz
AGENTS.md pravidlo 1. Protokol rigctld je stabilní a dobře zdokumentovaný,
takže je (na rozdíl od DX Cluster/RBN/PSKReporter, viz adapters/) plně
implementovaný -- otestovaný proti lokálnímu fake TCP serveru v
tests/test_rig_rigctld.py, protože reálný rigctld/IC-7300 nejde v CI mít
k dispozici.
"""

from __future__ import annotations

import socket

from station_agent.modes import normalize_mode
from station_agent.rig.base import RigControl

# Mapování našich normalizovaných módů na Hamlib/rigctld mód jména.
# Digitální módy (FT8/FT4/PSK31/PSK63/OTHER_DIGITAL) se na IC-7300 typicky
# provozují v datovém USB módu (PKTUSB) -- operátor si toto mapování může
# v budoucnu zpřístupnit v configu, pokud potřebuje jinak.
_TO_RIGCTLD_MODE = {
    "SSB": "USB",
    "CW": "CW",
    "RTTY": "RTTY",
    "FT8": "PKTUSB",
    "FT4": "PKTUSB",
    "PSK31": "PKTUSB",
    "PSK63": "PKTUSB",
    "OTHER_DIGITAL": "PKTUSB",
}
_FROM_RIGCTLD_MODE = {
    "USB": "SSB",
    "LSB": "SSB",
    "CW": "CW",
    "CWR": "CW",
    "RTTY": "RTTY",
    "RTTYR": "RTTY",
    "PKTUSB": "OTHER_DIGITAL",
    "PKTLSB": "OTHER_DIGITAL",
}


class RigctldError(RuntimeError):
    pass


class RigctldClient(RigControl):
    def __init__(self, host: str, port: int, timeout: float = 5.0):
        self.host = host
        self.port = port
        self.timeout = timeout
        self._sock: socket.socket | None = None

    # -- spojení -----------------------------------------------------------

    def _ensure_connected(self) -> socket.socket:
        if self._sock is None:
            sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
            sock.settimeout(self.timeout)
            self._sock = sock
        return self._sock

    def close(self) -> None:
        if self._sock is not None:
            try:
                self._sock.close()
            finally:
                self._sock = None

    def _command(self, cmd: str, expected_lines: int) -> list[str]:
        sock = self._ensure_connected()
        sock.sendall((cmd.strip() + "\n").encode("ascii"))
        buf = b""
        lines: list[str] = []
        while len(lines) < expected_lines:
            chunk = sock.recv(4096)
            if not chunk:
                break
            buf += chunk
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                lines.append(line.decode("ascii", errors="replace").strip())
        return lines

    # -- veřejné rozhraní ----------------------------------------------------

    def get_frequency(self) -> int:
        lines = self._command("f", expected_lines=1)
        if not lines:
            raise RigctldError("rigctld nevrátil odpověď na příkaz 'f'")
        return int(float(lines[0]))

    def get_mode(self) -> str:
        # rigctld na "m" vrací dva řádky: název módu a šířku pásma (Hz).
        lines = self._command("m", expected_lines=2)
        if not lines:
            raise RigctldError("rigctld nevrátil odpověď na příkaz 'm'")
        raw_mode = lines[0]
        return _FROM_RIGCTLD_MODE.get(raw_mode, normalize_mode(raw_mode))

    def set_frequency(self, freq_hz: int) -> None:
        lines = self._command(f"F {int(freq_hz)}", expected_lines=1)
        _raise_on_error(lines, f"set_frequency({freq_hz})")

    def set_mode(self, mode: str, passband_hz: int = 0) -> None:
        rig_mode = _TO_RIGCTLD_MODE.get(mode, "PKTUSB")
        lines = self._command(f"M {rig_mode} {passband_hz}", expected_lines=1)
        _raise_on_error(lines, f"set_mode({mode})")


def _raise_on_error(lines: list[str], context: str) -> None:
    if not lines:
        raise RigctldError(f"rigctld nevrátil odpověď na {context}")
    reply = lines[0]
    if reply.startswith("RPRT"):
        code = reply.split()[-1]
        if code != "0":
            raise RigctldError(f"rigctld vrátil chybu na {context}: {reply}")
