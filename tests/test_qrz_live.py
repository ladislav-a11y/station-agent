"""Ověřuje, že QRZClient/fetch_qrz_* opravdu provádí síťový přenos.

Stejný princip jako tests/test_adapters_live.py u PSKReporteru: skutečný
lokální HTTP server (real socket, real HTTP GET přes loopback), ne mock v
procesu -- ověřuje se sestavení URL/query parametrů, dekódování odpovědi a
end-to-end chování QRZClient.lookup() proti reálnému HTTP klientovi, aniž
by test běžel proti internetu (viz AGENTS.md "Testy běží bez internetu").
"""

from __future__ import annotations

import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

from station_agent.adapters.qrz import QRZClient, fetch_qrz_lookup_xml, fetch_qrz_session_xml

SESSION_XML = b"""<?xml version="1.0" encoding="utf-8" ?>
<QRZDatabase version="1.34" xmlns="http://xmldata.qrz.com">
<Session>
<Key>livesessionkey</Key>
<Count>1</Count>
<GMTime>Fri Sep  4 12:00:00 2026</GMTime>
</Session>
</QRZDatabase>
"""

LOOKUP_XML = b"""<?xml version="1.0" encoding="utf-8" ?>
<QRZDatabase version="1.34" xmlns="http://xmldata.qrz.com">
<Callsign>
<call>4L5O</call>
<country>Georgia</country>
<lat>41.715138</lat>
<lon>44.827096</lon>
<cqzone>21</cqzone>
</Callsign>
<Session>
<Key>livesessionkey</Key>
<Count>2</Count>
<GMTime>Fri Sep  4 12:00:01 2026</GMTime>
</Session>
</QRZDatabase>
"""

# Druhy, odlisny callsign/zeme (dalsi "?" stanice ze zivych dat 2026-09-04,
# viz DIAGNOSIS_DXCC_PREFIX_GAP.md) -- dokazuje, ze cely HTTP klient neni
# hard-coded na "4L5O", ale skutecne posila/parsuje libovolny dotazovany
# callsign.
LOOKUP_JE3GUG_XML = b"""<?xml version="1.0" encoding="utf-8" ?>
<QRZDatabase version="1.34" xmlns="http://xmldata.qrz.com">
<Callsign>
<call>JE3GUG</call>
<country>Japan</country>
<lat>34.6937</lat>
<lon>135.5023</lon>
<cqzone>25</cqzone>
</Callsign>
<Session>
<Key>livesessionkey</Key>
<Count>3</Count>
<GMTime>Fri Sep  4 12:00:02 2026</GMTime>
</Session>
</QRZDatabase>
"""


class _QRZHandler(BaseHTTPRequestHandler):
    last_path: str | None = None

    def do_GET(self):  # noqa: N802 (stdlib naming)
        type(self).last_path = self.path
        self.send_response(200)
        self.send_header("Content-Type", "text/xml; charset=utf-8")
        self.end_headers()
        if "callsign=JE3GUG" in self.path:
            self.wfile.write(LOOKUP_JE3GUG_XML)
        elif "callsign=" in self.path:
            self.wfile.write(LOOKUP_XML)
        else:
            self.wfile.write(SESSION_XML)

    def log_message(self, format, *args):  # noqa: A002 -- ztišit testovací výstup
        pass


class _LocalHttpServerTestCase(unittest.TestCase):
    handler_class = _QRZHandler

    def setUp(self):
        self.server = HTTPServer(("127.0.0.1", 0), self.handler_class)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        host, port = self.server.server_address
        self.base_url = f"http://{host}:{port}/xml/current/"

    def tearDown(self):
        self.server.shutdown()
        self.thread.join(timeout=5)
        self.server.server_close()


class QRZLiveFetchTests(_LocalHttpServerTestCase):
    def test_fetch_session_xml_performs_real_http_get(self):
        body = fetch_qrz_session_xml(self.base_url, "OK1TEST", "secret", timeout_s=5)
        self.assertIn("livesessionkey", body)

    def test_fetch_session_xml_sends_credentials_as_query_params(self):
        fetch_qrz_session_xml(self.base_url, "OK1TEST", "secret", timeout_s=5)
        self.assertIn("username=OK1TEST", _QRZHandler.last_path)
        self.assertIn("password=secret", _QRZHandler.last_path)

    def test_fetch_lookup_xml_performs_real_http_get(self):
        body = fetch_qrz_lookup_xml(self.base_url, "livesessionkey", "4L5O", timeout_s=5)
        self.assertIn("Georgia", body)

    def test_client_lookup_end_to_end_over_real_socket(self):
        client = QRZClient(username="OK1TEST", password="secret", base_url=self.base_url, timeout_s=5)
        entity = client.lookup("4L5O")
        self.assertIsNotNone(entity)
        self.assertEqual(entity.name, "Georgia")
        self.assertEqual(entity.cq_zone, 21)

    def test_client_lookup_end_to_end_for_different_station_is_not_hard_coded(self):
        # Obecnost reseni: stejny klient bez jakekoli zmeny kodu spravne
        # dohleda i uplne jinou stanici/zemi (JE3GUG/Japan) -- neni to
        # specialni vetvena logika jen pro presny priklad "4L5O" ze zadani.
        client = QRZClient(username="OK1TEST", password="secret", base_url=self.base_url, timeout_s=5)
        entity = client.lookup("JE3GUG")
        self.assertIsNotNone(entity)
        self.assertEqual(entity.name, "Japan")
        self.assertEqual(entity.cq_zone, 25)
        self.assertIn("callsign=JE3GUG", _QRZHandler.last_path)


if __name__ == "__main__":
    unittest.main()
