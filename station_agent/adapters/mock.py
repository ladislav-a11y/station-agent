"""Mock zdroj spotů -- umožňuje testovat GUI, scoring a AUTO TUNE logiku
zcela bez internetu a bez připojeného rádia.

Na rozdíl od DX Cluster/RBN/PSKReporter adaptérů (viz dx_cluster.py,
rbn.py, pskreporter.py) tento adaptér nic nepředstírá -- je to explicitně
označený a dokumentovaný testovací/demo zdroj dat, defaultně zapnutý
(``sources.mock.enabled: true``), zatímco živé zdroje jsou defaultně
vypnuté.
"""

from __future__ import annotations

import time

from station_agent.adapters.base import SpotSource
from station_agent.models import Spot

# Statická sada ukázkových spotů pokrývající různá pásma/módy/kontinenty,
# aby šlo smysluplně otestovat filtrování, scoring i AUTO TUNE bez sítě.
# `age_s` = jak "staré" má být demo spot vzhledem k okamžiku volání fetch().
_SAMPLE_TEMPLATE: list[dict] = [
    dict(callsign="JA1XYZ", freq_hz=14_195_000, mode="SSB", age_s=30, snr_db=15, spotter="OK1KT"),
    dict(callsign="VK3ABC", freq_hz=21_074_000, mode="FT8", age_s=45, snr_db=-8, spotter="DL2ABC"),
    dict(callsign="ZS6DEF", freq_hz=7_030_000, mode="CW", age_s=90, snr_db=20, spotter="G4XYZ"),
    dict(callsign="PY2GHI", freq_hz=28_450_000, mode="SSB", age_s=15, snr_db=9, spotter="EA1ABC"),
    dict(callsign="W1AW", freq_hz=14_074_000, mode="FT8", age_s=600, snr_db=3, spotter="OK1ABC"),
    dict(callsign="LU7JKL", freq_hz=18_100_000, mode="CW", age_s=120, snr_db=None, spotter="F5XYZ"),
    dict(callsign="9M6MNO", freq_hz=24_910_000, mode="RTTY", age_s=200, snr_db=None, spotter="I2ABC"),
    dict(callsign="VU2PQR", freq_hz=10_136_000, mode="PSK31", age_s=300, snr_db=None, spotter="SP5XYZ"),
]


def sample_spots(now: float | None = None, source: str = "mock") -> list[Spot]:
    """Vrátí deterministickou sadu demo spotů relativně k `now`."""
    now = time.time() if now is None else now
    return [
        Spot(
            callsign=item["callsign"],
            freq_hz=item["freq_hz"],
            mode=item["mode"],
            timestamp=now - item["age_s"],
            source=source,
            snr_db=item["snr_db"],
            spotter=item["spotter"],
            comment="mock spot",
        )
        for item in _SAMPLE_TEMPLATE
    ]


class MockAdapter(SpotSource):
    """Plně funkční offline zdroj spotů pro vývoj/testy/demo."""

    name = "mock"

    def __init__(self, spots: list[Spot] | None = None):
        self._fixed_spots = spots

    def fetch(self) -> list[Spot]:
        if self._fixed_spots is not None:
            return list(self._fixed_spots)
        return sample_spots(source=self.name)
