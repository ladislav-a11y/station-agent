"""Ověřuje, že PSKReporterAdapter opravdu provádí síťový přenos.

Na rozdíl od tests/test_adapters_parsing.py (které testuje jen parser na
fixture textu v paměti) tento test spustí skutečný lokální HTTP server
(real socket, real TCP/HTTP GET přes loopback) a nechá adaptér se na něj
opravdu připojit -- stejnou cestou kódu, jakou by použil proti reálnému
https://retrieve.pskreporter.info/query. Díky loopbacku test neběží proti
internetu (viz AGENTS.md "Testy běží bez internetu"), ale zároveň neni to
mock v procesu -- ověřuje se skutečný HTTP klient (`fetch_pskreporter_xml`),
sestavení URL/query parametrů, timeout i chybové chování.
"""

from __future__ import annotations

import threading
import unittest
import urllib.error
from http.server import BaseHTTPRequestHandler, HTTPServer

from station_agent.adapters.pskreporter import PSKReporterAdapter, fetch_pskreporter_xml

PSKR_XML = b"""<?xml version="1.0"?>
<receptionReports>
<receptionReport senderCallsign="OK1ABC" receiverCallsign="W1AW"
                  frequency="14074000" mode="FT8"
                  flowStartSeconds="1700000000" sNR="-10" />
</receptionReports>
"""


class _PskrHandler(BaseHTTPRequestHandler):
    last_path: str | None = None

    def do_GET(self):  # noqa: N802 (stdlib naming)
        type(self).last_path = self.path
        self.send_response(200)
        self.send_header("Content-Type", "text/xml; charset=utf-8")
        self.end_headers()
        self.wfile.write(PSKR_XML)

    def log_message(self, format, *args):  # noqa: A002 -- ztišit testovací výstup
        pass


class _FailingHandler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        self.send_response(503)
        self.end_headers()

    def log_message(self, format, *args):  # noqa: A002
        pass


class _LocalHttpServerTestCase(unittest.TestCase):
    handler_class = _PskrHandler

    def setUp(self):
        self.server = HTTPServer(("127.0.0.1", 0), self.handler_class)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        host, port = self.server.server_address
        self.base_url = f"http://{host}:{port}/query"

    def tearDown(self):
        self.server.shutdown()
        self.thread.join(timeout=5)
        self.server.server_close()


class PSKReporterLiveFetchTests(_LocalHttpServerTestCase):
    def test_fetch_pskreporter_xml_performs_real_http_get(self):
        body = fetch_pskreporter_xml(self.base_url, timeout_s=5)
        self.assertIn("OK1ABC", body)

    def test_fetch_pskreporter_xml_appends_query_params(self):
        fetch_pskreporter_xml(self.base_url, params={"senderCallsign": "OK1KT"}, timeout_s=5)
        self.assertIn("senderCallsign=OK1KT", _PskrHandler.last_path)

    def test_adapter_fetch_downloads_and_parses_over_real_socket(self):
        adapter = PSKReporterAdapter(query_url=self.base_url, timeout_s=5)
        spots = adapter.fetch()
        self.assertEqual(len(spots), 1)
        self.assertEqual(spots[0].callsign, "OK1ABC")
        self.assertEqual(spots[0].source, "pskreporter")


class PSKReporterLiveFetchErrorTests(_LocalHttpServerTestCase):
    handler_class = _FailingHandler

    def test_http_error_propagates_instead_of_fake_data(self):
        adapter = PSKReporterAdapter(query_url=self.base_url, timeout_s=5)
        with self.assertRaises(urllib.error.HTTPError):
            adapter.fetch()


if __name__ == "__main__":
    unittest.main()
