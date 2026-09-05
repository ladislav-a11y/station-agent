from __future__ import annotations

import socket
import time
import unittest
import tempfile
from pathlib import Path
from unittest import mock

from station_agent.adapters.dx_cluster import DXClusterAdapter, RECOMMENDED_PROVIDERS
from station_agent.cli import build_app_state, build_sources, main
from station_agent.config import config_from_dict, load_config
from station_agent.db import Database
from station_agent.models import Spot


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


class Log4OMBridgeStartupTests(unittest.TestCase):
    """config.log4om se dřív načetl (config.py::Log4OMConfig), ale
    build_app_state ho nikdy nepoužil -- žádná AppState instance nikdy
    neměla způsob, jak Log4OM2 prefill vůbec poslat. Zajišťuje, že bridge
    vznikne jen na explicitní opt-in (enabled: true), s hodnotami přesně
    z configu, a že defaultně (enabled: false) žádný bridge nevznikne."""

    def _build(self, log4om_overrides: dict):
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = str(Path(temp_dir) / "station.sqlite3")
            config = config_from_dict(
                {
                    "station": {"callsign": "OK1TEST"},
                    "database": {"path": database_path},
                    "sources": {"mock": {"enabled": False}},
                    "propagation": {"enabled": False},
                    "log4om": log4om_overrides,
                }
            )
            app_state = build_app_state(config)
            try:
                return app_state.log4om_bridge
            finally:
                app_state.aggregator.close()
                app_state.db.close()
                app_state.rig.close()

    def test_no_bridge_when_log4om_disabled(self):
        self.assertIsNone(self._build({"enabled": False}))

    def test_bridge_constructed_with_configured_host_port_and_callsign_when_enabled(self):
        bridge = self._build({"enabled": True, "host": "127.0.0.1", "port": 2333})
        self.assertIsNotNone(bridge)
        self.assertEqual(bridge.host, "127.0.0.1")
        self.assertEqual(bridge.port, 2333)
        self.assertEqual(bridge.station_callsign, "OK1TEST")


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

    def test_main_exits_cleanly_when_initial_candidate_refresh_fails(self):
        """Regrese: `app_state.refresh_candidates()` (počáteční synchronní
        naplnění kandidátů, volané před spuštěním web serveru -- viz
        aggregator.poll_once/DB purge/build_candidates/scoring) běželo
        původně MIMO jakýkoli try/except v main(). Selhání kdekoli v tomto
        řetězci by spadlo na nezachyceném tracebacku přesto, že
        load_config() i build_app_state() proběhly v pořádku -- stejná
        třída "Station Agent nejde spustit" jako ostatní opravy v
        DIAGNOSIS_P5.md. Reálný scoring/DB řetězec s platnou konfigurací
        neselhává, proto se selhání vynucuje mockem -- jde o strukturální
        pojistku pro neočekávané výjimky v tomto kroku startu, ne o
        konkrétní dnes existující vstup, který by ho spustil."""
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = str(Path(temp_dir) / "config.yaml")
            database_path = str(Path(temp_dir) / "station.sqlite3")
            Path(config_path).write_text(
                "database:\n"
                f"  path: {database_path}\n"
                "sources:\n"
                "  mock:\n"
                "    enabled: false\n"
                "propagation:\n"
                "  enabled: false\n",
                encoding="utf-8",
            )
            with mock.patch(
                "station_agent.cli.AppState.refresh_candidates",
                side_effect=RuntimeError("boom"),
            ):
                with self.assertLogs("station_agent.cli", level="ERROR") as logs:
                    exit_code = main(["--config", config_path])
        self.assertEqual(exit_code, 1)
        log_output = "\n".join(logs.output)
        self.assertIn("boom", log_output)

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


class StartupDatabaseCleanupTests(unittest.TestCase):
    def test_normal_startup_clears_database_before_first_candidate_load(self):
        """Vyčištění databáze (Database.clear_all_data) se musí zapojit i do
        běžného startu (bez --clear-database), ne jen do samostatné údržbové
        volby --clear-database, která agenta vůbec nespouští. Musí proběhnout
        před prvním načtením dat (refresh_candidates), aby nová relace nikdy
        nezačínala nad daty z předchozího běhu. create_server je zmockovaný
        na OSError jen proto, aby test neblokoval na server.serve_forever()
        -- vyčištění i refresh_candidates už v tu chvíli proběhly reálně.

        Zasetá data pokrývají všechny tabulky z Database.DATA_TABLES (staré
        spoty, AUTO TUNE log, band-opening historii, QSO historii i worked-
        DXCC cache), aby test odpovídal DoD požadavku "nezůstanou staré...
        ani jiné aplikační záznamy". Zároveň ověřuje, že config.yaml zůstane
        po startu bajtově beze změny -- čištění smí mazat jen řádky v DB,
        nikdy konfiguraci ani zdrojový kód."""
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = str(Path(temp_dir) / "config.yaml")
            database_path = str(Path(temp_dir) / "station.sqlite3")
            config_text = (
                "database:\n"
                f"  path: {database_path}\n"
                "sources:\n"
                "  mock:\n"
                "    enabled: false\n"
                "propagation:\n"
                "  enabled: false\n"
            )
            Path(config_path).write_text(config_text, encoding="utf-8")
            with Database(database_path) as db:
                db.insert_spot(
                    Spot(
                        callsign="OK1ABC",
                        freq_hz=14_195_000,
                        mode="SSB",
                        timestamp=time.time(),
                        source="mock",
                    )
                )
                db.mark_worked("Czech Republic")
                db.log_autotune("OK1ABC", 14_195_000, "SSB", 82, "test reason")
                db.log_band_opening("20m", 6)
                db.log_qso("OK1ABC", 14_195_000, "SSB", "20m")
                db.save_filter_preferences(["20m"], ["SSB"])

            with mock.patch(
                "station_agent.cli.create_server",
                side_effect=OSError("nechceme tu skutečný server, jen ověřit pořadí kroků"),
            ):
                exit_code = main(["--config", config_path])

            self.assertEqual(exit_code, 1)
            with Database(database_path) as db:
                self.assertEqual(db.recent_spots(max_age_seconds=86400), [])
                self.assertEqual(db.worked_entities(), set())
                self.assertEqual(db.autotune_history(), [])
                self.assertEqual(db.recent_band_openings(), [])
                self.assertEqual(db.recent_qsos(), [])
                self.assertIsNone(db.load_filter_preferences())

            # Config a kód musí zůstat nedotčené -- čištění se smí týkat
            # výhradně obsahu databáze.
            self.assertEqual(Path(config_path).read_text(encoding="utf-8"), config_text)
            self.assertTrue((REPO_ROOT / "station_agent" / "db.py").exists())
            self.assertTrue((REPO_ROOT / "station_agent" / "cli.py").exists())

    def test_main_exits_cleanly_and_skips_candidate_load_when_startup_cleanup_fails(self):
        """Při selhání vyčištění databáze (RuntimeError z clear_all_data,
        viz db.py) nesmí Station Agent pokračovat s neověřeným stavem --
        refresh_candidates (první načtení dat) se nesmí vůbec zavolat."""
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = str(Path(temp_dir) / "config.yaml")
            database_path = str(Path(temp_dir) / "station.sqlite3")
            Path(config_path).write_text(
                "database:\n"
                f"  path: {database_path}\n"
                "sources:\n"
                "  mock:\n"
                "    enabled: false\n"
                "propagation:\n"
                "  enabled: false\n",
                encoding="utf-8",
            )
            with mock.patch(
                "station_agent.cli.Database.clear_all_data",
                side_effect=RuntimeError("boom"),
            ), mock.patch(
                "station_agent.cli.AppState.refresh_candidates"
            ) as refresh_mock:
                with self.assertLogs("station_agent.cli", level="ERROR") as logs:
                    exit_code = main(["--config", config_path])
                refresh_mock.assert_not_called()
        self.assertEqual(exit_code, 1)
        log_output = "\n".join(logs.output)
        self.assertIn("boom", log_output)


class ClearDatabaseCliTests(unittest.TestCase):
    def test_clear_database_flag_wipes_content_keeps_file_and_does_not_start_agent(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = str(Path(temp_dir) / "config.yaml")
            database_path = str(Path(temp_dir) / "station.sqlite3")
            Path(config_path).write_text(
                "database:\n"
                f"  path: {database_path}\n"
                "sources:\n"
                "  mock:\n"
                "    enabled: false\n"
                "propagation:\n"
                "  enabled: false\n",
                encoding="utf-8",
            )
            with Database(database_path) as db:
                db.mark_worked("Czech Republic")
                db.log_autotune("OK1ABC", 14_195_000, "SSB", 82, "test reason")

            with self.assertLogs("station_agent.cli", level="INFO") as logs:
                exit_code = main(["--config", config_path, "--clear-database"])

            self.assertEqual(exit_code, 0)
            self.assertTrue(Path(database_path).exists())
            log_output = "\n".join(logs.output)
            self.assertIn("vyčištěna", log_output)

            with Database(database_path) as db:
                self.assertEqual(db.worked_entities(), set())
                self.assertEqual(db.autotune_history(), [])

    def test_clear_database_flag_reports_error_when_database_file_is_invalid(self):
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
                exit_code = main(["--config", config_path, "--clear-database"])
        self.assertEqual(exit_code, 1)
        log_output = "\n".join(logs.output)
        self.assertIn(bad_database_path, log_output)


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
