"""Entry point: `python -m station_agent` / `station-agent`."""

from __future__ import annotations

import argparse
import logging
import sys

from station_agent.adapters.dx_cluster import DXClusterAdapter
from station_agent.adapters.mock import MockAdapter
from station_agent.adapters.pskreporter import PSKReporterAdapter
from station_agent.adapters.rbn import RBNAdapter
from station_agent.aggregator import Aggregator
from station_agent.app_state import AppState, PollingLoop
from station_agent.config import AppConfig, load_config
from station_agent.db import Database
from station_agent.rig import create_rig_control
from station_agent.web.server import create_server

logger = logging.getLogger(__name__)


def build_sources(config: AppConfig) -> list:
    sources = []
    if config.sources.get("mock", None) is None or config.sources["mock"].enabled:
        sources.append(MockAdapter())
    dxc = config.sources.get("dx_cluster")
    if dxc and dxc.enabled:
        sources.append(
            DXClusterAdapter(host=dxc.options.get("host", ""), port=int(dxc.options.get("port", 7300)))
        )
    rbn = config.sources.get("rbn")
    if rbn and rbn.enabled:
        sources.append(RBNAdapter(host=rbn.options.get("host", ""), port=int(rbn.options.get("port", 7000))))
    pskr = config.sources.get("pskreporter")
    if pskr and pskr.enabled:
        options = dict(pskr.options)
        query_url = options.pop("query_url", None) or "https://retrieve.pskreporter.info/query"
        timeout_s = float(options.pop("timeout_s", 15.0))
        sources.append(PSKReporterAdapter(query_url=query_url, params=options, timeout_s=timeout_s))
    return sources


def build_app_state(config: AppConfig) -> AppState:
    db = Database(config.database.path)
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
    app_state = AppState(config, db, rig, aggregator)
    if config.rig.mode == "live":
        app_state.sync_rig_state_from_hardware()
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

    config = load_config(args.config)
    app_state = build_app_state(config)
    app_state.refresh_candidates()

    loop = PollingLoop(app_state, interval_seconds=args.poll_interval)
    loop.start()

    server = create_server(app_state)
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
        app_state.db.close()
        app_state.rig.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
