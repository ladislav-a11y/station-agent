"""Načtení a validace config.yaml.

Pokud je nainstalovaný PyYAML, použije se pro parsování. Jinak se použije
vestavěný minimální YAML parser (``_MiniYamlParser``), který zvládá přesně
ten podmnožinu YAML syntaxe, kterou používá ``config.example.yaml``:
vnořené mapy, skalární hodnoty, seznamy skalárů a komentáře. Díky tomu
projekt funguje i bez jakékoli instalace závislostí.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from station_agent.bearing import maidenhead_to_latlon
from station_agent.modes import SUPPORTED_MODES
from station_agent.bandplan import SUPPORTED_BANDS

LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}

# Jediný zdroj pravdy pro výchozí váhy scoringu -- scoring.py si je odsud
# re-exportuje jako DEFAULT_WEIGHTS, aby nebyly duplikované na dvou místech
# a nerozjížděly se při rozšiřování o nové faktory. Součet musí dát 100 --
# viz tests/test_scoring.py::test_weights_sum_to_100.
DEFAULT_SCORING_WEIGHTS: dict[str, float] = {
    "freshness": 15,
    "sources": 15,
    "needed_dxcc": 25,
    "signal": 10,
    "reliability": 10,
    "propagation": 15,
    "path_dx": 10,
}


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


def _parse_flow_list(text: str) -> list:
    """Naparsuje jednořádkový YAML seznam ve "flow" zápisu, např.
    ``["20m", "15m"]`` -- config.example.yaml ho používá u ``presets.*.bands``
    a ``presets.*.modes``. Bez tohoto by se v prostředí bez PyYAML (viz
    _load_yaml_text, plnohodnotný fallback je záměrně bezzávislostní) celá
    hodnota naparsovala jako doslovný text `_parse_scalar` níže, ne jako
    seznam -- filtr proti SUPPORTED_BANDS/SUPPORTED_MODES v config_from_dict
    by pak neprošel ani jeden znak a předvolba by tiše spadla na výchozí
    "všechna pásma/módy" místo zamýšleného užšího výběru (viz DIAGNOSIS_P5.md)."""
    inner = text[1:-1].strip()
    if not inner:
        return []
    items: list[str] = []
    current = ""
    in_single = in_double = False
    for ch in inner:
        if ch == "'" and not in_double:
            in_single = not in_single
            current += ch
        elif ch == '"' and not in_single:
            in_double = not in_double
            current += ch
        elif ch == "," and not in_single and not in_double:
            items.append(current)
            current = ""
        else:
            current += ch
    if current.strip():
        items.append(current)
    return [_parse_scalar(item) for item in items]


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
    if len(text) >= 2 and text[0] == "[" and text[-1] == "]":
        return _parse_flow_list(text)
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
    except ImportError:
        return _MiniYamlParser(text).parse()
    try:
        return yaml.safe_load(text) or {}
    except yaml.YAMLError as exc:
        # yaml.YAMLError neni podtrida ValueError, takze by bez tohoto
        # prevodu propadl skrz load_config nezachyceny -- cli.py::main
        # odchytava jen FileNotFoundError/ValueError (viz DIAGNOSIS_P5.md),
        # ne kazdou moznou vyjimku z libovolneho YAML parseru.
        raise ValueError(f"Neplatný YAML zápis: {exc}") from exc


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
    weights: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_SCORING_WEIGHTS))


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
class FilterPreset:
    """Pojmenovaná kombinace filtrů pásem/módů pro rychlý výběr v GUI
    ("předvolby") -- čistě lokální UI pohodlí, nesahá na rig ani na žádnou
    externí službu."""

    label: str
    bands: list[str]
    modes: list[str]


# Rozumné výchozí předvolby, použité pokud config.yaml žádné nedefinuje --
# jen kombinace už existujících SUPPORTED_BANDS/SUPPORTED_MODES, nic
# vymyšleného navíc.
DEFAULT_PRESETS: dict[str, FilterPreset] = {
    "all": FilterPreset(label="Vše", bands=list(SUPPORTED_BANDS), modes=list(SUPPORTED_MODES)),
    "ssb": FilterPreset(label="Jen SSB", bands=list(SUPPORTED_BANDS), modes=["SSB"]),
    "cw": FilterPreset(label="Jen CW", bands=list(SUPPORTED_BANDS), modes=["CW"]),
    "digi": FilterPreset(
        label="Jen digi",
        bands=list(SUPPORTED_BANDS),
        modes=["FT8", "FT4", "RTTY", "PSK31", "PSK63", "OTHER_DIGITAL"],
    ),
}


@dataclass
class NotificationsConfig:
    """Band-opening notifikace -- lokálně odvozený signál z aktuálně
    přijatých spotů (žádné externí solar/K-index API, viz scoring.py
    _propagation_reason a aggregator.band_activity). GUI ukazuje jediný
    největší kladný přírůstek naměřený od spuštění (viz notifications.py)."""

    enabled: bool = True
    # Kolik odlišných stanic na pásmu už považujeme za "otevřené pásmo".
    min_distinct_stations: int = 5
    # Minimální doba mezi dvěma notifikacemi pro TENTÝŽ pásmo, i kdyby
    # zůstávalo nepřetržitě otevřené (ochrana proti kolísání kolem prahu).
    cooldown_minutes: float = 30.0
    # Tvrdý strop počtu notifikací za poslední hodinu napříč všemi pásmy.
    max_per_hour: int = 10

    def __post_init__(self) -> None:
        if self.min_distinct_stations < 2:
            raise ValueError(
                "notifications.min_distinct_stations musí být alespoň 2, dostal jsem "
                f"{self.min_distinct_stations!r}"
            )
        if self.cooldown_minutes <= 0:
            raise ValueError(
                f"notifications.cooldown_minutes musí být kladné číslo, dostal jsem {self.cooldown_minutes!r}"
            )
        if self.max_per_hour <= 0:
            raise ValueError(f"notifications.max_per_hour musí být kladné číslo, dostal jsem {self.max_per_hour!r}")


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
        if not 0 <= self.port <= 65535:
            # Bez tohoto by neplatný port (např. překlep s extra číslicí)
            # projel load_config() v pořádku a spadl by až na nezachyceném
            # OverflowError z socket.bind() uvnitř create_server(), které
            # v main() běží mimo try/except (viz DIAGNOSIS_P5.md).
            raise ValueError(f"web.port musí být v rozsahu 0-65535, ne {self.port!r}")


@dataclass
class DatabaseConfig:
    path: str = "station_agent.sqlite3"


@dataclass
class PollingConfig:
    """Frekvence dotazování ŽIVÝCH externích zdrojů (PSKReporter, ...) --

    úmyslně oddělená od frekvence obnovování GUI (to obnovuje tabulku
    kandidátů z DB každých pár sekund bez ohledu na tento interval, viz
    ``web/static/app.js``) i od intervalu vnitřní polling smyčky
    (``--poll-interval``, řídí i AUTO TUNE cyklus). ``source_interval_seconds``
    je minimální doba mezi dvěma reálnými HTTP dotazy na tentýž zdroj --
    výchozí hodnota (60 s) je zvolena tak, aby PSKReporter nikdy nedostával
    dotazy častěji, než jeho API rozumně snese (viz HTTP 429 z živého
    testu).
    """

    source_interval_seconds: float = 60.0
    source_backoff_max_seconds: float = 1800.0

    def __post_init__(self) -> None:
        if self.source_interval_seconds <= 0:
            raise ValueError(
                "polling.source_interval_seconds musí být kladné číslo, "
                f"dostal jsem {self.source_interval_seconds!r}"
            )


@dataclass
class PropagationConfig:
    """Hourly refresh of external propagation evidence."""

    enabled: bool = False
    refresh_seconds: float = 3600.0
    kp_url: str = "https://services.swpc.noaa.gov/products/noaa-planetary-k-index.json"
    sfi_url: str = "https://services.swpc.noaa.gov/json/f107_cm_flux.json"

    def __post_init__(self) -> None:
        if self.refresh_seconds < 3600:
            raise ValueError("propagation.refresh_seconds nesmí být kratší než 3600 sekund")


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
    polling: PollingConfig = field(default_factory=PollingConfig)
    presets: dict[str, FilterPreset] = field(default_factory=lambda: dict(DEFAULT_PRESETS))
    notifications: NotificationsConfig = field(default_factory=NotificationsConfig)
    propagation: PropagationConfig = field(default_factory=PropagationConfig)


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

    polling_raw = raw.get("polling", {}) or {}
    polling = PollingConfig(
        source_interval_seconds=float(polling_raw.get("source_interval_seconds", 60.0)),
        source_backoff_max_seconds=float(polling_raw.get("source_backoff_max_seconds", 1800.0)),
    )

    presets_raw = raw.get("presets", {}) or {}
    if presets_raw:
        presets = {
            str(key): FilterPreset(
                label=str((val or {}).get("label", key)),
                bands=[b for b in ((val or {}).get("bands") or []) if b in SUPPORTED_BANDS] or list(SUPPORTED_BANDS),
                modes=[m for m in ((val or {}).get("modes") or []) if m in SUPPORTED_MODES] or list(SUPPORTED_MODES),
            )
            for key, val in presets_raw.items()
        }
    else:
        presets = dict(DEFAULT_PRESETS)

    notif_raw = raw.get("notifications", {}) or {}
    notifications = NotificationsConfig(
        enabled=bool(notif_raw.get("enabled", True)),
        min_distinct_stations=int(notif_raw.get("min_distinct_stations", 5)),
        cooldown_minutes=float(notif_raw.get("cooldown_minutes", 30.0)),
        max_per_hour=int(notif_raw.get("max_per_hour", 10)),
    )

    propagation_raw = raw.get("propagation", {}) or {}
    propagation = PropagationConfig(
        # Keep an explicit opt-out, but enable the new propagation contract
        # for older user configs which predate this section.  Otherwise an
        # upgrade leaves the GUI permanently at "Kp: nedostupné" even though
        # the distributed example enables the feature.
        enabled=bool(propagation_raw.get("enabled", True)),
        refresh_seconds=float(propagation_raw.get("refresh_seconds", 3600.0)),
        kp_url=str(propagation_raw.get("kp_url", PropagationConfig().kp_url)),
        sfi_url=str(propagation_raw.get("sfi_url", PropagationConfig().sfi_url)),
    )

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
        polling=polling,
        presets=presets,
        notifications=notifications,
        propagation=propagation,
    )


def load_config(path: str | Path) -> AppConfig:
    config_path = Path(path)
    if not config_path.is_file():
        if config_path.exists():
            # Existuje (adresář, pojmenovaná roura apod.), jen to není
            # čitelný soubor -- návod "zkopíruj příklad" by byl zavádějící,
            # protože cílová cesta už je obsazená něčím jiným.
            raise FileNotFoundError(
                f"Konfigurační cesta '{config_path}' existuje, ale není to "
                "soubor (je to pravděpodobně adresář). Zadej --config s "
                "cestou k platnému YAML souboru."
            )
        example_path = Path(__file__).resolve().parent.parent / "config.example.yaml"
        # README dokumentuje `copy` pro Windows (sekce "Instalace a spuštění
        # na Windows 11") a `cp` pro bash/PowerShell (sekce "Instalace").
        # `cp` v syrovém cmd.exe (na rozdíl od PowerShell, kde je aliasovaný
        # na Copy-Item) není vestavěný příkaz, proto na Windows nabídneme
        # rovnou funkční `copy`, aby šel navrhovaný příkaz spustit beze změny.
        copy_cmd = "copy" if os.name == "nt" else "cp"
        hint = (
            f"Konfigurační soubor '{config_path}' neexistuje. "
            f"Zkopíruj příklad a uprav ho: {copy_cmd} {example_path} {config_path} "
            "(viz README.md, sekce Instalace)."
        )
        if not config_path.parent.exists():
            # Bez tohoto upozornění by výše navržený copy/cp příkaz selhal
            # podruhé se zavádějící hláškou (cílový adresář neexistuje) --
            # uživatel by nevěděl, že musí nejdřív vytvořit adresář, ne znovu
            # opravovat cestu k souboru.
            hint += (
                f" Pozor, ani nadřazený adresář '{config_path.parent}' zatím "
                "neexistuje -- je potřeba ho nejdřív vytvořit."
            )
        raise FileNotFoundError(hint)
    text = config_path.read_text(encoding="utf-8")
    raw = _load_yaml_text(text)
    if raw is not None and not isinstance(raw, dict):
        # Validní YAML, ale ne mapování na nejvyšší úrovni (např. omylem
        # vložený seznam nebo holý skalár) -- bez téhle hlídky by
        # config_from_dict spadl na nezachyceném AttributeError z `raw.get(...)`,
        # stejná třída "Station Agent nejde spustit" jako u chybějícího
        # souboru nebo neplatného YAML zápisu (viz DIAGNOSIS_P5.md).
        raise ValueError(
            f"Konfigurace '{config_path}' musí být na nejvyšší úrovni YAML mapování "
            f"(klíč: hodnota), ne {type(raw).__name__}. Zkontroluj strukturu proti "
            f"config.example.yaml."
        )
    try:
        return config_from_dict(raw)
    except TypeError as exc:
        # Prázdná (explicitně `null`) hodnota u číselného pole -- např.
        # "rigctld_port:" bez hodnoty za dvojtečkou -- se z YAML naparsuje
        # jako None, na rozdíl od chybějícího klíče (ten by použil výchozí
        # hodnotu). config_from_dict pak volá int(None)/float(None), což
        # vyhazuje TypeError, ne ValueError -- bez tohoto převodu by to
        # cli.py::main() (odchytává jen FileNotFoundError/ValueError, viz
        # DIAGNOSIS_P5.md) nezachytil a spadl by na nezachyceném tracebacku
        # stejně jako dřív u ostatních neplatných hodnot v config.yaml.
        raise ValueError(
            f"Konfigurace '{config_path}' obsahuje prázdnou nebo neplatnou hodnotu "
            f"u číselného pole: {exc}. Zkontroluj, že za každým ':' u číselných "
            "políček (porty, intervaly, prahy) je vyplněná hodnota, nebo řádek "
            "z config.yaml úplně smaž, ať se použije výchozí hodnota."
        ) from exc
