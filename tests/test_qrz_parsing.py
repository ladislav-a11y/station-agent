"""Testuje QRZ XML parsery a cache/cooldown logiku QRZClient na fixture
datech -- žádný skutečný síťový přístup (viz tests/test_qrz_live.py pro
ověření síťové vrstvy proti lokálnímu HTTP serveru)."""

from __future__ import annotations

import unittest

from station_agent.adapters.qrz import (
    QRZClient,
    QRZLookupError,
    _QRZSessionExpiredError,
    parse_qrz_lookup_xml,
    parse_qrz_session_key,
)

SESSION_OK_XML = """<?xml version="1.0" encoding="utf-8" ?>
<QRZDatabase version="1.34" xmlns="http://xmldata.qrz.com">
<Session>
<Key>abc123sessionkey</Key>
<Count>123</Count>
<SubExp>Wed Jan 1 00:00:00 2030</SubExp>
<GMTime>Fri Sep  4 12:00:00 2026</GMTime>
</Session>
</QRZDatabase>
"""

SESSION_ERROR_XML = """<?xml version="1.0" encoding="utf-8" ?>
<QRZDatabase version="1.34" xmlns="http://xmldata.qrz.com">
<Session>
<Error>Username/password incorrect</Error>
<GMTime>Fri Sep  4 12:00:00 2026</GMTime>
</Session>
</QRZDatabase>
"""

LOOKUP_4L5O_XML = """<?xml version="1.0" encoding="utf-8" ?>
<QRZDatabase version="1.34" xmlns="http://xmldata.qrz.com">
<Callsign>
<call>4L5O</call>
<country>Georgia</country>
<lat>41.715138</lat>
<lon>44.827096</lon>
<grid>LN41ox</grid>
<ccode>75</ccode>
<cqzone>21</cqzone>
<ituzone>29</ituzone>
</Callsign>
<Session>
<Key>abc123sessionkey</Key>
<Count>124</Count>
<GMTime>Fri Sep  4 12:00:01 2026</GMTime>
</Session>
</QRZDatabase>
"""

LOOKUP_NOT_FOUND_XML = """<?xml version="1.0" encoding="utf-8" ?>
<QRZDatabase version="1.34" xmlns="http://xmldata.qrz.com">
<Session>
<Error>Not found: QQ0XYZ</Error>
<Key>abc123sessionkey</Key>
<Count>125</Count>
<GMTime>Fri Sep  4 12:00:02 2026</GMTime>
</Session>
</QRZDatabase>
"""

LOOKUP_SESSION_TIMEOUT_XML = """<?xml version="1.0" encoding="utf-8" ?>
<QRZDatabase version="1.34" xmlns="http://xmldata.qrz.com">
<Session>
<Error>Session Timeout</Error>
<GMTime>Fri Sep  4 12:00:03 2026</GMTime>
</Session>
</QRZDatabase>
"""


class ParseSessionKeyTests(unittest.TestCase):
    def test_parses_valid_session_key(self):
        self.assertEqual(parse_qrz_session_key(SESSION_OK_XML), "abc123sessionkey")

    def test_raises_lookup_error_on_bad_credentials(self):
        with self.assertRaises(QRZLookupError):
            parse_qrz_session_key(SESSION_ERROR_XML)


class ParseLookupXmlTests(unittest.TestCase):
    def test_parses_known_callsign_into_dxcc_entity(self):
        entity = parse_qrz_lookup_xml(LOOKUP_4L5O_XML)
        self.assertIsNotNone(entity)
        self.assertEqual(entity.name, "Georgia")
        self.assertEqual(entity.prefix, "4L5O")
        self.assertAlmostEqual(entity.latitude, 41.715138)
        self.assertAlmostEqual(entity.longitude, 44.827096)
        self.assertEqual(entity.cq_zone, 21)
        # Kontinent QRZ nevrací -- radši prázdné, než vymyšlené (viz app.js).
        self.assertEqual(entity.continent, "")

    def test_not_found_returns_none_not_exception(self):
        self.assertIsNone(parse_qrz_lookup_xml(LOOKUP_NOT_FOUND_XML))

    def test_session_timeout_raises_internal_retry_signal(self):
        with self.assertRaises(_QRZSessionExpiredError):
            parse_qrz_lookup_xml(LOOKUP_SESSION_TIMEOUT_XML)


class _FakeClock:
    def __init__(self, start: float = 1_000_000.0):
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class QRZClientCacheAndCooldownTests(unittest.TestCase):
    def _client(self, clock: _FakeClock, **overrides) -> QRZClient:
        return QRZClient(
            username="OK1TEST",
            password="secret",
            time_func=clock,
            cache_ttl_seconds=overrides.pop("cache_ttl_seconds", 100.0),
            error_cooldown_seconds=overrides.pop("error_cooldown_seconds", 50.0),
            **overrides,
        )

    def test_lookup_never_raises_on_network_failure(self):
        clock = _FakeClock()
        client = self._client(clock)
        client._authenticate = lambda: (_ for _ in ()).throw(OSError("no network"))
        result = client.lookup("4L5O")
        self.assertIsNone(result)

    def test_successful_lookup_is_cached_without_second_network_call(self):
        clock = _FakeClock()
        client = self._client(clock)
        calls = []

        def fake_authenticate():
            calls.append("auth")
            return "sessionkey"

        def fake_lookup_uncached(call):
            calls.append(f"lookup:{call}")
            return parse_qrz_lookup_xml(LOOKUP_4L5O_XML)

        client._authenticate = fake_authenticate
        client._lookup_uncached = fake_lookup_uncached

        first = client.lookup("4L5O")
        second = client.lookup("4l5o")  # case-insensitive cache key
        self.assertEqual(first.name, "Georgia")
        self.assertEqual(second.name, "Georgia")
        self.assertEqual(calls, ["lookup:4L5O"])  # jen jedno reálné volání

    def test_negative_result_is_cached_too(self):
        clock = _FakeClock()
        client = self._client(clock)
        calls = []
        client._lookup_uncached = lambda call: (calls.append(call), None)[1]

        self.assertIsNone(client.lookup("QQ0XYZ"))
        self.assertIsNone(client.lookup("QQ0XYZ"))
        self.assertEqual(calls, ["QQ0XYZ"])

    def test_cache_expires_after_ttl(self):
        clock = _FakeClock()
        client = self._client(clock, cache_ttl_seconds=10.0)
        calls = []
        client._lookup_uncached = lambda call: (calls.append(call), parse_qrz_lookup_xml(LOOKUP_4L5O_XML))[1]

        client.lookup("4L5O")
        clock.advance(11.0)
        client.lookup("4L5O")
        self.assertEqual(calls, ["4L5O", "4L5O"])

    def test_error_triggers_cooldown_before_retrying(self):
        clock = _FakeClock()
        client = self._client(clock, error_cooldown_seconds=30.0)
        calls = []

        def failing(call):
            calls.append(call)
            raise OSError("timeout")

        client._lookup_uncached = failing

        self.assertIsNone(client.lookup("4L5O"))
        self.assertIsNone(client.lookup("4L7T"))  # jiny callsign, presto cooldown plati globalne
        self.assertEqual(calls, ["4L5O"])  # druhe volani se vubec neprovedlo

        clock.advance(31.0)
        self.assertIsNone(client.lookup("4L7T"))
        self.assertEqual(calls, ["4L5O", "4L7T"])

    def test_session_expiry_triggers_single_reauth_then_succeeds(self):
        clock = _FakeClock()
        client = self._client(clock)
        client._session_key = "stale-key"
        auth_calls = []

        def fake_authenticate():
            auth_calls.append(1)
            return "fresh-key"

        fetch_calls = []

        def fake_fetch(base_url, session_key, callsign, timeout_s):
            fetch_calls.append(session_key)
            if session_key == "stale-key":
                return LOOKUP_SESSION_TIMEOUT_XML
            return LOOKUP_4L5O_XML

        client._authenticate = fake_authenticate
        import station_agent.adapters.qrz as qrz_module

        original_fetch = qrz_module.fetch_qrz_lookup_xml
        qrz_module.fetch_qrz_lookup_xml = fake_fetch
        try:
            result = client.lookup("4L5O")
        finally:
            qrz_module.fetch_qrz_lookup_xml = original_fetch

        self.assertEqual(result.name, "Georgia")
        self.assertEqual(auth_calls, [1])
        self.assertEqual(fetch_calls, ["stale-key", "fresh-key"])

    def test_empty_callsign_returns_none_without_network(self):
        clock = _FakeClock()
        client = self._client(clock)
        client._lookup_uncached = lambda call: (_ for _ in ()).throw(AssertionError("should not be called"))
        self.assertIsNone(client.lookup(""))
        self.assertIsNone(client.lookup(None))


if __name__ == "__main__":
    unittest.main()
