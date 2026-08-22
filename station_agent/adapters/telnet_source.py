"""Sdílený generický klient pro živé telnet streamovací zdroje spotů
(DX Cluster, Reverse Beacon Network).

Na rozdíl od PSKReporteru (jednoduché "HTTP GET -> XML" bez nutnosti
udržovaného spojení, viz ``pskreporter.py``) DX Cluster i RBN fungují jako
dlouho otevřené telnet relace, na kterých server průběžně streamuje řádky
se spoty. ``LiveTelnetSpotSource`` proto běží na vlastním daemon vlákně,
které:

1. Otevře reálný TCP socket na ``host``/``port``.
2. Pošle přihlašovací řádek s callsignem stanice -- naprostá většina
   veřejných AR-Cluster/CC-Cluster uzlů i telnet server RBN (viz
   https://www.reversebeacon.net/) očekává callsign jako první řádek po
   navázání spojení, bez ohledu na přesné znění uvítacího banneru/promptu
   (ten se uzel od uzlu liší, a spoléhat na jeho přesný text by bylo
   křehké). Tento přístup je standardní i pro jednoduché skriptovatelné
   telnet klienty k DX clusterům.
3. Čte řádek po řádku a každý předá injektované ``parse_line`` -- řádky,
   které nesedí na formát spotu (banner, echo příkazů, systémové zprávy),
   se tiše přeskočí (vrátí ``None``).
4. Při chybě/zavření spojení serverem se sama pokusí o reconnect
   s exponenciálním backoffem (nezávisle na ostatních zdrojích -- každý
   adaptér má vlastní vlákno a vlastní socket, takže výpadek jednoho
   adaptéru neovlivní ostatní).

``fetch()`` (volané z ``adapters/polling.py``) pouze vybere spoty
nashromážděné od posledního volání -- vlastní síťová smyčka běží nezávisle
na tom, jak často (nebo jestli vůbec) něco volá ``fetch()``. Dokud se
adaptéru nikdy nepodařilo navázat spojení a naparsovat aspoň jeden reálný
spot, ``fetch()`` vyhazuje ``SourceNotReadyError`` (GUI stav "pending").
Jakmile jednou dorazí reálná data, další výpadky spojení se hlásí jako
běžná výjimka (GUI stav "error") -- ne návrat k "pending".
"""

from __future__ import annotations

import logging
import socket
import threading
from collections import deque

from station_agent.adapters.base import SourceNotReadyError, SpotSource
from station_agent.models import Spot

logger = logging.getLogger(__name__)

DEFAULT_CONNECT_TIMEOUT_S = 15.0
DEFAULT_READ_TIMEOUT_S = 300.0
DEFAULT_RECONNECT_INITIAL_SECONDS = 5.0
DEFAULT_RECONNECT_MAX_SECONDS = 300.0


class LiveTelnetSpotSource(SpotSource):
    """Základ pro živé telnet zdroje. Podtřída nastaví ``name`` a
    implementuje ``parse_line(line: str) -> Spot | None``."""

    def __init__(
        self,
        host: str,
        port: int,
        callsign: str,
        connect_timeout_s: float = DEFAULT_CONNECT_TIMEOUT_S,
        read_timeout_s: float = DEFAULT_READ_TIMEOUT_S,
        reconnect_initial_seconds: float = DEFAULT_RECONNECT_INITIAL_SECONDS,
        reconnect_max_seconds: float = DEFAULT_RECONNECT_MAX_SECONDS,
    ):
        self.host = host
        self.port = port
        self.callsign = callsign
        self.connect_timeout_s = connect_timeout_s
        self.read_timeout_s = read_timeout_s
        self.reconnect_initial_seconds = reconnect_initial_seconds
        self.reconnect_max_seconds = reconnect_max_seconds

        self._lock = threading.Lock()
        self._queue: deque[Spot] = deque()
        self._ever_received_data = False
        self._last_error: str | None = None
        self._backoff_seconds = reconnect_initial_seconds
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._sock: socket.socket | None = None

    def parse_line(self, line: str) -> Spot | None:  # pragma: no cover - abstract
        raise NotImplementedError

    def _ensure_started(self) -> None:
        if self._thread is not None:
            return
        if not self.host or not self.port:
            raise SourceNotReadyError(f"{self.name}: host/port není nakonfigurován ({self.host!r}:{self.port!r})")
        if not self.callsign:
            raise SourceNotReadyError(f"{self.name}: station.callsign není nakonfigurován -- nutný pro přihlášení")
        self._thread = threading.Thread(target=self._run, name=f"station-agent-{self.name}", daemon=True)
        self._thread.start()

    def close(self) -> None:
        """Zastaví vlákno a uvolní socket -- volá se při vypnutí aplikace.

        Vlákno může být zrovna zablokované v blokujícím čtení ze socketu
        (až ``read_timeout_s``, výchozí 300 s) -- pouhé nastavení
        ``_stop_event`` by tedy nemuselo vlákno probudit včas. Proto se
        aktivní socket (pokud existuje) rovnou násilně zavře/shutdownuje --
        to vyvolá výjimku v běžící ``recv()`` prakticky okamžitě, ať už
        vlákno čeká na data, nebo je v backoff pauze mezi pokusy o
        opětovné připojení (tu přeruší ``_stop_event`` samo)."""
        self._stop_event.set()
        with self._lock:
            sock = self._sock
        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                sock.close()
            except OSError:
                pass
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None

    def fetch(self) -> list[Spot]:
        self._ensure_started()
        with self._lock:
            spots = list(self._queue)
            self._queue.clear()
            ever_received = self._ever_received_data
            error = self._last_error
        if not ever_received:
            raise SourceNotReadyError(
                error or f"{self.name}: čekám na první živá data z {self.host}:{self.port}"
            )
        if error and not spots:
            raise ConnectionError(error)
        return spots

    # -- vlastní síťová smyčka (běží na daemon vlákně) ----------------------

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                self._connect_once()
            except Exception as exc:  # síťová chyba/odpojení -- reconnect níže
                with self._lock:
                    self._last_error = str(exc)
                logger.warning(
                    "%s: spojení na %s:%d selhalo (%s), nový pokus za %.0f s",
                    self.name,
                    self.host,
                    self.port,
                    exc,
                    self._backoff_seconds,
                )
            if self._stop_event.is_set():
                break
            self._stop_event.wait(self._backoff_seconds)
            self._backoff_seconds = min(self._backoff_seconds * 2, self.reconnect_max_seconds)

    def _connect_once(self) -> None:
        sock = socket.create_connection((self.host, self.port), timeout=self.connect_timeout_s)
        with self._lock:
            self._sock = sock
        file_obj = None
        try:
            sock.settimeout(self.read_timeout_s)
            sock.sendall(f"{self.callsign}\r\n".encode("ascii", errors="ignore"))
            file_obj = sock.makefile("r", encoding="utf-8", errors="replace", newline="\n")
            # Úspěšné připojení + odeslání loginu -- reset backoffu a chyby,
            # i kdyby ještě nedorazil žádný rozpoznatelný spot.
            with self._lock:
                self._backoff_seconds = self.reconnect_initial_seconds
                self._last_error = None
            for raw_line in file_obj:
                if self._stop_event.is_set():
                    return
                spot = self.parse_line(raw_line)
                if spot is not None:
                    with self._lock:
                        self._queue.append(spot)
                        self._ever_received_data = True
            raise ConnectionError(f"{self.name}: server {self.host}:{self.port} ukončil spojení")
        finally:
            with self._lock:
                if self._sock is sock:
                    self._sock = None
            # POZOR: socket.makefile() interně inkrementuje refcount
            # (_io_refs) podkladového socketu -- dokud se ``file_obj``
            # výslovně nezavře, ``sock.close()`` níže NENÍ skutečný OS
            # close (nepošle FIN druhé straně). ``file_obj`` je jinak jen
            # lokální proměnná uvolněná až GC při návratu z této metody,
            # což je pro deterministické/rychlé odpojení nespolehlivé.
            if file_obj is not None:
                file_obj.close()
            sock.close()
