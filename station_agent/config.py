"""Načtení a validace config.yaml.

Pokud je nainstalovaný PyYAML, použije se pro parsování. Jinak se použije
vestavěný minimální YAML parser (``_MiniYamlParser``), který zvládá přesně
ten podmnožinu YAML syntaxe, kterou používá ``config.example.yaml``:
vnořené mapy, skalární hodnoty, seznamy skalárů a komentáře. Díky tomu
projekt funguje i bez jakékoli instalace závislostí.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from station_agent.bearing import maidenhead_to_latlon
from station_agent.modes import SUPPORTED_MODES
from station_agent.bandplan import SUPPORTED_BANDS

LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


# ---------------------------------------------------------------------------
# Minimální vestavěný YAML parser (fallback, když není PyYAML)
# ---------------------------------------------------------------------------


def _strip_comment(line: str) -> str:
    in_single = in_double = False
    for i, ch in enumerate(line):
        if ch == "'" and not in_double:
            in_single = not in_single
        elif ch == '"' and not in_single:
            in_double = not in_double
        elif ch == "#" and not in_single and not in_double:
            if i == 0 or line[i - 1].isspace():
                return line[:i]
    return line


def _parse_scalar(text: str) -> Any:
    text = text.strip()
    if text == "" or text.lower() in ("null", "~"):
        return None
    if text.lower() == "true":
        return True
    if text.lower() == "false":
        return False
    if len(text) >= 2 and text[0] == text[-1] and text[0] in ("'", '"'):
        return text[1:-1]
    try:
        return int(text)
    except ValueError:
        pass
    try:
        return float(text)
    except ValueError:
        pass
    return text


class _MiniYamlParser:
    def __init__(self, text: str):
        self.lines: list[tuple[int, str]] = []
        for raw in text.splitlines():
            no_comment = _strip_comment(raw).rstrip()
            if no_comment.strip() == "":
                continue
            indent = len(no_comment) - len(no_comment.lstrip(" "))
            self.lines.append((indent, no_comment.strip()))
        self.pos = 0

    def parse(self) -> dict:
        if not self.lines:
            return {}
        return self._parse_block(self.lines[0][0])

    def _parse_block(self, indent: int):
        result: dict | list | None = None
        while self.pos < len(self.lines):
            cur_indent, content = self.lines[self.pos]
            if cur_indent < indent:
                break
            if cur_indent > indent:
                raise ValueError(f"Neočekávaná odsazení v configu: {content!r}")

            if content.startswith("- "):
                if result is None:
                    result = []
                item = content[2:].strip()
                self.pos += 1
                result.append(_parse_scalar(item))
            else:
                if result is None:
                    result = {}
                key, sep, rest = content.partition(":")
                if not sep:
                    raise ValueError(f"Řádek configu bez ':' -- {content!r}")
                key = key.strip()
                rest = rest.strip()
                self.pos += 1
                if rest == "":
                    if self.pos < len(self.lines) and self.lines[self.pos][0] > indent:
                        value = self._parse_block(self.lines[self.pos][0])
                    else:
                        value = None
                else:
                    value = _parse_scalar(rest)
                result[key] = value
        return result if result is not None else {}


def _load_yaml_text(text: str) -> dict:
    try:
        import yaml  # type: ignore

        return yaml.safe_load(text) or {}
    except ImportError:
        return _MiniYamlParser(text).parse()


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class StationConfig:
    callsign: str = ""
    qth_locator: str | None = None
    latitude: float | None = None
    longitude: float | None = None

    def get_latlon(self) -> tuple[float, float]:
        if self.qth_locator:
            return maidenhead_to_latlon(self.qth_locator)
        if self.latitude is not None and self.longitude is not None:
            return (self.latitude, self.longitude)
        raise ValueError(
            "QTH není nakonfigurováno -- vyplň station.qth_locator nebo "
            "station.latitude/station.longitude v config.yaml"
        )


@dataclass
class RigConfig:
    mode: str = "mock"  # "mock" (výchozí) nebo "live"
    rigctld_host: str = "127.0.0.1"
    rigctld_port: int = 4532
    model: str = "IC-7300"

    def __post_init__(self) -> None:
        if self.mode not in ("mock", "live"):
            raise ValueError(f"rig.mode musí být 'mock' nebo 'live', ne {self.mode!r}")


@dataclass
class ScoringConfig:
    min_score: int = 60
    spot_max_age_minutes: float = 15.0
    weights: dict[str, float] = field(
        default_factory=lambda: {
            "freshness": 25,
            "sources": 20,
            "needed_dxcc": 35,
            "signal": 20,
        }
    )


@dataclass
class AutoTuneConfig:
    enabled: bool = False
    hold: bool = False
    min_hold_seconds: float = 120.0
    min_score_delta: float = 8.0


@dataclass
class SourceConfig:
    enabled: bool = False
    options: dict[str, Any] = field(default_factory=dict)


@dataclass
class Log4OMConfig:
    enabled: bool = False
    host: str = "127.0.0.1"
    port: int = 2333


@dataclass
class WebConfig:
    host: str = "127.0.0.1"
    port: int = 8765

    def __post_init__(self) -> None:
        if self.host not in LOOPBACK_HOSTS:
            raise ValueError(
                f"web.host musí být loopback adresa {sorted(LOOPBACK_HOSTS)}, ne {self.host!r} "
                "-- GUI smí běžet pouze na localhost."
            )


@dataclass
class DatabaseConfig:
    path: str = "station_agent.sqlite3"


@dataclass
class AppConfig:
    station: StationConfig = field(default_factory=StationConfig)
    rig: RigConfig = field(default_factory=RigConfig)
    bands: list[str] = field(default_factory=lambda: list(SUPPORTED_BANDS))
    modes: list[str] = field(default_factory=lambda: list(SUPPORTED_MODES))
    scoring: ScoringConfig = field(default_factory=ScoringConfig)
    autotune: AutoTuneConfig = field(default_factory=AutoTuneConfig)
    sources: dict[str, SourceConfig] = field(default_factory=dict)
    log4om: Log4OMConfig = field(default_factory=Log4OMConfig)
    web: WebConfig = field(default_factory=WebConfig)
    database: DatabaseConfig = field(default_factory=DatabaseConfig)


def _build_source_config(raw: dict) -> SourceConfig:
    raw = dict(raw or {})
    enabled = bool(raw.pop("enabled", False))
    return SourceConfig(enabled=enabled, options=raw)


def config_from_dict(raw: dict) -> AppConfig:
    raw = raw or {}

    station_raw = raw.get("station", {}) or {}
    station = StationConfig(
        callsign=station_raw.get("callsign", ""),
        qth_locator=station_raw.get("qth_locator"),
        latitude=station_raw.get("latitude"),
        longitude=station_raw.get("longitude"),
    )

    rig_raw = raw.get("rig", {}) or {}
    rig = RigConfig(
        mode=rig_raw.get("mode", "mock"),
        rigctld_host=rig_raw.get("rigctld_host", "127.0.0.1"),
        rigctld_port=int(rig_raw.get("rigctld_port", 4532)),
        model=rig_raw.get("model", "IC-7300"),
    )

    bands = list(raw.get("bands") or SUPPORTED_BANDS)
    modes = list(raw.get("modes") or SUPPORTED_MODES)

    scoring_raw = raw.get("scoring", {}) or {}
    weights = dict(scoring_raw.get("weights") or {})
    scoring = ScoringConfig(
        min_score=int(scoring_raw.get("min_score", 60)),
        spot_max_age_minutes=float(scoring_raw.get("spot_max_age_minutes", 15.0)),
        weights=weights or ScoringConfig().weights,
    )

    autotune_raw = raw.get("autotune", {}) or {}
    autotune = AutoTuneConfig(
        enabled=bool(autotune_raw.get("enabled", False)),
        hold=bool(autotune_raw.get("hold", False)),
        min_hold_seconds=float(autotune_raw.get("min_hold_seconds", 120.0)),
        min_score_delta=float(autotune_raw.get("min_score_delta", 8.0)),
    )

    sources_raw = raw.get("sources", {}) or {}
    sources = {name: _build_source_config(cfg) for name, cfg in sources_raw.items()}

    log4om_raw = raw.get("log4om", {}) or {}
    log4om = Log4OMConfig(
        enabled=bool(log4om_raw.get("enabled", False)),
        host=log4om_raw.get("host", "127.0.0.1"),
        port=int(log4om_raw.get("port", 2333)),
    )

    web_raw = raw.get("web", {}) or {}
    web = WebConfig(
        host=web_raw.get("host", "127.0.0.1"),
        port=int(web_raw.get("port", 8765)),
    )

    db_raw = raw.get("database", {}) or {}
    database = DatabaseConfig(path=db_raw.get("path", "station_agent.sqlite3"))

    return AppConfig(
        station=station,
        rig=rig,
        bands=bands,
        modes=modes,
        scoring=scoring,
        autotune=autotune,
        sources=sources,
        log4om=log4om,
        web=web,
        database=database,
    )


def load_config(path: str | Path) -> AppConfig:
    text = Path(path).read_text(encoding="utf-8")
    raw = _load_yaml_text(text)
    return config_from_dict(raw)
