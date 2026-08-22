import tempfile
import unittest
from pathlib import Path

from station_agent.config import PollingConfig, WebConfig, _MiniYamlParser, load_config

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


if __name__ == "__main__":
    unittest.main()
