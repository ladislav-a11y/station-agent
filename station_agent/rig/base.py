"""Rozhraní pro ovládání riggu.

Uzavřená sada metod: čtení a nastavení frekvence/módu. Žádná metoda pro
vysílání zde není a nikdy nesmí být přidána (viz AGENTS.md pravidlo 1) --
ani obecná "pošli libovolný příkaz" metoda, protože by šla ke stejnému
účelu zneužít.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod

from station_agent.models import RigState


class RigControl(ABC):
    @abstractmethod
    def get_frequency(self) -> int:
        """Aktuální frekvence v Hz."""
        raise NotImplementedError

    @abstractmethod
    def get_mode(self) -> str:
        """Aktuální mód (normalizovaný, viz station_agent.modes)."""
        raise NotImplementedError

    @abstractmethod
    def set_frequency(self, freq_hz: int) -> None:
        raise NotImplementedError

    @abstractmethod
    def set_mode(self, mode: str) -> None:
        raise NotImplementedError

    def get_status(self) -> RigState:
        return RigState(freq_hz=self.get_frequency(), mode=self.get_mode(), tuned_at=time.time())

    def close(self) -> None:
        pass
