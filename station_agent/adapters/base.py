"""Společné rozhraní pro všechny zdroje spotů."""

from __future__ import annotations

from abc import ABC, abstractmethod

from station_agent.models import Spot


class SpotSource(ABC):
    """Zdroj DX spotů. Každý adaptér má jednoznačné jméno (``name``), které
    se používá jako ``Spot.source`` a v seznamu "confirming_sources"."""

    name: str = "base"

    #: Minimální doba (s) mezi dvěma reálnými dotazy na tento konkrétní zdroj,
    #: kterou ``Aggregator`` vynutí bez ohledu na (nižší) ``polling.
    #: source_interval_seconds`` z configu -- viz ``PSKReporterAdapter``,
    #: jehož veřejné API vrací HTTP 429 i při obecném 60s minimu. ``0``
    #: znamená "žádné dodatečné omezení nad rámec configu".
    min_poll_interval_seconds: float = 0.0

    @abstractmethod
    def fetch(self) -> list[Spot]:
        """Vrátí aktuální dávku spotů. Musí být bezpečné volat opakovaně."""
        raise NotImplementedError


class RateLimitedError(Exception):
    """Zdroj odpověděl HTTP 429 (Too Many Requests).

    Adaptéry, které mluví po HTTP (viz ``pskreporter.py``), vyhazují tuto
    výjimku místo obecné ``HTTPError``, aby ji polling vrstva
    (``adapters/polling.py``) mohla odlišit od ostatních chyb a reagovat
    exponenciálním backoffem -- případně respektovat ``Retry-After``
    hlavičku, pokud ji server poslal (``retry_after_seconds``).
    """

    def __init__(self, message: str = "HTTP 429 Too Many Requests", retry_after_seconds: float | None = None):
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds


class SourceNotReadyError(Exception):
    """Živý zdroj (viz ``adapters/telnet_source.py``) je implementovaný a
    aktivně se pokouší o spojení, ale ještě nikdy se mu nepodařilo navázat
    spojení a naparsovat aspoň jeden reálný spot.

    Na rozdíl od ``NotImplementedError`` (viz ``PendingSpotSource`` níže),
    které znamená "tento adaptér vůbec nemá živou implementaci", tato
    výjimka znamená "implementace je živá, jen zatím čekáme na první
    úspěšné spojení/data" -- ``PolledSource`` (``adapters/polling.py``) ji
    mapuje na stejný GUI stav ``pending``, dokud nedorazí první reálná
    data, po kterých už zdroj hlásí ``ok``/``error`` podle aktuálního
    stavu spojení.
    """


class PendingSpotSource(SpotSource):
    """Základ pro adaptéry na živé externí služby, které zatím nebyly
    ověřeny proti reálnému serveru (viz README "Stav externích zdrojů").

    ``fetch()`` úmyslně vyhazuje NotImplementedError -- nikdy nevrací
    vymyšlená data tvářící se jako reálná odpověď externí služby. Parsovací
    funkce v podtřídách (např. ``parse_spot_line``) jsou naopak plně
    implementované a testované na fixture datech.
    """

    pending_reason: str = "Live připojení zatím nebylo ověřeno proti reálné službě."

    def fetch(self) -> list[Spot]:
        raise NotImplementedError(
            f"{self.name}: adaptér je PENDING -- {self.pending_reason} "
            "Viz README.md 'Stav externích zdrojů'."
        )
