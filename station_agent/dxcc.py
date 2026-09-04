"""Callsign -> DXCC entita.

Obsahuje záměrně NEúplnou, ale rozšiřitelnou prefixovou tabulku (plný
oficiální DXCC seznam má cca 340 entit s desítkami výjimek a prefixových
přidělení). Souřadnice jsou orientační referenční bod entity (hlavní
město / geografický střed), ne přesná poloha konkrétní stanice -- pro
účely přibližného bearingu je to dostatečné.

Vyhledávání je "longest prefix match": ze všech klíčů v PREFIX_TABLE, které
jsou prefixem daného callsignu, vyhraje nejdelší shoda (např. "OK" i "OK1"
by mohly existovat, "OK1" vyhraje pro callsign "OK1ABC").
"""

from __future__ import annotations

from station_agent.models import DXCCEntity

# Neúplná, ale funkční sada běžných DXCC entit. Přidávání dalších je
# jednoduché -- viz AGENTS.md "Rozšiřování".
PREFIX_TABLE: dict[str, DXCCEntity] = {
    "OK": DXCCEntity("Czech Republic", "OK", "EU", 50.0755, 14.4378, 15),
    "OM": DXCCEntity("Slovak Republic", "OM", "EU", 48.1486, 17.1077, 15),
    "DL": DXCCEntity("Germany", "DL", "EU", 52.5200, 13.4050, 14),
    "G": DXCCEntity("England", "G", "EU", 51.5072, -0.1276, 14),
    "F": DXCCEntity("France", "F", "EU", 48.8566, 2.3522, 14),
    "I": DXCCEntity("Italy", "I", "EU", 41.9028, 12.4964, 15),
    "EA": DXCCEntity("Spain", "EA", "EU", 40.4168, -3.7038, 14),
    "SP": DXCCEntity("Poland", "SP", "EU", 52.2297, 21.0122, 15),
    "SM": DXCCEntity("Sweden", "SM", "EU", 59.3293, 18.0686, 14),
    "LA": DXCCEntity("Norway", "LA", "EU", 59.9139, 10.7522, 14),
    "OH": DXCCEntity("Finland", "OH", "EU", 60.1699, 24.9384, 15),
    "PA": DXCCEntity("Netherlands", "PA", "EU", 52.3676, 4.9041, 14),
    "ON": DXCCEntity("Belgium", "ON", "EU", 50.8503, 4.3517, 14),
    "HB9": DXCCEntity("Switzerland", "HB9", "EU", 46.9480, 7.4474, 14),
    "OE": DXCCEntity("Austria", "OE", "EU", 48.2082, 16.3738, 15),
    "9A": DXCCEntity("Croatia", "9A", "EU", 45.8150, 15.9819, 15),
    "S5": DXCCEntity("Slovenia", "S5", "EU", 46.0569, 14.5058, 15),
    "YO": DXCCEntity("Romania", "YO", "EU", 44.4268, 26.1025, 20),
    "LZ": DXCCEntity("Bulgaria", "LZ", "EU", 42.6977, 23.3219, 20),
    "UR": DXCCEntity("Ukraine", "UR", "EU", 50.4501, 30.5234, 16),
    "YL": DXCCEntity("Latvia", "YL", "EU", 56.9496, 24.1052, 15),
    "LY": DXCCEntity("Lithuania", "LY", "EU", 54.6872, 25.2797, 15),
    "ES": DXCCEntity("Estonia", "ES", "EU", 59.4370, 24.7536, 15),
    "HA": DXCCEntity("Hungary", "HA", "EU", 47.4979, 19.0402, 15),
    "9H": DXCCEntity("Malta", "9H", "EU", 35.8989, 14.5146, 15),
    "TA": DXCCEntity("Turkey", "TA", "EU", 39.9334, 32.8597, 20),
    "4X": DXCCEntity("Israel", "4X", "AS", 31.7683, 35.2137, 20),
    "UA": DXCCEntity("European Russia", "UA", "EU", 55.7558, 37.6173, 16),
    "W": DXCCEntity("United States", "W", "NA", 38.9072, -77.0369, 5),
    "K": DXCCEntity("United States", "K", "NA", 38.9072, -77.0369, 5),
    "N": DXCCEntity("United States", "N", "NA", 38.9072, -77.0369, 5),
    "AA": DXCCEntity("United States", "AA", "NA", 38.9072, -77.0369, 5),
    "VE": DXCCEntity("Canada", "VE", "NA", 45.4215, -75.6972, 4),
    "VA": DXCCEntity("Canada", "VA", "NA", 45.4215, -75.6972, 4),
    "XE": DXCCEntity("Mexico", "XE", "NA", 19.4326, -99.1332, 6),
    "PY": DXCCEntity("Brazil", "PY", "SA", -15.7939, -47.8828, 11),
    "LU": DXCCEntity("Argentina", "LU", "SA", -34.6037, -58.3816, 13),
    "CE": DXCCEntity("Chile", "CE", "SA", -33.4489, -70.6693, 12),
    "HK": DXCCEntity("Colombia", "HK", "SA", 4.7110, -74.0721, 9),
    "JA": DXCCEntity("Japan", "JA", "AS", 35.6762, 139.6503, 25),
    "BY": DXCCEntity("China", "BY", "AS", 39.9042, 116.4074, 24),
    "HL": DXCCEntity("Republic of Korea", "HL", "AS", 37.5665, 126.9780, 25),
    "VU": DXCCEntity("India", "VU", "AS", 28.6139, 77.2090, 22),
    "VK": DXCCEntity("Australia", "VK", "OC", -35.2809, 149.1300, 30),
    "ZL": DXCCEntity("New Zealand", "ZL", "OC", -41.2865, 174.7762, 32),
    "ZS": DXCCEntity("South Africa", "ZS", "AF", -25.7479, 28.2293, 38),
    "5N": DXCCEntity("Nigeria", "5N", "AF", 9.0765, 7.3986, 35),
    "SV": DXCCEntity("Greece", "SV", "EU", 37.9838, 23.7275, 20),
    "CT": DXCCEntity("Portugal", "CT", "EU", 38.7223, -9.1393, 14),
    "OZ": DXCCEntity("Denmark", "OZ", "EU", 55.6761, 12.5683, 14),
    "TF": DXCCEntity("Iceland", "TF", "EU", 64.1466, -21.9426, 40),
    "EI": DXCCEntity("Ireland", "EI", "EU", 53.3498, -6.2603, 14),
    # Samostatné DXCC entity uvnitř širších prefixových bloků (USA) --
    # musí být delší než "K"/"W"/"N", aby vyhrály v longest-prefix-match.
    "KH6": DXCCEntity("Hawaii", "KH6", "OC", 21.3069, -157.8583, 31),
    "KL7": DXCCEntity("Alaska", "KL7", "NA", 61.2181, -149.9003, 1),
    "KP4": DXCCEntity("Puerto Rico", "KP4", "NA", 18.4655, -66.1057, 8),
    # Karibik a Střední/Jižní Amerika.
    "HP": DXCCEntity("Panama", "HP", "NA", 8.9824, -79.5199, 7),
    "TI": DXCCEntity("Costa Rica", "TI", "NA", 9.9281, -84.0907, 7),
    "CO": DXCCEntity("Cuba", "CO", "NA", 23.1136, -82.3666, 8),
    "HI": DXCCEntity("Dominican Republic", "HI", "NA", 18.4861, -69.9312, 8),
    "6Y": DXCCEntity("Jamaica", "6Y", "NA", 18.1096, -77.2975, 8),
    "9Y": DXCCEntity("Trinidad & Tobago", "9Y", "SA", 10.6596, -61.5019, 9),
    "PZ": DXCCEntity("Suriname", "PZ", "SA", 5.8520, -55.2038, 9),
    "YV": DXCCEntity("Venezuela", "YV", "SA", 10.4806, -66.9036, 9),
    "HC": DXCCEntity("Ecuador", "HC", "SA", -0.1807, -78.4678, 10),
    "OA": DXCCEntity("Peru", "OA", "SA", -12.0464, -77.0428, 10),
    "CP": DXCCEntity("Bolivia", "CP", "SA", -16.4897, -68.1193, 10),
    "ZP": DXCCEntity("Paraguay", "ZP", "SA", -25.2637, -57.5759, 11),
    "CX": DXCCEntity("Uruguay", "CX", "SA", -34.9011, -56.1645, 13),
    # Blízký východ a severní Afrika.
    "9K": DXCCEntity("Kuwait", "9K", "AS", 29.3759, 47.9774, 21),
    "HZ": DXCCEntity("Saudi Arabia", "HZ", "AS", 24.7136, 46.6753, 21),
    "A4": DXCCEntity("Oman", "A4", "AS", 23.5859, 58.4059, 21),
    "5B": DXCCEntity("Cyprus", "5B", "AS", 35.1856, 33.3823, 20),
    "OD": DXCCEntity("Lebanon", "OD", "AS", 33.8938, 35.5018, 20),
    "JY": DXCCEntity("Jordan", "JY", "AS", 31.9454, 35.9284, 20),
    "EP": DXCCEntity("Iran", "EP", "AS", 35.6892, 51.3890, 21),
    "7X": DXCCEntity("Algeria", "7X", "AF", 36.7538, 3.0588, 33),
    "CN": DXCCEntity("Morocco", "CN", "AF", 33.9716, -6.8498, 33),
    "SU": DXCCEntity("Egypt", "SU", "AF", 30.0444, 31.2357, 34),
    # Subsaharská Afrika.
    "9G": DXCCEntity("Ghana", "9G", "AF", 5.6037, -0.1870, 35),
    "ET": DXCCEntity("Ethiopia", "ET", "AF", 9.0300, 38.7400, 37),
    "5H": DXCCEntity("Tanzania", "5H", "AF", -6.1630, 35.7516, 37),
    "5X": DXCCEntity("Uganda", "5X", "AF", 0.3476, 32.5825, 37),
    "V5": DXCCEntity("Namibia", "V5", "AF", -22.5609, 17.0658, 38),
    "Z2": DXCCEntity("Zimbabwe", "Z2", "AF", -17.8252, 31.0335, 38),
    "D2": DXCCEntity("Angola", "D2", "AF", -8.8390, 13.2894, 36),
    "6W": DXCCEntity("Senegal", "6W", "AF", 14.6928, -17.4467, 35),
    # Jihovýchodní a východní Asie.
    "9M2": DXCCEntity("West Malaysia", "9M2", "AS", 3.1390, 101.6869, 28),
    "9V": DXCCEntity("Singapore", "9V", "AS", 1.3521, 103.8198, 28),
    "HS": DXCCEntity("Thailand", "HS", "AS", 13.7563, 100.5018, 26),
    "YB": DXCCEntity("Indonesia", "YB", "OC", -6.2088, 106.8456, 28),
    "DU": DXCCEntity("Philippines", "DU", "OC", 14.5995, 120.9842, 27),
    "4S": DXCCEntity("Sri Lanka", "4S", "AS", 6.9271, 79.8612, 22),
    "BV": DXCCEntity("Taiwan", "BV", "AS", 25.0330, 121.5654, 24),
    "VR": DXCCEntity("Hong Kong", "VR", "AS", 22.3193, 114.1694, 24),
    "UN": DXCCEntity("Kazakhstan", "UN", "AS", 51.1694, 71.4491, 17),
}


def _base_call(callsign: str) -> str:
    """Vybere ze složeného callsignu (OK1ABC/P, W1AW/OK1) základní část.

    Heuristika: část obsahující číslici je "plný" callsign, krátké přípony
    jako /P, /MM, /QRP číslici typicky nemají. Není to dokonalé (skutečné
    DXCC přiřazení u compound callsignů má výjimky), ale pro účel
    přibližného zobrazení entity je to dostatečné.
    """
    call = callsign.strip().upper()
    if "/" not in call:
        return call
    parts = [p for p in call.split("/") if p]
    with_digit = [p for p in parts if any(c.isdigit() for c in p)]
    candidates = with_digit or parts
    return max(candidates, key=len)


def _iter_prefix_candidates(callsign: str) -> list[str]:
    """Vygeneruje všechny prefixy callsignu od nejdelšího po nejkratší."""
    call = _base_call(callsign)
    return [call[:i] for i in range(len(call), 0, -1)]


def callsign_to_dxcc(callsign: str) -> DXCCEntity | None:
    """Vrátí DXCCEntity pro callsign, nebo None pokud prefix není v tabulce.

    Nikdy nevyhazuje výjimku na neznámý/neplatný callsign -- kandidát se
    v GUI prostě zobrazí bez DXCC informace.
    """
    if not callsign:
        return None
    for prefix in _iter_prefix_candidates(callsign):
        entity = PREFIX_TABLE.get(prefix)
        if entity is not None:
            return entity
    return None
