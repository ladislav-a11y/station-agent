import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from unittest.mock import patch

from station_agent.log4om_lookup import (
    Log4OMQSOChecker,
    QSOVerificationStatus,
    _readonly_uri,
)


class Log4OMQSOCheckerTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tempdir.name, "log.sqlite")
        with closing(sqlite3.connect(self.db_path)) as connection:
            with connection:
                connection.execute(
                    'CREATE TABLE "Log" (callsign VARCHAR(50) NOT NULL, mode VARCHAR(30) NOT NULL, freq DECIMAL(18,3) NOT NULL, freqrx DECIMAL(18,3) NOT NULL)'
                )
                connection.execute(
                    'INSERT INTO "Log" (callsign, mode, freq, freqrx) VALUES (?, ?, ?, ?)',
                    (" ok1abc ", "USB", 14195.125, 99999.0),
                )
        self.checker = Log4OMQSOChecker(self.db_path)

    def tearDown(self):
        self.tempdir.cleanup()

    def test_exact_match_normalizes_call_and_mode_and_converts_khz_to_hz(self):
        result = self.checker.check("ok1ABC", " ssb ", 14_195_125)
        self.assertEqual(result.status, QSOVerificationStatus.MATCH)
        self.assertTrue(result.verified)
        self.assertTrue(result.exists)

    def test_different_mode_does_not_match(self):
        result = self.checker.check("OK1ABC", "CW", 14_195_125)
        self.assertEqual(result.status, QSOVerificationStatus.NO_MATCH)

    def test_different_frequency_does_not_match_and_freqrx_is_ignored(self):
        result = self.checker.check("OK1ABC", "SSB", 99_999_000)
        self.assertEqual(result.status, QSOVerificationStatus.NO_MATCH)

    def test_connection_is_opened_with_read_only_uri(self):
        real_connect = sqlite3.connect
        calls = []

        def recording_connect(database, *args, **kwargs):
            calls.append((database, kwargs))
            return real_connect(database, *args, **kwargs)

        with patch("station_agent.log4om_lookup.sqlite3.connect", recording_connect):
            self.checker.check("OK1ABC", "SSB", 14_195_125)
        self.assertIn("mode=ro", calls[0][0])
        self.assertTrue(calls[0][1]["uri"])

    def test_readonly_uri_encodes_unc_without_unsupported_uri_authority(self):
        uri = _readonly_uri(r"\\server\sdílená složka\log.sqlite")
        self.assertTrue(uri.startswith("file:%5C%5Cserver%5C"))
        self.assertIn("%C3%AD", uri)
        self.assertIn("%20", uri)
        self.assertTrue(uri.endswith("?mode=ro&immutable=1"))

    def test_connection_enables_query_only_before_reading_schema(self):
        statements = []
        real_connect = sqlite3.connect

        class RecordingConnection:
            def __init__(self, connection):
                self.connection = connection

            def execute(self, statement, parameters=()):
                statements.append(statement)
                return self.connection.execute(statement, parameters)

            def close(self):
                self.connection.close()

        with patch(
            "station_agent.log4om_lookup.sqlite3.connect",
            side_effect=lambda *args, **kwargs: RecordingConnection(real_connect(*args, **kwargs)),
        ):
            self.checker.check("OK1ABC", "SSB", 14_195_125)
        self.assertEqual(statements[0], "PRAGMA query_only=ON")

    def test_diagnostic_does_not_disclose_database_path_or_driver_error(self):
        secret_path = os.path.join(self.tempdir.name, "user-secret.sqlite")
        unavailable = Log4OMQSOChecker(secret_path).check("OK1ABC", "SSB", 14_195_125)
        self.assertNotIn(secret_path, unavailable.diagnostic)
        with patch(
            "station_agent.log4om_lookup.sqlite3.connect",
            side_effect=sqlite3.DatabaseError("password=super-secret"),
        ):
            unreadable = self.checker.check("OK1ABC", "SSB", 14_195_125)
        self.assertNotIn("super-secret", unreadable.diagnostic)

    def test_unavailable_database_is_not_reported_as_verified_absence(self):
        result = Log4OMQSOChecker(os.path.join(self.tempdir.name, "missing.sqlite")).check(
            "OK1ABC", "SSB", 14_195_125
        )
        self.assertEqual(result.status, QSOVerificationStatus.UNAVAILABLE)
        self.assertFalse(result.verified)
        self.assertIsNone(result.exists)

    def test_unknown_schema_has_distinct_status(self):
        unknown_path = os.path.join(self.tempdir.name, "unknown.sqlite")
        with closing(sqlite3.connect(unknown_path)) as connection:
            with connection:
                connection.execute("CREATE TABLE something_else (value TEXT)")
        result = Log4OMQSOChecker(unknown_path).check("OK1ABC", "SSB", 14_195_125)
        self.assertEqual(result.status, QSOVerificationStatus.UNKNOWN_DATABASE)

    def test_unreadable_database_has_distinct_status_and_diagnostic(self):
        with patch(
            "station_agent.log4om_lookup.sqlite3.connect",
            side_effect=sqlite3.DatabaseError("not a database"),
        ):
            result = self.checker.check("OK1ABC", "SSB", 14_195_125)
        self.assertEqual(result.status, QSOVerificationStatus.UNREADABLE)
        self.assertFalse(result.verified)
        self.assertIn("read-only", result.diagnostic)


if __name__ == "__main__":
    unittest.main()
