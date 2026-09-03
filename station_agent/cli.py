"""Entry point: `python -m station_agent` / `station-agent`."""

from __future__ import annotations

import argparse
import logging
import sqlite3
import sys

from station_agent.adapters.dx_cluster import DXClusterAdapter, RECOMMENDED_PROVIDERS
from station_agent.adapters.mock import MockAdapter
from station_agent.adapters.pskreporter import PSKReporterAdapter
from station_agent.adapters.rbn import RBNAdapter
from station_agent.aggregator import Aggregator
from station_agent.app_state import AppState, PollingLoop
from station_agent.bandplan import SUPPORTED_BANDS
from station_agent.config import AppConfig, load_config
from station_agent.db import Database
from station_agent.modes import SUPPORTED_MODES
from station_agent.rig import create_rig_control
from station_agent.web.server import create_server

logger = logging.getLogger(__name__)


def build_sources(config: AppConfig) -> list:
    sources = []
    if config.sources.get("mock", None) is None or config.sources["mock"].enabled:
        sources.append(MockAdapter())
    # Libovolný počet pojmenovaných cluster uzlů může běžet nezávisle. Přesný
    # název se zachová i ve Spot.source, aby agregace neslila dva poskytovatele
    # do jediné evidence.
    for source_name, dxc in config.sources.items():
        if (source_name == "dx_cluster" or source_name.startswith("dx_cluster_")) and dxc.enabled:
            default_host, default_port = RECOMMENDED_PROVIDERS.get(
                source_name,
                (DXClusterAdapter.DEFAULT_HOST, DXClusterAdapter.DEFAULT_PORT),
            )
            sources.append(DXClusterAdapter(
                host=dxc.options.get("host", default_host),
                port=int(dxc.options.get("port", default_port)),
                callsign=dxc.options.get("callsign", config.station.callsign),
                source_name=source_name,
            ))
    rbn = config.sources.get("rbn")
    if rbn and rbn.enabled:
        sources.append(
            RBNAdapter(
                host=rbn.options.get("host", RBNAdapter.DEFAULT_HOST),
                port=int(rbn.options.get("port", RBNAdapter.DEFAULT_PORT)),
                callsign=rbn.options.get("callsign", config.station.callsign),
            )
        )
    pskr = config.sources.get("pskreporter")
    if pskr and pskr.enabled:
        options = dict(pskr.options)
        query_url = options.pop("query_url", None) or "https://retrieve.pskreporter.info/query"
        timeout_s = float(options.pop("timeout_s", 15.0))
        sources.append(PSKReporterAdapter(query_url=query_url, params=options, timeout_s=timeout_s))
    return sources


def build_app_state(config: AppConfig) -> AppState:
    try:
        db = Database(config.database.path)
    except sqlite3.DatabaseError as exc:
        # sqlite3.DatabaseError pokrývá dvě reálné třídy "Station Agent
        # nejde spustit" na database.path: podtřídu OperationalError (např.
        # nadřazený adresář neexistuje) i samostatný DatabaseError, když
        # cesta míří na existující soubor, který ale není platná SQLite
        # databáze (poškozený/cizí soubor na tom místě -- "file is not a
        # database"). Bez tohoto převodu by main() spadl na nezachyceném
        # tracebacku (cli.main odchytává jen FileNotFoundError/ValueError),
        # stejná třída chyby jako ostatní problémy v config.yaml (viz
        # DIAGNOSIS_P5.md).
        raise ValueError(
            f"Nelze otevřít databázi '{config.database.path}' (database.path "
            f"v config.yaml): {exc}. Zkontroluj, že nadřazený adresář existuje, "
            "máš do něj právo zápisu a že soubor (pokud existuje) je platná "
            "SQLite databáze."
        ) from exc
    rig = None
    try:
        saved_filters = db.load_filter_preferences()
        if saved_filters is not None:
            saved_bands, saved_modes = saved_filters
            valid_bands = [band for band in saved_bands if band in SUPPORTED_BANDS]
            valid_modes = [mode for mode in saved_modes if mode in SUPPORTED_MODES]
            config.bands = valid_bands
            config.modes = valid_modes
        rig = create_rig_control(config.rig)
        try:
            qth_latlon = config.station.get_latlon()
        except ValueError as exc:
            logger.warning("QTH není nakonfigurováno, bearing nebude dostupný: %s", exc)
            qth_latlon = None

        aggregator = Aggregator(
            build_sources(config),
            db,
            config.scoring,
            qth_latlon=qth_latlon,
            source_poll_interval_seconds=config.polling.source_interval_seconds,
            source_backoff_max_seconds=config.polling.source_backoff_max_seconds,
        )
    except TypeError as exc:
        # sources.*.options je volný dict (SourceConfig.options), na rozdíl
        # od ostatních polí ho load_config nekonvertuje ani nevaliduje --
        # build_sources() níže volá int(...)/float(...) přímo na hodnotách
        # z configu (např. sources.dx_cluster.options.port). Explicitně
        # prázdné "port:" v config.yaml se z YAML naparsuje jako None
        # (klíč existuje, hodnota None -- na rozdíl od úplně chybějícího
        # klíče), takže int(None) vyhazuje TypeError, ne ValueError. Bez
        # tohoto převodu by to cli.py::main() (odchytává jen
        # FileNotFoundError/ValueError) nezachytilo a spadlo by na
        # nezachyceném tracebacku stejně jako dřív ostatní neplatné hodnoty
        # v config.yaml -- stejná třída chyby jako
        # config.py::load_config, jen v jiném, pozdějším kroku startu
        # (viz DIAGNOSIS_P5.md).
        db.close()
        if rig is not None:
            rig.close()
        raise ValueError(
            f"Konfigurace živého zdroje (sources.*.options v config.yaml) obsahuje "
            f"prázdnou nebo neplatnou hodnotu: {exc}. Zkontroluj, že za každým ':' "
            "u číselných políček (např. port, timeout_s) je vyplněná hodnota, nebo "
            "řádek úplně smaž, ať se použije výchozí hodnota."
        ) from exc
    except Exception:
        # Selhani kdekoli mezi otevrenim DB a sestavenim aggregatoru (napr.
        # neplatna hodnota v sources.*.options, viz build_sources) nesmi
        # nechat otevrene sqlite spojeni/rig handle -- volajici (cli.main)
        # v tomto pripade koncí exit kodem 1 bez app_state, ktery by je jinak
        # v normalnim behu zaviral (viz DIAGNOSIS_P5.md).
        db.close()
        if rig is not None:
            rig.close()
        raise
    app_state = AppState(config, db, rig, aggregator)
    if config.rig.mode == "live":
        try:
            app_state.sync_rig_state_from_hardware()
        except Exception as exc:
            # rigctld nemusí v okamžiku startu ještě běžet (nebo je dočasně
            # nedostupný) -- start agenta na tom nesmí ztroskotat, GUI i
            # AUTO TUNE zvládají current_rig_state == None (viz web/server.py
            # rig_state_to_dict a PollingLoop, který má stejný fail-open
            # vzor pro selhání za běhu).
            logger.warning(
                "Počáteční synchronizace stavu riggu selhala, pokračuji bez ní: %s", exc
            )
    return app_state


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="station-agent", description="Station Agent DX asistent")
    parser.add_argument("--config", default="config.yaml", help="cesta ke config.yaml")
    parser.add_argument("--poll-interval", type=float, default=10.0, help="interval pollingu v sekundách")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    try:
        config = load_config(args.config)
        # build_app_state patří do stejného try -- i validní config.yaml
        # může mít hodnotu, která se ověří/zkonvertuje až tady (např.
        # sources.dx_cluster.options.port jako netextové číslo se na int()
        # převádí až v build_sources(), ne při load_config()). Bez toho by
        # main() spadl na nezachyceném ValueError stejně jako dřív na
        # chybějícím/neplatném config.yaml (viz DIAGNOSIS_P5.md).
        app_state = build_app_state(config)
    except FileNotFoundError as exc:
        logger.error(str(exc))
        return 1
    except ValueError as exc:
        logger.error("Konfigurace '%s' je neplatná: %s", args.config, exc)
        return 1

    try:
        # Počáteční naplnění kandidátů běží synchronně před spuštěním web
        # serveru (viz refresh_candidates -- volá aggregator.poll_once,
        # DB purge i build_candidates/scoring). Dřív běželo úplně mimo
        # try/except v main() -- selhání kdekoli v tomto řetězci (např.
        # neočekávaná hodnota z scoring/propagation) by spadlo na
        # nezachyceném tracebacku přesto, že load_config() i
        # build_app_state() proběhly v pořádku, stejná třída "Station
        # Agent nejde spustit" jako ostatní opravy v DIAGNOSIS_P5.md.
        app_state.refresh_candidates()
    except Exception as exc:
        logger.error(
            "Počáteční načtení kandidátů selhalo, Station Agent se nespustí: %s",
            exc,
        )
        app_state.aggregator.close()
        app_state.db.close()
        app_state.rig.close()
        return 1

    loop = PollingLoop(app_state, interval_seconds=args.poll_interval)
    loop.start()

    try:
        server = create_server(app_state)
    except OSError as exc:
        # web.port projde load_config()/WebConfig validaci rozsahu (viz
        # DIAGNOSIS_P5.md), ale platný port muze byt uz obsazeny jinym
        # procesem (typicky uz bezici instance Station Agenta, nebo jina
        # aplikace na stejnem portu) -- socket.bind() v create_server() na
        # tom vyhazuje OSError (na Windows konkretne PermissionError
        # WinError 10013 pri exkluzivnim obsazeni portu, na Linuxu typicky
        # "Address already in use"). Puvodne bezelo mimo jakykoli
        # try/except v main(), takze to spadlo na nezachycenem tracebacku
        # presto, ze cely config i build_app_state() probehly v poradku --
        # stejna trida "Station Agent nejde spustit" jako predchozich 9
        # oprav, jen odhalena az v tomto pozdejsim kroku startu. Zivě
        # reprodukovano pred opravou pomoci soketu s SO_EXCLUSIVEADDRUSE
        # drzicim stejny port.
        logger.error(
            "Nelze spustit webové GUI na %s:%d -- %s. Pravděpodobně už na "
            "tomto portu běží jiná instance Station Agenta nebo jiná "
            "aplikace. Ukonči ji, nebo změň web.port v config.yaml.",
            config.web.host,
            config.web.port,
            exc,
        )
        loop.stop()
        app_state.aggregator.close()
        app_state.db.close()
        app_state.rig.close()
        return 1
    logger.info(
        "Station Agent GUI na http://%s:%d (rig mode=%s)",
        config.web.host,
        config.web.port,
        config.rig.mode,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        loop.stop()
        server.shutdown()
        app_state.aggregator.close()
        app_state.db.close()
        app_state.rig.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
