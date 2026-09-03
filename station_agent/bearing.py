"""Maidenhead locator <-> lat/lon a great-circle bearing/vzdálenost.

Používá se výhradně pro VÝPOČET a ZOBRAZENÍ směru k DX stanici. Projekt
záměrně neobsahuje žádný modul pro ovládání anténního rotátoru -- viz
ARCHITECTURE.md.
"""

from __future__ import annotations

import math

EARTH_RADIUS_KM = 6371.0088


def maidenhead_to_latlon(locator: str) -> tuple[float, float]:
    """Převede Maidenhead locator (4 nebo 6 znaků) na (lat, lon) ve stupních.

    Vrací souřadnice středu příslušného pole/čtverce/podčtverce.
    """
    loc = locator.strip().upper()
    if len(loc) not in (4, 6, 8):
        raise ValueError(f"Neplatná délka Maidenhead locatoru: {locator!r}")
    if not (loc[0].isalpha() and loc[1].isalpha() and loc[2].isdigit() and loc[3].isdigit()):
        raise ValueError(f"Neplatný formát Maidenhead locatoru: {locator!r}")

    lon = (ord(loc[0]) - ord("A")) * 20.0 - 180.0
    lat = (ord(loc[1]) - ord("A")) * 10.0 - 90.0
    lon += int(loc[2]) * 2.0
    lat += int(loc[3]) * 1.0

    if len(loc) >= 6:
        if not (loc[4].isalpha() and loc[5].isalpha()):
            raise ValueError(f"Neplatný formát Maidenhead locatoru: {locator!r}")
        lon += (ord(loc[4]) - ord("A")) * (2.0 / 24.0)
        lat += (ord(loc[5]) - ord("A")) * (1.0 / 24.0)
        lon += (2.0 / 24.0) / 2.0
        lat += (1.0 / 24.0) / 2.0
    else:
        lon += 1.0
        lat += 0.5

    return lat, lon


def haversine_distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(min(1.0, math.sqrt(a)))


def initial_bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Počáteční (great-circle) azimut z bodu 1 na bod 2, 0-360 stupňů."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dlambda = math.radians(lon2 - lon1)
    x = math.sin(dlambda) * math.cos(phi2)
    y = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(dlambda)
    bearing = math.degrees(math.atan2(x, y))
    return (bearing + 360.0) % 360.0


def bearing_and_distance(
    qth_lat: float, qth_lon: float, target_lat: float, target_lon: float
) -> tuple[float, float]:
    """Vrátí (bearing_deg, distance_km) z QTH na cíl."""
    bearing = initial_bearing_deg(qth_lat, qth_lon, target_lat, target_lon)
    distance = haversine_distance_km(qth_lat, qth_lon, target_lat, target_lon)
    return bearing, distance
