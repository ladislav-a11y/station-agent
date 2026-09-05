import unittest

from station_agent.country_lookup import CountryLookup
from station_agent.models import DXCCEntity


class _Callinfo:
    def __init__(self, result=None, error=None):
        self.result, self.error = result, error

    def get_all(self, callsign):
        if self.error:
            raise self.error
        return self.result


class CountryLookupTests(unittest.TestCase):
    def test_country_file_result_has_priority(self):
        lookup = CountryLookup()
        lookup._initialization_attempted = True
        lookup._callinfo = _Callinfo({"country": "Georgia", "continent": "AS",
            "latitude": 42, "longitude": 43.5, "cqz": 21, "prefix": "4L"})
        entity = lookup.lookup("4L5O")
        self.assertEqual((entity.name, entity.prefix), ("Georgia", "4L"))

    def test_unavailable_country_file_uses_builtin_table(self):
        lookup = CountryLookup()
        lookup._initialization_attempted = True
        self.assertEqual(lookup.lookup("JA1XYZ").name, "Japan")

    def test_failure_uses_network_fallback_after_builtin_miss(self):
        expected = DXCCEntity("Georgia", "4L", "AS", 42, 43.5, 21)
        calls = []
        lookup = CountryLookup(lambda call: calls.append(call) or expected)
        lookup._initialization_attempted = True
        lookup._callinfo = _Callinfo(error=RuntimeError("unavailable"))
        self.assertIs(lookup.lookup("4L5O"), expected)
        self.assertEqual(calls, ["4L5O"])

    def test_no_available_source_returns_none(self):
        lookup = CountryLookup()
        lookup._initialization_attempted = True
        self.assertIsNone(lookup.lookup("QQ0XYZ"))
