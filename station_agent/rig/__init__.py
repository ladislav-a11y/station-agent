"""Ovládání riggu (IC-7300) přes Hamlib/rigctld -- mock nebo live.

BEZPEČNOST: rozhraní RigControl (viz base.py) záměrně nemá a nikdy nesmí
mít žádnou metodu pro zapnutí vysílání/klíčování transmitteru. Viz AGENTS.md pravidlo 1.
"""

from __future__ import annotations

from station_agent.config import RigConfig
from station_agent.rig.base import RigControl
from station_agent.rig.mock_rig import MockRig
from station_agent.rig.rigctld import RigctldClient


def create_rig_control(config: RigConfig) -> RigControl:
    """Vytvoří RigControl podle configu. Výchozí je vždy mock (viz config.py
    RigConfig.mode default "mock"); "live" je explicitní volba uživatele."""
    if config.mode == "mock":
        return MockRig()
    if config.mode == "live":
        return RigctldClient(host=config.rigctld_host, port=config.rigctld_port)
    raise ValueError(f"Neznámý rig.mode: {config.mode!r}")


__all__ = ["RigControl", "MockRig", "RigctldClient", "create_rig_control"]
