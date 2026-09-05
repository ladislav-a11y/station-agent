from __future__ import annotations

import socket
import tempfile
import threading
import unittest
from pathlib import Path

from station_agent.cli import main
from station_agent.config import config_from_dict
from station_agent.db import Database
from station_agent.diagnostics import (
    check_database,
    check_log4om_endpoint,
    check_tcp_endpoint,
    run_live_diagnostics,
)


class LiveDiagnosticsTests(unittest.TestCase):
    def test_database_check_is_read_only_and_reports_integrity(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = str(Path(temp_dir) / "station.sqlite3")
            with Database(path) as database:
                database.mark_worked("Czech Republic")

            result = check_database(path)

            self.assertTrue(result.ok)
            self.assertTrue(result.verified)
            with Database(path) as database:
                self.assertEqual(database.worked_entities(), {"Czech Republic"})

    def test_database_check_fails_for_missing_file_without_creating_it(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "missing.sqlite3"
            result = check_database(str(path))
            self.assertFalse(result.ok)
            self.assertFalse(path.exists())

    def test_cluster_check_opens_real_tcp_connection(self):
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        accepted = threading.Event()

        def accept_once():
            connection, _ = listener.accept()
            connection.close()
            accepted.set()

        thread = threading.Thread(target=accept_once, daemon=True)
        thread.start()
        try:
            result = check_tcp_endpoint("dx_cluster", "127.0.0.1", listener.getsockname()[1])
            self.assertTrue(result.ok)
            self.assertTrue(result.verified)
            self.assertTrue(accepted.wait(1.0))
        finally:
            listener.close()
            thread.join(timeout=1.0)

    def test_log4om_udp_check_is_explicitly_unconfirmed(self):
        result = check_log4om_endpoint("127.0.0.1", 2333)
        self.assertTrue(result.ok)
        self.assertFalse(result.verified)
        self.assertIn("nelze přes UDP potvrdit", result.detail)

    def test_disabled_external_integrations_are_not_contacted(self):
        config = config_from_dict({"sources": {"mock": {"enabled": False}}})
        with tempfile.TemporaryDirectory() as temp_dir:
            config.database.path = str(Path(temp_dir) / "station.sqlite3")
            with Database(config.database.path):
                pass
            results = run_live_diagnostics(config)
        self.assertEqual([result.component for result in results], ["database", "log4om", "dx_cluster"])
        self.assertTrue(results[0].verified)
        self.assertFalse(results[1].verified)
        self.assertFalse(results[2].verified)

    def test_cli_diagnostic_does_not_clear_database_or_start_agent(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.yaml"
            database_path = Path(temp_dir) / "station.sqlite3"
            config_path.write_text(
                f"database:\n  path: {database_path}\n"
                "sources:\n  mock:\n    enabled: false\n"
                "propagation:\n  enabled: false\n",
                encoding="utf-8",
            )
            with Database(str(database_path)) as database:
                database.mark_worked("Czech Republic")

            self.assertEqual(main(["--config", str(config_path), "--diagnose-live"]), 0)

            with Database(str(database_path)) as database:
                self.assertEqual(database.worked_entities(), {"Czech Republic"})


if __name__ == "__main__":
    unittest.main()
