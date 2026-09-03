"""Maidenhead locator <-> lat/lon a great-circle bearing/vzdálenost.

Používá se výhradně pro VÝPOČET a ZOBRAZENÍ směru k DX stanici. Projekt
záměrně neobsahuje žádný modul pro ovládání anténního rotátoru -- viz
ARCHITECTURE.md.
"""

from __future__ import annotations

import math

EARTH_RADIUS_KM = 6371.0088


def maidenhead_to_latlon(locator: str) -> tuple[float, float]:
    """Převede Maidenhead locator (4, 6, 8 nebo 10 znaků) na (lat, lon) ve stupních.

    Podporuje i "extended" precision (8/10 znaků), kterou reálně vrací
    PSKReporter (senderLocator) pro část stanic -- viz LIVE_EVIDENCE.md
    ("live test v PowerShell"): každá další dvojice znaků za základními 4
    dál zpřesňuje pozici, typicky střídavě číslicemi (extended square,
    0-9) a písmeny (extended subsquare, A-X), stejně jako subsquare
    (5.-6. znak) zpřesňuje square. Typ páru (písmena vs. číslice) se ale
    určuje podle skutečného obsahu dvojice, ne podle pevné pozice -- někteří
    poskytovatelé vrací i na pozici extended square písmena místo číslic
    (reálný kandidát 'KN10LNPN'), přesto jde o formálně platné zpřesnění.
    Bez podpory těchto delších locatorů by se u ~10 % reálných PSKReporter
    kandidátů zahazoval platný bearing jako "neplatná délka"/"neplatný
    formát", ačkoliv jde o formálně správný, jen přesnější locator.

    Vrací souřadnice středu příslušného pole/čtverce/podčtverce.
    """
    loc = locator.strip().upper()
    if len(loc) not in (4, 6, 8, 10):
        raise ValueError(f"Neplatná délka Maidenhead locatoru: {locator!r}")
    if not (loc[0].isalpha() and loc[1].isalpha() and loc[2].isdigit() and loc[3].isdigit()):
        raise ValueError(f"Neplatný formát Maidenhead locatoru: {locator!r}")

    lon = (ord(loc[0]) - ord("A")) * 20.0 - 180.0 + int(loc[2]) * 2.0
    lat = (ord(loc[1]) - ord("A")) * 10.0 - 90.0 + int(loc[3]) * 1.0
    lon_size = 2.0
    lat_size = 1.0

    # Standardně 5.-6. znak (subsquare) jsou písmena, 7.-8. číslice (extended
    # square), 9.-10. zase písmena atd. Někteří poskytovatelé ale i pro
    # 7.-8. znak vrací písmena místo číslic (reálný kandidát 'KN10LNPN' z
    # PSKReporteru), přesto jde o formálně platné zpřesnění polohy -- proto
    # se typ páru (písmena vs. číslice) určuje podle skutečného obsahu
    # dvojice, ne podle pevné pozice. Pár musí být homogenní (obě písmena,
    # nebo obě číslice); smíšený pár zůstává neplatný.
    pos = 4
    while pos < len(loc):
        a, b = loc[pos], loc[pos + 1]
        if a.isalpha() and b.isalpha():
            divisions = 24.0
            idx_lon, idx_lat = ord(a) - ord("A"), ord(b) - ord("A")
        elif a.isdigit() and b.isdigit():
            divisions = 10.0
            idx_lon, idx_lat = int(a), int(b)
        else:
            raise ValueError(f"Neplatný formát Maidenhead locatoru: {locator!r}")
        lon_size /= divisions
        lat_size /= divisions
        lon += idx_lon * lon_size
        lat += idx_lat * lat_size
        pos += 2

    lon += lon_size / 2.0
    lat += lat_size / 2.0

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
