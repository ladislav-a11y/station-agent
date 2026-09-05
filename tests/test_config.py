import os
import tempfile
import unittest
from pathlib import Path

from station_agent.bandplan import SUPPORTED_BANDS
from station_agent.modes import SUPPORTED_MODES
from station_agent.config import (
    NotificationsConfig,
    PollingConfig,
    QRZConfig,
    StationConfig,
    WebConfig,
    _MiniYamlParser,
    config_from_dict,
    load_config,
)

REPO_ROOT = Path(__file__).resolve().parent.parent

MINIMAL_YAML = """
station:
  callsign: "OK1TEST"
  qth_locator: "JN79FG"
rig:
  mode: mock
  rigctld_port: 4532
bands:
  - "20m"
  - "40m"
modes:
  - "SSB"
  - "FT8"
scoring:
  min_score: 55
  weights:
    freshness: 25
    sources: 20
    needed_dxcc: 35
    signal: 20
autotune:
  enabled: true
  hold: false
  min_hold_seconds: 90
  min_score_delta: 5
sources:
  mock:
    enabled: true
  dx_cluster:
    enabled: false
    host: "example.net"
    port: 7300
log4om:
  enabled: false
  host: "127.0.0.1"
  port: 2333
web:
  host: "127.0.0.1"
  port: 9999
database:
  path: "test.sqlite3"
"""


class MiniYamlParserTests(unittest.TestCase):
    def test_parses_nested_structure(self):
        parsed = _MiniYamlParser(MINIMAL_YAML).parse()
        self.assertEqual(parsed["station"]["callsign"], "OK1TEST")
        self.assertEqual(parsed["bands"], ["20m", "40m"])
        self.assertEqual(parsed["rig"]["rigctld_port"], 4532)
        self.assertEqual(parsed["autotune"]["enabled"], True)
        self.assertEqual(parsed["sources"]["dx_cluster"]["host"], "example.net")

    def test_strips_comments(self):
        text = "a: 1  # a comment\nb: 2\n"
        parsed = _MiniYamlParser(text).parse()
        self.assertEqual(parsed, {"a": 1, "b": 2})


class LoadConfigTests(unittest.TestCase):
    def test_station_coordinates_distinguish_unknown_from_invalid(self):
        self.assertIsNone(StationConfig().get_latlon())
        with self.assertRaisesRegex(ValueError, "uvedeny společně"):
            StationConfig(latitude=50.0).get_latlon()
        with self.assertRaisesRegex(ValueError, "mimo rozsah"):
            StationConfig(latitude=95.0, longitude=14.0).get_latlon()

    def test_load_minimal_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.yaml"
            path.write_text(MINIMAL_YAML, encoding="utf-8")
            config = load_config(path)

        self.assertEqual(config.station.callsign, "OK1TEST")
        self.assertEqual(config.rig.mode, "mock")
        self.assertEqual(config.bands, ["20m", "40m"])
        self.assertEqual(config.scoring.min_score, 55)
        self.assertTrue(config.autotune.enabled)
        self.assertEqual(config.autotune.min_hold_seconds, 90)
        self.assertEqual(config.autotune.min_score_delta, 5)
        self.assertFalse(config.sources["dx_cluster"].enabled)
        self.assertEqual(config.sources["dx_cluster"].options["host"], "example.net")
        self.assertEqual(config.log4om.host, "127.0.0.1")
        self.assertEqual(config.log4om.port, 2333)
        self.assertEqual(config.web.port, 9999)
        self.assertTrue(config.propagation.enabled)

    def test_missing_config_file_raises_actionable_error(self):
        # Fresh checkout nemá commitnutý config.yaml (viz .gitignore) -- bez
        # této hlídky by load_config selhal syrovým FileNotFoundError bez
        # návodu, jak si vlastní config vytvořit (viz README.md, sekce
        # Instalace: `cp`/`copy config.example.yaml config.yaml`).
        with tempfile.TemporaryDirectory() as tmp:
            missing_path = Path(tmp) / "config.yaml"
            with self.assertRaises(FileNotFoundError) as ctx:
                load_config(missing_path)
        message = str(ctx.exception)
        self.assertIn(str(missing_path), message)
        # Návrhový příkaz musí obsahovat plnou cestu k example configu, ne
        # jen holé jméno souboru -- jinak "cp config.example.yaml ..." selže,
        # pokud uživatel/orchestrátor spustí agenta z jiného pracovního
        # adresáře, než je kořen repozitáře.
        self.assertIn(str(REPO_ROOT / "config.example.yaml"), message)
        # Na Windows (primární cílová platforma, viz README "Instalace a
        # spuštění na Windows 11") musí návod použít `copy` -- syrový cmd.exe
        # (na rozdíl od PowerShell, kde je `cp` aliasovaný na Copy-Item) nemá
        # `cp` jako vestavěný příkaz, takže by navrhovaný příkaz jinak selhal.
        expected_copy_cmd = "copy" if os.name == "nt" else "cp"
        self.assertIn(f"{expected_copy_cmd} {REPO_ROOT / 'config.example.yaml'}", message)
        # Nadřazený adresář (tmp) existuje, takže navržený copy/cp příkaz je
        # rovnou spustitelný -- žádné dodatečné varování o chybějícím
        # adresáři tu být nemá (viz test níže pro opačný případ).
        self.assertNotIn("nadřazený adresář", message)

    def test_missing_config_file_with_missing_parent_dir_warns_about_it(self):
        # Pokud --config ukazuje do adresáře, který vůbec neexistuje (např.
        # překlep v cestě), navržený "cp config.example.yaml <cesta>" by
        # selhal podruhé se zavádějící hláškou. Hláška proto musí uživatele
        # upozornit, že je potřeba nejdřív vytvořit nadřazený adresář.
        with tempfile.TemporaryDirectory() as tmp:
            missing_path = Path(tmp) / "no_such_subdir" / "config.yaml"
            with self.assertRaises(FileNotFoundError) as ctx:
                load_config(missing_path)
        message = str(ctx.exception)
        self.assertIn(str(missing_path.parent), message)
        self.assertIn("nadřazený adresář", message)

    def test_config_path_pointing_at_directory_raises_distinct_error(self):
        # Pokud --config omylem ukazuje na existující adresář (např. překlep
        # nebo zbylá složka se stejným jménem), hláška "neexistuje" spolu s
        # návodem "zkopíruj příklad na tuto cestu" by byla zavádějící --
        # cesta už obsazená je, jen to není soubor.
        with tempfile.TemporaryDirectory() as tmp:
            directory_path = Path(tmp) / "config.yaml"
            directory_path.mkdir()
            with self.assertRaises(FileNotFoundError) as ctx:
                load_config(directory_path)
        message = str(ctx.exception)
        self.assertIn(str(directory_path), message)
        self.assertNotIn("neexistuje", message)
        self.assertNotIn("Zkopíruj příklad", message)

    def test_malformed_yaml_content_raises_value_error_not_yaml_error(self):
        # Když je nainstalovaný PyYAML (viz requirements.txt, nepovinné), je
        # yaml.YAMLError odlišná třída než ValueError -- bez převodu v
        # _load_yaml_text by tahle chyba propadla skrz load_config
        # nezachycená přes cli.py::main (ten odchytává jen FileNotFoundError
        # a ValueError, viz DIAGNOSIS_P5.md). Tab uvnitř odsazení je platný
        # důvod k selhání parsování v PyYAML.
        try:
            import yaml  # noqa: F401
        except ImportError:
            self.skipTest("PyYAML není nainstalovaný -- vestavěný fallback parser tento vstup toleruje jinak")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.yaml"
            path.write_text("station:\n  callsign: OK1TEST\n\tqth_locator: JO70\n", encoding="utf-8")
            with self.assertRaises(ValueError) as ctx:
                load_config(path)
        self.assertNotIsInstance(ctx.exception, FileNotFoundError)
        self.assertIn("YAML", str(ctx.exception))

    def test_top_level_yaml_list_raises_actionable_value_error(self):
        # Validní YAML, ale ne mapování na nejvyšší úrovni (např. omylem
        # vložený seznam) -- bez hlídky v load_config by config_from_dict
        # spadl na nezachyceném AttributeError z `raw.get(...)`. Reprodukuje
        # se stejně s PyYAML i s vestavěným _MiniYamlParser fallbackem, viz
        # DIAGNOSIS_P5.md.
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.yaml"
            path.write_text("- foo\n- bar\n", encoding="utf-8")
            with self.assertRaises(ValueError) as ctx:
                load_config(path)
        message = str(ctx.exception)
        self.assertNotIsInstance(ctx.exception, FileNotFoundError)
        self.assertIn(str(path), message)
        self.assertIn("mapování", message)

    def test_explicit_null_numeric_field_raises_actionable_value_error(self):
        # "rigctld_port:" bez hodnoty za dvojtečkou je platný YAML (klíč
        # existuje, hodnota je None) -- na rozdíl od chybějícího klíče se
        # proto nepoužije výchozí hodnota a config_from_dict zavolá
        # int(None), což vyhazuje TypeError, ne ValueError. Bez převodu v
        # load_config by tahle chyba propadla skrz cli.py::main nezachycená
        # (ten odchytává jen FileNotFoundError a ValueError, viz
        # DIAGNOSIS_P5.md).
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.yaml"
            path.write_text(
                "station:\n  callsign: OK1TEST\nrig:\n  mode: mock\n  rigctld_port:\n",
                encoding="utf-8",
            )
            with self.assertRaises(ValueError) as ctx:
                load_config(path)
        self.assertNotIsInstance(ctx.exception, FileNotFoundError)
        self.assertNotIsInstance(ctx.exception, TypeError)
        self.assertIn(str(path), str(ctx.exception))

    def test_propagation_can_be_explicitly_disabled(self):
        config = config_from_dict({"propagation": {"enabled": False}})
        self.assertFalse(config.propagation.enabled)

    def test_polling_defaults_when_section_missing(self):
        # MINIMAL_YAML výše nemá žádnou sekci `polling:` -- musí se použít
        # bezpečný výchozí interval (>= 60s), aby živé zdroje (PSKReporter)
        # nikdy nebyly dotazovány častěji, i když si uživatel config.yaml
        # nedoplní.
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.yaml"
            path.write_text(MINIMAL_YAML, encoding="utf-8")
            config = load_config(path)
        self.assertGreaterEqual(config.polling.source_interval_seconds, 60.0)
        self.assertEqual(config.polling.source_backoff_max_seconds, 1800.0)

    def test_polling_section_is_parsed(self):
        yaml_text = MINIMAL_YAML + (
            "\npolling:\n  source_interval_seconds: 90\n  source_backoff_max_seconds: 600\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.yaml"
            path.write_text(yaml_text, encoding="utf-8")
            config = load_config(path)
        self.assertEqual(config.polling.source_interval_seconds, 90.0)
        self.assertEqual(config.polling.source_backoff_max_seconds, 600.0)

    def test_example_config_loads(self):
        config = load_config(REPO_ROOT / "config.example.yaml")
        self.assertEqual(config.rig.mode, "mock")
        self.assertEqual(config.web.host, "127.0.0.1")
        self.assertFalse(config.autotune.enabled)
        self.assertFalse(config.sources["dx_cluster"].enabled)
        self.assertFalse(config.sources["rbn"].enabled)
        self.assertFalse(config.sources["pskreporter"].enabled)
        self.assertFalse(config.log4om.enabled)
        self.assertEqual(sum(config.scoring.weights.values()), 100)
        self.assertGreaterEqual(config.polling.source_interval_seconds, 60.0)


class PollingConfigSafetyTests(unittest.TestCase):
    def test_rejects_non_positive_interval(self):
        with self.assertRaises(ValueError):
            PollingConfig(source_interval_seconds=0)

    def test_default_interval_is_at_least_60s(self):
        self.assertGreaterEqual(PollingConfig().source_interval_seconds, 60.0)


class WebConfigSafetyTests(unittest.TestCase):
    def test_rejects_non_loopback_host(self):
        with self.assertRaises(ValueError):
            WebConfig(host="0.0.0.0", port=8765)

    def test_accepts_loopback_hosts(self):
        WebConfig(host="127.0.0.1", port=8765)
        WebConfig(host="localhost", port=8765)

    def test_rejects_port_out_of_valid_range(self):
        # Bez tohoto by neplatny web.port (napr. preklep s extra cislici)
        # projel load_config() v poradku a spadl az na nezachycenem
        # OverflowError ze socket.bind() uvnitr create_server(), ktere v
        # cli.main() bezi mimo try/except (viz DIAGNOSIS_P5.md).
        with self.assertRaises(ValueError):
            WebConfig(host="127.0.0.1", port=999999)
        with self.assertRaises(ValueError):
            WebConfig(host="127.0.0.1", port=-1)

    def test_accepts_port_at_range_boundaries(self):
        WebConfig(host="127.0.0.1", port=0)
        WebConfig(host="127.0.0.1", port=65535)


class QRZConfigSafetyTests(unittest.TestCase):
    def test_disabled_by_default(self):
        config = config_from_dict({})
        self.assertFalse(config.qrz.enabled)
        self.assertEqual(config.qrz.username, "")
        self.assertEqual(config.qrz.password, "")

    def test_enabled_without_credentials_raises(self):
        with self.assertRaises(ValueError):
            QRZConfig(enabled=True, username="", password="")
        with self.assertRaises(ValueError):
            QRZConfig(enabled=True, username="OK1ABC", password="")

    def test_enabled_with_credentials_is_accepted(self):
        cfg = QRZConfig(enabled=True, username="OK1ABC", password="secret")
        self.assertTrue(cfg.enabled)

    def test_repr_never_exposes_plaintext_password(self):
        cfg = QRZConfig(enabled=True, username="OK1ABC", password="s3cr3t-p4ss")
        self.assertNotIn("s3cr3t-p4ss", repr(cfg))
        self.assertNotIn("s3cr3t-p4ss", str(cfg))
        self.assertIn("OK1ABC", repr(cfg))

    def test_repr_of_empty_password_does_not_claim_it_is_set(self):
        cfg = QRZConfig()
        self.assertNotIn("***", repr(cfg))

    def test_rejects_non_positive_timeout(self):
        with self.assertRaises(ValueError):
            QRZConfig(timeout_s=0)

    def test_parsed_from_raw_dict(self):
        raw = {
            "qrz": {
                "enabled": True,
                "username": "OK1ABC",
                "password": "secret",
                "timeout_s": 5,
                "cache_ttl_seconds": 3600,
            }
        }
        config = config_from_dict(raw)
        self.assertTrue(config.qrz.enabled)
        self.assertEqual(config.qrz.username, "OK1ABC")
        self.assertEqual(config.qrz.password, "secret")
        self.assertEqual(config.qrz.timeout_s, 5.0)
        self.assertEqual(config.qrz.cache_ttl_seconds, 3600.0)


class PresetsConfigTests(unittest.TestCase):
    def test_default_presets_used_when_section_missing(self):
        config = config_from_dict({})
        self.assertIn("all", config.presets)
        self.assertEqual(config.presets["all"].bands, list(SUPPORTED_BANDS))
        self.assertEqual(config.presets["all"].modes, list(SUPPORTED_MODES))

    def test_custom_presets_parsed_from_dict_of_dicts(self):
        raw = {
            "presets": {
                "ssb_dx": {"label": "SSB DX", "bands": ["20m", "15m"], "modes": ["SSB"]},
            }
        }
        config = config_from_dict(raw)
        self.assertEqual(set(config.presets.keys()), {"ssb_dx"})
        preset = config.presets["ssb_dx"]
        self.assertEqual(preset.label, "SSB DX")
        self.assertEqual(preset.bands, ["20m", "15m"])
        self.assertEqual(preset.modes, ["SSB"])

    def test_unknown_bands_and_modes_in_preset_are_filtered_out(self):
        raw = {"presets": {"weird": {"label": "x", "bands": ["20m", "999m"], "modes": ["SSB", "MORSE"]}}}
        config = config_from_dict(raw)
        self.assertEqual(config.presets["weird"].bands, ["20m"])
        self.assertEqual(config.presets["weird"].modes, ["SSB"])

    def test_mini_yaml_parser_handles_nested_preset_dict(self):
        text = (
            "presets:\n"
            "  ssb_dx:\n"
            "    label: \"SSB DX\"\n"
            "    bands:\n"
            "      - \"20m\"\n"
            "    modes:\n"
            "      - \"SSB\"\n"
        )
        parsed = _MiniYamlParser(text).parse()
        config = config_from_dict(parsed)
        self.assertEqual(config.presets["ssb_dx"].label, "SSB DX")
        self.assertEqual(config.presets["ssb_dx"].bands, ["20m"])

    def test_mini_yaml_parser_handles_inline_flow_style_list(self):
        # config.example.yaml (viz presets sekce) používá jednořádkový
        # "flow" zápis seznamu -- bands: ["20m", "15m"] -- ne blokový
        # zápis s "-". Bez podpory v _parse_scalar by se celá hodnota
        # naparsovala jako doslovný text, filtr proti SUPPORTED_BANDS by
        # neprošel ani jeden znak a předvolba by tiše spadla na výchozí
        # "všechna pásma/módy" místo zamýšleného užšího výběru -- reálně
        # reprodukováno přímo na distribuovaném config.example.yaml v
        # prostředí bez PyYAML (viz DIAGNOSIS_P5.md).
        text = (
            "presets:\n"
            "  ssb_dx:\n"
            "    label: \"SSB DX\"\n"
            "    bands: [\"20m\", \"15m\"]\n"
            "    modes: [\"SSB\"]\n"
        )
        parsed = _MiniYamlParser(text).parse()
        self.assertEqual(parsed["presets"]["ssb_dx"]["bands"], ["20m", "15m"])
        config = config_from_dict(parsed)
        self.assertEqual(config.presets["ssb_dx"].bands, ["20m", "15m"])
        self.assertEqual(config.presets["ssb_dx"].modes, ["SSB"])

    def test_mini_yaml_parser_parses_config_example_presets_correctly(self):
        # End-to-end regrese na skutečném distribuovaném souboru, který
        # README nabádá zkopírovat jako config.yaml (viz load_config) --
        # ověřuje, že "ssb"/"cw"/"digi" předvolby v config.example.yaml
        # zůstanou po parsování bez PyYAML skutečně užší než "all", ne
        # tiše nahrazené plnou sadou pásem/módů.
        text = (REPO_ROOT / "config.example.yaml").read_text(encoding="utf-8")
        parsed = _MiniYamlParser(text).parse()
        config = config_from_dict(parsed)
        self.assertEqual(config.presets["ssb"].modes, ["SSB"])
        self.assertEqual(config.presets["cw"].modes, ["CW"])
        self.assertNotEqual(config.presets["digi"].modes, config.presets["all"].modes)


class NotificationsConfigTests(unittest.TestCase):
    def test_defaults(self):
        cfg = NotificationsConfig()
        self.assertTrue(cfg.enabled)
        self.assertGreaterEqual(cfg.min_distinct_stations, 2)
        self.assertGreater(cfg.cooldown_minutes, 0)
        self.assertGreater(cfg.max_per_hour, 0)

    def test_rejects_too_low_min_distinct_stations(self):
        with self.assertRaises(ValueError):
            NotificationsConfig(min_distinct_stations=1)

    def test_rejects_non_positive_cooldown(self):
        with self.assertRaises(ValueError):
            NotificationsConfig(cooldown_minutes=0)

    def test_rejects_non_positive_max_per_hour(self):
        with self.assertRaises(ValueError):
            NotificationsConfig(max_per_hour=0)

    def test_parsed_from_dict(self):
        raw = {"notifications": {"enabled": False, "min_distinct_stations": 3, "cooldown_minutes": 10, "max_per_hour": 4}}
        config = config_from_dict(raw)
        self.assertFalse(config.notifications.enabled)
        self.assertEqual(config.notifications.min_distinct_stations, 3)
        self.assertEqual(config.notifications.cooldown_minutes, 10)
        self.assertEqual(config.notifications.max_per_hour, 4)


if __name__ == "__main__":
    unittest.main()
