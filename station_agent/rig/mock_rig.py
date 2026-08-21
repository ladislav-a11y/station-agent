"""In-memory mock rig -- výchozí backend, umožňuje testovat AUTO TUNE a GUI
bez jakéhokoli fyzicky připojeného rádia."""

from __future__ import annotations

from station_agent.rig.base import RigControl


class MockRig(RigControl):
    def __init__(self, freq_hz: int = 14_200_000, mode: str = "SSB"):
        self._freq_hz = freq_hz
        self._mode = mode
        self.set_frequency_calls: list[int] = []
        self.set_mode_calls: list[str] = []

    def get_frequency(self) -> int:
        return self._freq_hz

    def get_mode(self) -> str:
        return self._mode

    def set_frequency(self, freq_hz: int) -> None:
        self._freq_hz = freq_hz
        self.set_frequency_calls.append(freq_hz)

    def set_mode(self, mode: str) -> None:
        self._mode = mode
        self.set_mode_calls.append(mode)
