"""Společné rozhraní pro všechny zdroje spotů."""

from __future__ import annotations

from abc import ABC, abstractmethod

from station_agent.models import Spot


class SpotSource(ABC):
    """Zdroj DX spotů. Každý adaptér má jednoznačné jméno (``name``), které
    se používá jako ``Spot.source`` a v seznamu "confirming_sources"."""

    name: str = "base"

    @abstractmethod
    def fetch(self) -> list[Spot]:
        """Vrátí aktuální dávku spotů. Musí být bezpečné volat opakovaně."""
        raise NotImplementedError


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
