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
import warnings
from email.utils import format_datetime
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer

from station_agent.adapters.base import RateLimitedError
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


class _RateLimitedHandler(BaseHTTPRequestHandler):
    """Simuluje PSKReporter vracející HTTP 429 s ``Retry-After: 30`` (v
    sekundách) -- reprodukuje reálný live test, kde PSKReporter začal
    vracet 429 kvůli příliš častým dotazům."""

    def do_GET(self):  # noqa: N802
        self.send_response(429)
        self.send_header("Retry-After", "30")
        self.end_headers()

    def log_message(self, format, *args):  # noqa: A002
        pass


class _RateLimitedNoRetryAfterHandler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        self.send_response(429)
        self.end_headers()

    def log_message(self, format, *args):  # noqa: A002
        pass


class _RateLimitedHttpDateHandler(BaseHTTPRequestHandler):
    """``Retry-After`` může být podle RFC 7231 i HTTP-date, ne jen počet
    sekund -- ověřuje se, že to ``fetch_pskreporter_xml`` umí naparsovat."""

    retry_after_date = format_datetime(datetime.now(timezone.utc) + timedelta(seconds=45), usegmt=True)

    def do_GET(self):  # noqa: N802
        self.send_response(429)
        self.send_header("Retry-After", self.retry_after_date)
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

    def test_http_error_response_is_closed(self):
        with warnings.catch_warnings():
            warnings.simplefilter("error", ResourceWarning)
            try:
                fetch_pskreporter_xml(self.base_url, timeout_s=5)
            except urllib.error.HTTPError as exc:
                self.assertTrue(exc.closed)
            else:
                self.fail("Expected HTTPError")


class PSKReporterRateLimitTests(_LocalHttpServerTestCase):
    """Live test odhalil HTTP 429 -- ověřuje se, že se to nepropaguje jako
    obecná HTTPError, ale jako RateLimitedError s naparsovaným Retry-After
    (viz station_agent/adapters/polling.py, které na tuto výjimku reaguje
    backoffem)."""

    handler_class = _RateLimitedHandler

    def test_429_raises_rate_limited_error_not_http_error(self):
        with self.assertRaises(RateLimitedError) as ctx:
            fetch_pskreporter_xml(self.base_url, timeout_s=5)
        self.assertAlmostEqual(ctx.exception.retry_after_seconds, 30.0, delta=1.0)

    def test_adapter_fetch_also_raises_rate_limited_error(self):
        adapter = PSKReporterAdapter(query_url=self.base_url, timeout_s=5)
        with self.assertRaises(RateLimitedError):
            adapter.fetch()

    def test_429_http_response_is_closed(self):
        with warnings.catch_warnings():
            warnings.simplefilter("error", ResourceWarning)
            with self.assertRaises(RateLimitedError) as ctx:
                fetch_pskreporter_xml(self.base_url, timeout_s=5)
        cause = ctx.exception.__cause__
        self.assertIsInstance(cause, urllib.error.HTTPError)
        self.assertTrue(cause.closed)


class PSKReporterRateLimitNoRetryAfterTests(_LocalHttpServerTestCase):
    handler_class = _RateLimitedNoRetryAfterHandler

    def test_429_without_retry_after_header_leaves_it_none(self):
        with self.assertRaises(RateLimitedError) as ctx:
            fetch_pskreporter_xml(self.base_url, timeout_s=5)
        self.assertIsNone(ctx.exception.retry_after_seconds)


class PSKReporterRateLimitHttpDateTests(_LocalHttpServerTestCase):
    handler_class = _RateLimitedHttpDateHandler

    def test_retry_after_as_http_date_is_parsed(self):
        with self.assertRaises(RateLimitedError) as ctx:
            fetch_pskreporter_xml(self.base_url, timeout_s=5)
        # Handler nastavil Retry-After ~45 s do budoucnosti jako HTTP-date.
        self.assertAlmostEqual(ctx.exception.retry_after_seconds, 45.0, delta=5.0)


if __name__ == "__main__":
    unittest.main()
