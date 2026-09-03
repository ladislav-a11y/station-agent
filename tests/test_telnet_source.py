"""Ověřuje ``LiveTelnetSpotSource`` (station_agent/adapters/telnet_source.py)
a na něm postavené ``DXClusterAdapter``/``RBNAdapter`` proti skutečnému
lokálnímu TCP serveru.

Stejně jako u PSKReporteru (viz tests/test_adapters_live.py) jde o reálný
socket round-trip po loopbacku -- žádná data se nefalšují uvnitř procesu,
testuje se opravdový TCP klient (connect, login řádek, čtení řádek po
řádku, reconnect po zavření spojení serverem), jen mířený na lokální
testovací server místo skutečného DX clusteru/RBN, aby testy běžely bez
internetu (AGENTS.md "Testy běží bez internetu").
"""

from __future__ import annotations

import socket
import threading
import time
import unittest

from station_agent.adapters.base import SourceNotReadyError
from station_agent.adapters.dx_cluster import DXClusterAdapter
from station_agent.adapters.rbn import RBNAdapter
from station_agent.adapters.telnet_source import LiveTelnetSpotSource
from station_agent.models import Spot


def _wait_until(predicate, timeout: float = 5.0, interval: float = 0.02) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


class _FakeTelnetServer:
    """Skutečný TCP server na 127.0.0.1:<náhodný port> -- zaznamená
    přihlašovací řádek a odešle nakonfigurované řádky. Po odeslání buď
    spojení zavře (simulace výpadku uzlu -> reconnect), nebo ho drží
    otevřené (simulace dlouhotrvající streamovací relace)."""

    def __init__(self, lines_per_connection=None, keep_open: bool = False):
        self._lines_per_connection = list(lines_per_connection or [])
        self._keep_open = keep_open
        self._server_sock = socket.create_server(("127.0.0.1", 0))
        self._server_sock.settimeout(1.0)
        self.host, self.port = self._server_sock.getsockname()
        self.logins: list[str] = []
        self.connection_count = 0
        self._stop = threading.Event()
        self._open_conns: list[socket.socket] = []
        self._lock = threading.Lock()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                conn, _ = self._server_sock.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            with self._lock:
                self.connection_count += 1
            conn.settimeout(5.0)
            try:
                # POZOR: socket.makefile() interně inkrementuje refcount
                # (_io_refs) podkladového socketu -- dokud se vrácený file
                # objekt výslovně nezavře, pozdější conn.close() níže NENÍ
                # skutečný OS close (nepošle FIN) a klient by na druhé
                # straně čekal na EOF donekonečna (reálně until
                # read_timeout_s, 300 s). Proto se `f` zavírá hned po
                # přečtení login řádku, ne až se zahodí jako lokální
                # proměnná.
                f = conn.makefile("r", encoding="utf-8", errors="replace", newline="\n")
                try:
                    login = f.readline()
                finally:
                    f.close()
                with self._lock:
                    self.logins.append(login.strip())
                lines = self._lines_per_connection.pop(0) if self._lines_per_connection else []
                for line in lines:
                    conn.sendall((line + "\r\n").encode("utf-8"))
                if self._keep_open:
                    with self._lock:
                        self._open_conns.append(conn)
                    continue
                # ``sendall(); close()`` může na Windows skončit RST dřív,
                # než klient převezme právě odeslanou poslední dávku. To
                # nedeterministicky zahodí testovací spot a delší čekání už
                # nemůže pomoci. Half-close garantuje data -> EOF; klient
                # stále pozoruje skutečné ukončení streamu a otestuje tutéž
                # reconnect/error větev jako při běžném FIN od serveru.
                conn.shutdown(socket.SHUT_WR)
            except OSError:
                pass
            conn.close()

    def stop(self) -> None:
        self._stop.set()
        with self._lock:
            conns = list(self._open_conns)
            self._open_conns.clear()
        for conn in conns:
            try:
                conn.close()
            except OSError:
                pass
        self._server_sock.close()
        self._thread.join(timeout=5)


class LiveTelnetSpotSourceHandshakeTests(unittest.TestCase):
    def test_sends_callsign_as_login_line(self):
        server = _FakeTelnetServer(lines_per_connection=[[]], keep_open=True)
        try:
            source = DXClusterAdapter(host=server.host, port=server.port, callsign="OK1RPL")
            with self.assertRaises(SourceNotReadyError):
                source.fetch()
            self.assertTrue(_wait_until(lambda: len(server.logins) >= 1))
            self.assertEqual(server.logins[0], "OK1RPL")
        finally:
            server.stop()
            source.close()

    def test_fetch_raises_source_not_ready_before_first_real_data(self):
        server = _FakeTelnetServer(lines_per_connection=[[]], keep_open=True)
        try:
            source = DXClusterAdapter(host=server.host, port=server.port, callsign="OK1RPL")
            with self.assertRaises(SourceNotReadyError):
                source.fetch()
        finally:
            server.stop()
            source.close()

    def test_connected_source_becomes_ready_immediately_without_spot(self):
        server = _FakeTelnetServer(lines_per_connection=[[]], keep_open=True)
        try:
            source = DXClusterAdapter(
                host=server.host,
                port=server.port,
                callsign="OK1RPL",
                startup_grace_seconds=180.0,
            )
            with self.assertRaises(SourceNotReadyError):
                source.fetch()
            self.assertTrue(_wait_until(lambda: len(server.logins) >= 1))

            # Spojení je navázané a login odeslaný -- zdroj musí přejít na
            # "ok" hned, BEZ čekání na uplynutí startovní grace period
            # (ta se uplatní jen pro cestu "spojení se nikdy nepodařilo
            # navázat" -- viz test_connection_failure_is_error_after_startup_grace).
            deadline = time.time() + 5.0
            result = None
            while time.time() < deadline:
                try:
                    result = source.fetch()
                except SourceNotReadyError:
                    time.sleep(0.02)
                    continue
                break
            self.assertEqual(result, [])
        finally:
            server.stop()
            source.close()

    def test_connection_failure_is_error_after_startup_grace(self):
        source = RBNAdapter(
            host="127.0.0.1",
            port=1,
            callsign="OK1RPL",
            startup_grace_seconds=180.0,
            reconnect_initial_seconds=30.0,
        )
        try:
            with self.assertRaises(SourceNotReadyError):
                source.fetch()
            self.assertTrue(_wait_until(lambda: source._last_error is not None))
            source._started_at -= 181.0
            with self.assertRaises(ConnectionError):
                source.fetch()
        finally:
            source.close()


def _fetch_until_nonempty(source, timeout: float = 20.0) -> list[Spot]:
    """Volá fetch() dokud nedorazí neprázdná dávka spotů, nebo nevyprší
    timeout -- ``SourceNotReadyError`` mezitím značí, že vlákno ještě
    čeká na první data ze síťové smyčky (viz LiveTelnetSpotSource.fetch).

    20 s (ne dřívějších 10 s) ze stejného důvodu jako u ``_wait_until``
    volání níže v tomto souboru -- pod zátěží celé test suite (stovky
    dalších testů, real sockets/threads) může první connect+login+parse
    trvat déle, než když test běží izolovaně; rychlá cesta se timeoutem
    vůbec neprodlužuje, vrací se hned po příchodu dat."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            spots = source.fetch()
        except SourceNotReadyError:
            spots = []
        if spots:
            return spots
        time.sleep(0.02)
    return []


class LiveTelnetSpotSourceParsingTests(unittest.TestCase):
    def test_dx_cluster_adapter_parses_real_stream_into_spots(self):
        line = "DX de OK1KT:     14195.0  JA1XYZ       SSB nice signal          1234Z"
        server = _FakeTelnetServer(lines_per_connection=[[line]], keep_open=True)
        try:
            source = DXClusterAdapter(host=server.host, port=server.port, callsign="OK1RPL")
            spots = _fetch_until_nonempty(source)
            self.assertEqual(len(spots), 1)
            self.assertEqual(spots[0].callsign, "JA1XYZ")
            self.assertEqual(spots[0].source, "dx_cluster")
            self.assertEqual(spots[0].mode, "SSB")
        finally:
            server.stop()
            source.close()

    def test_rbn_adapter_parses_real_stream_into_spots(self):
        line = "DX de RBN-1-#:    7024.3  DL1ABC       CW    12 dB  25 WPM  CQ      1200Z"
        server = _FakeTelnetServer(lines_per_connection=[[line]], keep_open=True)
        try:
            source = RBNAdapter(host=server.host, port=server.port, callsign="OK1RPL")
            spots = _fetch_until_nonempty(source)
            self.assertEqual(len(spots), 1)
            self.assertEqual(spots[0].callsign, "DL1ABC")
            self.assertEqual(spots[0].source, "rbn")
            self.assertEqual(spots[0].mode, "CW")
        finally:
            server.stop()
            source.close()

    def test_lines_not_matching_format_are_silently_skipped(self):
        server = _FakeTelnetServer(
            lines_per_connection=[["*** connected to node ***", "not a spot line"]], keep_open=True
        )
        try:
            source = DXClusterAdapter(host=server.host, port=server.port, callsign="OK1RPL")
            # Síťové vlákno se spouští líně, až prvním fetch() (viz
            # LiveTelnetSpotSource._ensure_started) -- bez tohoto volání by
            # server nikdy nepřijal žádné spojení a čekání na
            # connection_count níže by vždy vypršelo časovým limitem.
            with self.assertRaises(SourceNotReadyError):
                source.fetch()
            self.assertTrue(_wait_until(lambda: server.connection_count >= 1))

            # Garbage řádky se tiše zahodí (parse_line vrátí None), ale
            # spojení samo je navázané -- zdroj proto musí přejít na "ok"
            # (fetch() vrací prázdný seznam), NE zůstat v "pending" jen
            # proto, že ještě nedorazil rozpoznatelný spot.
            deadline = time.time() + 5.0
            result = None
            while time.time() < deadline:
                try:
                    result = source.fetch()
                except SourceNotReadyError:
                    time.sleep(0.02)
                    continue
                break
            self.assertEqual(result, [])
        finally:
            server.stop()
            source.close()


class LiveTelnetSpotSourceReconnectTests(unittest.TestCase):
    def test_reconnects_after_server_closes_connection(self):
        line1 = "DX de OK1KT:     14195.0  JA1XYZ       SSB first             1234Z"
        line2 = "DX de OK1KT:     14195.0  JA1XYZ       SSB second            1235Z"
        server = _FakeTelnetServer(lines_per_connection=[[line1], [line2]], keep_open=False)
        try:
            source = DXClusterAdapter(
                host=server.host,
                port=server.port,
                callsign="OK1RPL",
                reconnect_initial_seconds=0.05,
                reconnect_max_seconds=0.2,
            )
            # Síťové vlákno se spouští líně, až prvním fetch() (viz
            # LiveTelnetSpotSource._ensure_started) -- bez tohoto volání by
            # se adapter nikdy nepřipojil a čekání na druhé spojení níže by
            # vždy vypršelo časovým limitem.
            _fetch_until_nonempty(source)
            # Čeká se přímo na server.logins (ne na connection_count) --
            # connection_count se inkrementuje hned po accept(), ještě před
            # přečtením login řádku, takže "connection_count >= 2" může být
            # pravda dřív, než druhé spojení stihlo login vůbec doručit/
            # zpracovat (reálně pozorovaná race: 2 spojení accepted, jen 1
            # login zapsaný). server.logins je skutečný signál dokončení.
            # Velkorysý timeout je jen bezpečnostní strop pro běh pod
            # zátěží celé test suite -- test vrací výsledek hned po splnění
            # podmínky, takže neprodlužuje běžný (rychlý) případ.
            self.assertTrue(_wait_until(lambda: len(server.logins) >= 2, timeout=20.0))
            self.assertGreaterEqual(server.connection_count, 2)
            self.assertEqual(server.logins[0], "OK1RPL")
            self.assertEqual(server.logins[1], "OK1RPL")
        finally:
            server.stop()
            source.close()

    def test_status_becomes_error_after_disconnect_once_data_seen(self):
        line = "DX de OK1KT:     14195.0  JA1XYZ       SSB nice signal          1234Z"
        server = _FakeTelnetServer(lines_per_connection=[[line]], keep_open=False)
        try:
            source = DXClusterAdapter(
                host=server.host,
                port=server.port,
                callsign="OK1RPL",
                reconnect_initial_seconds=30.0,
                reconnect_max_seconds=30.0,
            )
            spots = _fetch_until_nonempty(source)
            self.assertEqual(len(spots), 1, "první reálný spot musí dorazit")

            # server po odeslání první dávky spojení zavřel -- adapter to
            # musí ohlásit jako běžnou chybu (GUI "error"), NE zpátky na
            # "pending" (ten stav patří jen situaci "nikdy nedorazila
            # žádná reálná data").
            def _errors_after_disconnect():
                try:
                    source.fetch()
                except SourceNotReadyError:
                    return False
                except Exception:
                    return True
                return False

            # Timeout musí zůstat bezpečně pod reconnect_initial_seconds
            # (30 s) -- jinak by test místo detekce chyby náhodou zachytil
            # už druhý (rychlejší) reconnect a nic by neověřil. 30/20 s
            # (místo dřívějších 10/8 s) dává rezervu proti zpoždění
            # plánovače OS/GIL při běhu celé test suite -- viz komentář u
            # LiveTelnetSpotSourceReconnectTests.test_reconnects_after_server_closes_connection.
            self.assertTrue(_wait_until(_errors_after_disconnect, timeout=20.0))
        finally:
            server.stop()
            source.close()


class LiveTelnetSpotSourceIndependenceTests(unittest.TestCase):
    """Výpadek jednoho zdroje (neexistující/nedostupný server) nesmí
    ovlivnit jiný, nezávisle běžící zdroj (vlastní vlákno a socket)."""

    def test_unreachable_source_does_not_block_a_working_one(self):
        line = "DX de RBN-1-#:    7024.3  DL1ABC       CW    12 dB  25 WPM  CQ      1200Z"
        good_server = _FakeTelnetServer(lines_per_connection=[[line]], keep_open=True)
        # port 1 na loopbacku by měl spojení hned odmítnout (ECONNREFUSED).
        broken = DXClusterAdapter(host="127.0.0.1", port=1, callsign="OK1RPL")
        good = RBNAdapter(host=good_server.host, port=good_server.port, callsign="OK1RPL")
        try:
            with self.assertRaises(SourceNotReadyError):
                broken.fetch()

            spots = _fetch_until_nonempty(good)
            self.assertEqual(len(spots), 1)

            with self.assertRaises(SourceNotReadyError):
                broken.fetch()
        finally:
            good_server.stop()
            broken.close()
            good.close()


class LiveTelnetSpotSourceConfigValidationTests(unittest.TestCase):
    def test_missing_host_raises_source_not_ready_without_starting_thread(self):
        source = DXClusterAdapter(host="", port=7373, callsign="OK1RPL")
        with self.assertRaises(SourceNotReadyError):
            source.fetch()
        self.assertIsNone(source._thread)

    def test_missing_callsign_raises_source_not_ready_without_starting_thread(self):
        source = DXClusterAdapter(host="dxc.example.net", port=7373, callsign="")
        with self.assertRaises(SourceNotReadyError):
            source.fetch()
        self.assertIsNone(source._thread)

    def test_base_class_requires_parse_line_override(self):
        source = LiveTelnetSpotSource(host="x", port=1, callsign="OK1RPL")
        with self.assertRaises(NotImplementedError):
            source.parse_line("anything")


if __name__ == "__main__":
    unittest.main()
