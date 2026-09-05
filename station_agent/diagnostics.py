"""Explicitní diagnostika lokální databáze a síťových endpointů.

Diagnostika nic nezapisuje do provozních tabulek a nespouští běžný polling.
U UDP endpointu lze ověřit jen překlad adresy a lokální síťovou cestu;
protokol neposkytuje potvrzení, že cílová aplikace paket přijala.
"""

from __future__ import annotations

import socket
import sqlite3
from dataclasses import dataclass

from station_agent.config import AppConfig


@dataclass(frozen=True)
class DiagnosticResult:
    component: str
    ok: bool
    detail: str
    verified: bool = True


def check_database(path: str) -> DiagnosticResult:
    """Ověří otevření a integritu SQLite bez změny aplikačních dat."""
    connection: sqlite3.Connection | None = None
    try:
        uri = f"file:{path}?mode=rw"
        connection = sqlite3.connect(uri, uri=True, timeout=2.0)
        row = connection.execute("PRAGMA quick_check").fetchone()
        if row != ("ok",):
            return DiagnosticResult("database", False, f"SQLite quick_check: {row!r}")
    except (OSError, sqlite3.Error) as exc:
        return DiagnosticResult("database", False, f"SQLite nelze ověřit: {exc}")
    finally:
        if connection is not None:
            connection.close()
    return DiagnosticResult("database", True, f"SQLite je dostupná a integrita je v pořádku: {path}")


def check_tcp_endpoint(component: str, host: str, port: int, timeout: float = 5.0) -> DiagnosticResult:
    """Ověří navázání TCP spojení a ihned je korektně zavře."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            pass
    except OSError as exc:
        return DiagnosticResult(component, False, f"TCP {host}:{port} není dostupné: {exc}")
    return DiagnosticResult(component, True, f"TCP {host}:{port} přijalo spojení")


def check_log4om_endpoint(host: str, port: int) -> DiagnosticResult:
    """Ověří adresaci UDP endpointu bez odeslání prefill dat.

    UDP nemá handshake, proto úspěch nesmí být vydáván za potvrzení příjmu
    běžící aplikací. Skutečné předvyplnění zůstává pouze ruční akcí operátora.
    """
    try:
        addresses = socket.getaddrinfo(host, port, type=socket.SOCK_DGRAM)
        if not addresses:
            raise OSError("překlad adresy nevrátil žádný výsledek")
        family, socktype, protocol, _, address = addresses[0]
        with socket.socket(family, socktype, protocol) as sock:
            sock.connect(address)
            local_address = sock.getsockname()
    except OSError as exc:
        return DiagnosticResult("log4om", False, f"UDP endpoint {host}:{port} nelze připravit: {exc}")
    return DiagnosticResult(
        "log4om",
        True,
        f"UDP cesta {local_address[0]} -> {host}:{port} je připravená; příjem aplikací nelze přes UDP potvrdit",
        verified=False,
    )


def run_live_diagnostics(config: AppConfig, timeout: float = 5.0) -> list[DiagnosticResult]:
    """Vrátí výsledky pro DB, Log4OM2 a všechny povolené Cluster zdroje."""
    results = [check_database(config.database.path)]
    if config.log4om.enabled:
        results.append(check_log4om_endpoint(config.log4om.host, config.log4om.port))
    else:
        results.append(DiagnosticResult("log4om", True, "integrace je v configu vypnutá", verified=False))

    enabled_clusters = 0
    for name, source in config.sources.items():
        if not (name == "dx_cluster" or name.startswith("dx_cluster_")) or not source.enabled:
            continue
        enabled_clusters += 1
        from station_agent.adapters.dx_cluster import DXClusterAdapter, RECOMMENDED_PROVIDERS

        default_host, default_port = RECOMMENDED_PROVIDERS.get(
            name, (DXClusterAdapter.DEFAULT_HOST, DXClusterAdapter.DEFAULT_PORT)
        )
        host = str(source.options.get("host", default_host))
        port = int(source.options.get("port", default_port))
        results.append(check_tcp_endpoint(name, host, port, timeout=timeout))
    if not enabled_clusters:
        results.append(DiagnosticResult("dx_cluster", True, "žádný Cluster zdroj není povolený", verified=False))
    return results
