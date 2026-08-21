"""Testuje RigctldClient proti lokálnímu fake rigctld TCP serveru.

Reálný rigctld/IC-7300 v testovacím prostředí není k dispozici, ale
protokol je jednoduchý a stabilní -- tento fake server implementuje jen
příkazy 'f'/'F'/'m'/'M' (frekvence/mód), stejně jako skutečný RigctldClient
umí jen tyto -- viz station_agent/rig/rigctld.py a AGENTS.md pravidlo 1
(žádný PTT příkaz nikde neexistuje).
"""

from __future__ import annotations

import socket
import threading
import unittest

from station_agent.rig.rigctld import RigctldClient, RigctldError


class FakeRigctldServer(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(1)
        self.port = self.sock.getsockname()[1]
        self.freq = 14_200_000
        self.mode = "USB"
        self.passband = 2400
        self.fail_next = False
        self._stop = False

    def run(self) -> None:
        self.sock.settimeout(0.5)
        while not self._stop:
            try:
                conn, _ = self.sock.accept()
            except OSError:
                continue
            with conn:
                conn.settimeout(2)
                buf = b""
                while not self._stop:
                    try:
                        chunk = conn.recv(4096)
                    except OSError:
                        break
                    if not chunk:
                        break
                    buf += chunk
                    while b"\n" in buf:
                        line, buf = buf.split(b"\n", 1)
                        self._handle(conn, line.decode("ascii").strip())

    def _handle(self, conn: socket.socket, cmd: str) -> None:
        if cmd == "f":
            conn.sendall(f"{self.freq}\n".encode())
        elif cmd.startswith("F "):
            if self.fail_next:
                self.fail_next = False
                conn.sendall(b"RPRT -1\n")
                return
            self.freq = int(cmd.split()[1])
            conn.sendall(b"RPRT 0\n")
        elif cmd == "m":
            conn.sendall(f"{self.mode}\n{self.passband}\n".encode())
        elif cmd.startswith("M "):
            if self.fail_next:
                self.fail_next = False
                conn.sendall(b"RPRT -1\n")
                return
            parts = cmd.split()
            self.mode = parts[1]
            if len(parts) > 2:
                self.passband = int(parts[2])
            conn.sendall(b"RPRT 0\n")
        else:
            conn.sendall(b"RPRT -1\n")

    def stop(self) -> None:
        self._stop = True
        self.sock.close()


class RigctldClientTests(unittest.TestCase):
    def setUp(self):
        self.server = FakeRigctldServer()
        self.server.start()
        self.client = RigctldClient("127.0.0.1", self.server.port, timeout=2)

    def tearDown(self):
        self.client.close()
        self.server.stop()
        self.server.join(timeout=2)

    def test_get_frequency(self):
        self.assertEqual(self.client.get_frequency(), 14_200_000)

    def test_set_and_get_frequency(self):
        self.client.set_frequency(7_030_000)
        self.assertEqual(self.server.freq, 7_030_000)
        self.assertEqual(self.client.get_frequency(), 7_030_000)

    def test_get_mode_maps_rigctld_names(self):
        self.assertEqual(self.client.get_mode(), "SSB")  # server default "USB"

    def test_set_mode_maps_our_names_to_rigctld(self):
        self.client.set_mode("FT8")
        self.assertEqual(self.server.mode, "PKTUSB")
        self.client.set_mode("CW")
        self.assertEqual(self.server.mode, "CW")

    def test_set_frequency_error_raises(self):
        self.server.fail_next = True
        with self.assertRaises(RigctldError):
            self.client.set_frequency(1_000_000)

    def test_no_ptt_capable_methods_exist(self):
        public_methods = {name for name in dir(self.client) if not name.startswith("_")}
        self.assertTrue(all("ptt" not in name.lower() for name in public_methods))


if __name__ == "__main__":
    unittest.main()
