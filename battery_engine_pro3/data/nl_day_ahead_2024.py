# battery_engine_pro3/data/nl_day_ahead_2024.py
"""
Representatieve NL day-ahead prijzen voor 2024 in euro/MWh.
Gebaseerd op ENTSO-E maandgemiddelden en typische dagpatronen
voor de Nederlandse energiemarkt.
Gegenereerd als 8760 uurwaarden (geen schrikkeljaar).
"""

from datetime import datetime, timedelta


MONTH_AVG_EUR_MWH = [
    65,  # jan
    55,  # feb
    45,  # mrt
    35,  # apr
    40,  # mei
    38,  # jun
    42,  # jul
    48,  # aug
    52,  # sep
    58,  # okt
    62,  # nov
    68,  # dec
]

# Relatief dagprofiel (24 gewichten)
# Typisch NL patroon: laag in nacht, ochtend- en avondpiek,
# zomermiddag laag door veel PV op het net
HOUR_PROFILE_RAW = [
    0.72, 0.68, 0.65, 0.63, 0.64, 0.70,  # 00-05 nacht
    0.82, 0.95, 1.05, 1.02, 0.98, 0.95,  # 06-11 ochtend
    0.90, 0.88, 0.87, 0.90, 1.00, 1.15,  # 12-17 middag
    1.35, 1.45, 1.40, 1.25, 1.05, 0.85   # 18-23 avond
]

# Normaliseer zodat gemiddelde van profiel = 1.0
_avg_h = sum(HOUR_PROFILE_RAW) / 24
HOUR_PROFILE = [h / _avg_h for h in HOUR_PROFILE_RAW]


def generate_nl_2024_prices() -> list[float]:
    """
    Genereert representatieve NL day-ahead prijzen voor 2024
    in euro/MWh op uurbasis (8760 waarden).

    Modifiers bovenop het basispatroon:
    - Weekend (za/zo): x 0.85 (lagere industrievraag)
    - Zomermiddag jun/jul/aug uur 10-15: x 0.65
      (veel PV op net drukt prijzen, incl. negatieve uren)
    - Winterochtend dec/jan/feb uur 7-9: x 1.15
      (hoge verwarmingsvraag bij koude ochtenden)
    """
    start = datetime(2024, 1, 1)
    prices = []

    for i in range(8760):
        dt = start + timedelta(hours=i)
        month_idx = dt.month - 1
        hour = dt.hour
        weekday = dt.weekday()  # 0=ma, 6=zo

        base = MONTH_AVG_EUR_MWH[month_idx]
        price = base * HOUR_PROFILE[hour]

        # Weekend: lagere prijzen door minder industrie
        if weekday >= 5:
            price *= 0.85

        # Zomermiddag: PV-overschot drukt prijzen
        if dt.month in [6, 7, 8] and 10 <= hour <= 15:
            price *= 0.65

        # Winterochtend: hoge verwarmingsvraag
        if dt.month in [12, 1, 2] and 7 <= hour <= 9:
            price *= 1.15

        prices.append(round(price, 4))

    return prices


NL_2024_PRICES_EUR_MWH = generate_nl_2024_prices()
