from __future__ import annotations

import socket
import unittest
import tempfile
from pathlib import Path

from station_agent.adapters.dx_cluster import DXClusterAdapter, RECOMMENDED_PROVIDERS
from station_agent.cli import build_app_state, build_sources, main
from station_agent.config import config_from_dict, load_config
from station_agent.db import Database


REPO_ROOT = Path(__file__).resolve().parent.parent


def _unused_loopback_port() -> int:
    """Vrátí port na 127.0.0.1, na kterém aktuálně nikdo neposlouchá.

    Socket se hned zavře, takže následné connect() na tento port spolehlivě
    skončí ECONNREFUSED -- stejně jako když uživatel spustí Station Agent
    dřív, než nastartuje rigctld.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class LiveRigStartupTests(unittest.TestCase):
    def test_build_app_state_does_not_crash_when_rigctld_is_unreachable(self):
        """Regrese: `rig.mode: live` bez běžícího rigctld shazovalo celý
        start agenta na nezachycené ConnectionRefusedError z počáteční
        sync_rig_state_from_hardware() (viz cli.build_app_state). Start musí
        pokračovat v degradovaném stavu (current_rig_state zůstane None,
        GUI i AUTO TUNE to zvládají), stejně jako výpadek riggu za běhu
        v PollingLoop."""
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = str(Path(temp_dir) / "station.sqlite3")
            config = config_from_dict(
                {
                    "database": {"path": database_path},
                    "rig": {"mode": "live", "rigctld_port": _unused_loopback_port()},
                    "sources": {"mock": {"enabled": False}},
                    "propagation": {"enabled": False},
                }
            )
            app_state = build_app_state(config)
            try:
                self.assertIsNone(app_state.current_rig_state)
            finally:
                app_state.aggregator.close()
                app_state.db.close()
                app_state.rig.close()


class MissingConfigStartupTests(unittest.TestCase):
    def test_main_exits_cleanly_when_config_file_is_missing(self):
        """Regrese: fresh checkout nemá commitnutý config.yaml (je v
        .gitignore) -- `python -m station_agent` bez `cp config.example.yaml
        config.yaml` musí skončit čitelnou chybou a nenulovým návratovým
        kódem, ne nezachyceným FileNotFoundError/tracebackem (viz README.md,
        sekce Instalace)."""
        with tempfile.TemporaryDirectory() as temp_dir:
            missing_path = str(Path(temp_dir) / "config.yaml")
            with self.assertLogs("station_agent.cli", level="ERROR") as logs:
                exit_code = main(["--config", missing_path])
        self.assertEqual(exit_code, 1)
        # Nestačí ověřit jen exit kód -- kdyby main() regredoval na tiché
        # `except Exception: return 1` bez logování, test výše by to
        # nezachytil. Musí zůstat viditelná právě ta akční hláška s
        # návodným příkazem, ne jen libovolná chyba.
        log_output = "\n".join(logs.output)
        self.assertIn(missing_path, log_output)
        self.assertIn("config.example.yaml", log_output)

    def test_main_exits_cleanly_when_config_path_is_a_directory(self):
        """Stejná regrese jako výše, ale pro --config ukazující na existující
        adresář (viz station_agent.config.load_config: tato větev hlásí jinou
        zprávu než "neexistuje", main() ji ale musí odchytit úplně stejně a
        skončit s exit kódem 1, ne nezachyceným tracebackem."""
        with tempfile.TemporaryDirectory() as temp_dir:
            directory_path = str(Path(temp_dir) / "config.yaml")
            Path(directory_path).mkdir()
            with self.assertLogs("station_agent.cli", level="ERROR") as logs:
                exit_code = main(["--config", directory_path])
        self.assertEqual(exit_code, 1)
        log_output = "\n".join(logs.output)
        self.assertIn(directory_path, log_output)
        self.assertIn("adresář", log_output)

    def test_main_exits_cleanly_when_config_content_is_invalid(self):
        """Stejna trida regrese jako u chybejiciho souboru (DIAGNOSIS_P5.md),
        ale pro pritomny config.yaml s neplatnym obsahem (napr. rig.mode mimo
        povolene hodnoty -- viz RigConfig.__post_init__). Bez odchyceni
        ValueError v main() by tohle take spadlo na nezachycenem tracebacku
        misto srozumitelne hlasky a exit kodu 1."""
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = str(Path(temp_dir) / "config.yaml")
            Path(config_path).write_text("rig:\n  mode: not_a_valid_mode\n", encoding="utf-8")
            with self.assertLogs("station_agent.cli", level="ERROR") as logs:
                exit_code = main(["--config", config_path])
        self.assertEqual(exit_code, 1)
        log_output = "\n".join(logs.output)
        self.assertIn(config_path, log_output)
        self.assertIn("neplatn", log_output)

    def test_main_exits_cleanly_when_enabled_source_has_invalid_port(self):
        """Regrese: config.yaml sam o sobe validni (projde load_config), ale
        sources.dx_cluster.port neni cislo. int() prevod se deje az v
        cli.build_sources() -- volane z build_app_state(), ktere puvodne
        bezelo MIMO try/except v main(). main() tak spadl na nezachycenem
        ValueError misto citelne hlasky, presto ze load_config() vubec
        nespadl (viz DIAGNOSIS_P5.md)."""
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = str(Path(temp_dir) / "config.yaml")
            database_path = str(Path(temp_dir) / "station.sqlite3")
            Path(config_path).write_text(
                "database:\n"
                f"  path: {database_path}\n"
                "sources:\n"
                "  dx_cluster:\n"
                "    enabled: true\n"
                "    host: example.net\n"
                "    port: not_a_number\n"
                "propagation:\n"
                "  enabled: false\n",
                encoding="utf-8",
            )
            with self.assertLogs("station_agent.cli", level="ERROR") as logs:
                exit_code = main(["--config", config_path])
        self.assertEqual(exit_code, 1)
        log_output = "\n".join(logs.output)
        self.assertIn(config_path, log_output)
        self.assertIn("neplatn", log_output)

    def test_main_exits_cleanly_when_database_parent_dir_is_missing(self):
        """Regrese: config.yaml sam o sobe validni, ale database.path miri do
        neexistujiciho adresare (napr. preklep). Database(config.database.path)
        v cli.build_app_state() bezela puvodne pred jakymkoli try/except a
        sqlite3.OperationalError neni ani FileNotFoundError, ani ValueError --
        main() by spadl na nezachycenem tracebacku presto, ze load_config()
        vubec neselhal (viz DIAGNOSIS_P5.md)."""
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = str(Path(temp_dir) / "config.yaml")
            bad_database_path = str(Path(temp_dir) / "no_such_subdir" / "station.sqlite3")
            Path(config_path).write_text(
                "database:\n"
                f"  path: {bad_database_path}\n"
                "sources:\n"
                "  mock:\n"
                "    enabled: false\n"
                "propagation:\n"
                "  enabled: false\n",
                encoding="utf-8",
            )
            with self.assertLogs("station_agent.cli", level="ERROR") as logs:
                exit_code = main(["--config", config_path])
        self.assertEqual(exit_code, 1)
        log_output = "\n".join(logs.output)
        self.assertIn(bad_database_path, log_output)
        self.assertIn("neplatn", log_output)

    def test_main_exits_cleanly_when_web_port_is_out_of_range(self):
        """Regrese: web.port mimo platny rozsah 0-65535 (napr. preklep s
        extra cislici) byl driv odhalen az v create_server() -- socket.bind()
        vyhazuje OverflowError, ktere v main() bezelo mimo try/except a nebylo
        by odchyceno. Ted uz WebConfig.__post_init__ port validuje pri
        load_config(), takze to odchyti existujici except ValueError (viz
        DIAGNOSIS_P5.md)."""
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = str(Path(temp_dir) / "config.yaml")
            database_path = str(Path(temp_dir) / "station.sqlite3")
            Path(config_path).write_text(
                "database:\n"
                f"  path: {database_path}\n"
                "web:\n"
                "  host: 127.0.0.1\n"
                "  port: 999999\n"
                "sources:\n"
                "  mock:\n"
                "    enabled: false\n"
                "propagation:\n"
                "  enabled: false\n",
                encoding="utf-8",
            )
            with self.assertLogs("station_agent.cli", level="ERROR") as logs:
                exit_code = main(["--config", config_path])
        self.assertEqual(exit_code, 1)
        log_output = "\n".join(logs.output)
        self.assertIn(config_path, log_output)
        self.assertIn("neplatn", log_output)

    def test_main_exits_cleanly_when_numeric_field_is_explicitly_null(self):
        """Regrese: "rigctld_port:" bez hodnoty za dvojteckou je platny YAML
        (klic existuje, hodnota je None) -- na rozdil od chybejiciho klice se
        proto nepouzije vychozi hodnota a config_from_dict zavola int(None),
        coz vyhazuje TypeError, ne ValueError. Puvodne by to cli.py::main
        (odchytava jen FileNotFoundError a ValueError, viz DIAGNOSIS_P5.md)
        nezachytilo a spadlo na nezachycenem tracebacku presne stejne jako
        u ostatnich neplatnych hodnot v config.yaml."""
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = str(Path(temp_dir) / "config.yaml")
            database_path = str(Path(temp_dir) / "station.sqlite3")
            Path(config_path).write_text(
                "database:\n"
                f"  path: {database_path}\n"
                "rig:\n"
                "  mode: mock\n"
                "  rigctld_port:\n"
                "sources:\n"
                "  mock:\n"
                "    enabled: false\n"
                "propagation:\n"
                "  enabled: false\n",
                encoding="utf-8",
            )
            with self.assertLogs("station_agent.cli", level="ERROR") as logs:
                exit_code = main(["--config", config_path])
        self.assertEqual(exit_code, 1)
        log_output = "\n".join(logs.output)
        self.assertIn(config_path, log_output)
        self.assertIn("neplatn", log_output)

    def test_main_exits_cleanly_when_web_port_is_already_in_use(self):
        """Regrese: web.port je v platnem rozsahu 0-65535 (WebConfig
        validaci projde), ale je uz obsazeny jinym procesem -- typicky uz
        bezici instance Station Agenta. socket.bind() v
        web.server.create_server() na tom vyhazuje OSError (Windows:
        PermissionError WinError 10013 pri exkluzivnim obsazeni portu;
        Linux: "Address already in use"). Puvodne se `create_server()`
        volalo mimo jakykoli try/except v main() -- spadlo na nezachycenem
        tracebacku presto, ze load_config() i build_app_state() probehly
        v poradku (viz DIAGNOSIS_P5.md). SO_EXCLUSIVEADDRUSE (Windows) /
        chybejici SO_REUSEADDR (POSIX) na blokujicim soketu vynuti skutecny
        konflikt bez ohledu na to, ze ThreadingHTTPServer nastavuje
        allow_reuse_address."""
        blocker = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            blocker.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        blocker.bind(("127.0.0.1", 0))
        blocker.listen(1)
        occupied_port = blocker.getsockname()[1]
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                config_path = str(Path(temp_dir) / "config.yaml")
                database_path = str(Path(temp_dir) / "station.sqlite3")
                Path(config_path).write_text(
                    "database:\n"
                    f"  path: {database_path}\n"
                    "web:\n"
                    "  host: 127.0.0.1\n"
                    f"  port: {occupied_port}\n"
                    "sources:\n"
                    "  mock:\n"
                    "    enabled: false\n"
                    "propagation:\n"
                    "  enabled: false\n",
                    encoding="utf-8",
                )
                with self.assertLogs("station_agent.cli", level="ERROR") as logs:
                    exit_code = main(["--config", config_path])
            self.assertEqual(exit_code, 1)
            log_output = "\n".join(logs.output)
            self.assertIn(str(occupied_port), log_output)
        finally:
            blocker.close()

    def test_main_exits_cleanly_when_database_file_is_not_a_valid_sqlite_file(self):
        """Regrese: database.path miri na existujici soubor, ktery ale neni
        platna SQLite databaze (napr. poskozeny soubor nebo omylem jiny
        soubor na tomto miste). Database.__init__ (station_agent/db.py) na
        tom vyhazuje sqlite3.DatabaseError -- to NENI podtrida
        sqlite3.OperationalError (jen jeji spolecny predek), takze puvodni
        `except sqlite3.OperationalError` v cli.build_app_state tuto chybu
        nezachytilo a main() by spadl na nezachycenem tracebacku presto, ze
        load_config() vubec neselhal (viz DIAGNOSIS_P5.md)."""
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = str(Path(temp_dir) / "config.yaml")
            bad_database_path = str(Path(temp_dir) / "not_a_database.sqlite3")
            Path(bad_database_path).write_text("not a real sqlite file", encoding="utf-8")
            Path(config_path).write_text(
                "database:\n"
                f"  path: {bad_database_path}\n"
                "sources:\n"
                "  mock:\n"
                "    enabled: false\n"
                "propagation:\n"
                "  enabled: false\n",
                encoding="utf-8",
            )
            with self.assertLogs("station_agent.cli", level="ERROR") as logs:
                exit_code = main(["--config", config_path])
        self.assertEqual(exit_code, 1)
        log_output = "\n".join(logs.output)
        self.assertIn(bad_database_path, log_output)
        self.assertIn("neplatn", log_output)


class FilterPreferenceStartupTests(unittest.TestCase):
    def test_build_app_state_restores_last_filter_choice_from_database(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = str(Path(temp_dir) / "station.sqlite3")
            with Database(database_path) as db:
                db.save_filter_preferences(["20m", "15m"], ["SSB", "FT8"])

            config = config_from_dict(
                {
                    "database": {"path": database_path},
                    "bands": ["40m"],
                    "modes": ["CW"],
                    "sources": {"mock": {"enabled": False}},
                    "propagation": {"enabled": False},
                }
            )
            app_state = build_app_state(config)
            try:
                self.assertEqual(app_state.config.bands, ["20m", "15m"])
                self.assertEqual(app_state.config.modes, ["SSB", "FT8"])
            finally:
                app_state.aggregator.close()
                app_state.db.close()
                app_state.rig.close()


class MultipleDXClusterProviderTests(unittest.TestCase):
    def test_recommended_providers_keep_their_configured_identity(self):
        """Regrese pro doporučené uzly z distribuovaného example configu.

        Nestačí ověřit jen syntetická jména: příklad pro uživatele musí
        skutečně obsahovat více různých endpointů a při jejich zapnutí se
        jejich konfigurační jména musí beze změny propsat do adaptérů.
        """
        config = load_config(REPO_ROOT / "config.example.yaml")
        config.sources["mock"].enabled = False
        for provider_name in RECOMMENDED_PROVIDERS:
            config.sources[provider_name].enabled = True

        providers = build_sources(config)

        self.assertEqual(
            [(provider.name, provider.host, provider.port) for provider in providers],
            [(name, host, port) for name, (host, port) in RECOMMENDED_PROVIDERS.items()],
        )
        self.assertGreaterEqual(len(providers), 4)
        self.assertEqual(len({provider.name for provider in providers}), len(providers))
        self.assertEqual(len({(provider.host, provider.port) for provider in providers}), len(providers))

    def test_builds_all_enabled_named_cluster_providers(self):
        config = config_from_dict(
            {
                "station": {"callsign": "OK1ABC"},
                "sources": {
                    "mock": {"enabled": False},
                    "dx_cluster": {
                        "enabled": True,
                        "host": "primary.example",
                        "port": 7300,
                    },
                    "dx_cluster_local": {
                        "enabled": True,
                        "host": "local.example",
                        "port": 23,
                        "callsign": "OK1XYZ",
                    },
                    "dx_cluster_backup": {
                        "enabled": False,
                        "host": "backup.example",
                    },
                },
            }
        )

        sources = build_sources(config)

        self.assertEqual([source.name for source in sources], ["dx_cluster", "dx_cluster_local"])
        self.assertTrue(all(isinstance(source, DXClusterAdapter) for source in sources))
        self.assertEqual(sources[0].callsign, "OK1ABC")
        self.assertEqual(sources[1].callsign, "OK1XYZ")

    def test_recommended_provider_names_select_catalog_endpoints_by_default(self):
        config = config_from_dict(
            {
                "station": {"callsign": "OK1ABC"},
                "sources": {
                    "mock": {"enabled": False},
                    **{name: {"enabled": True} for name in RECOMMENDED_PROVIDERS},
                },
            }
        )

        providers = build_sources(config)

        self.assertEqual(
            [(provider.name, provider.host, provider.port) for provider in providers],
            [(name, host, port) for name, (host, port) in RECOMMENDED_PROVIDERS.items()],
        )

    def test_number_of_named_providers_is_not_hard_coded(self):
        named_sources = {
            f"dx_cluster_provider_{number}": {
                "enabled": True,
                "host": f"provider-{number}.example",
            }
            for number in range(5)
        }
        config = config_from_dict(
            {
                "station": {"callsign": "OK1ABC"},
                "sources": {"mock": {"enabled": False}, **named_sources},
            }
        )

        sources = build_sources(config)

        self.assertEqual(len(sources), 5)
        self.assertEqual({source.name for source in sources}, set(named_sources))


if __name__ == "__main__":
    unittest.main()
