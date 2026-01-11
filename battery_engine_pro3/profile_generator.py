# battery_engine_pro3/profile_generator.py

from __future__ import annotations
from dataclasses import dataclass
from typing import List, Tuple, Dict
from datetime import datetime, timedelta
import math


# ------------------------------------------------------------
# PROFIELEN (24u verdeling) — simpel maar verdedigbaar
# Percentages moeten optellen naar 1.0
# ------------------------------------------------------------

HOUSEHOLD_PROFILES: Dict[str, List[float]] = {
    # relatief vlak + avondpiek
    "alleenstaand_werkend": [
        0.020, 0.015, 0.012, 0.012, 0.014, 0.020,
        0.030, 0.035, 0.030, 0.025, 0.025, 0.030,
        0.035, 0.035, 0.030, 0.030, 0.035, 0.050,
        0.070, 0.080, 0.075, 0.055, 0.035, 0.025
    ],
    # ochtend + avond meer
    "gezin_kinderen": [
        0.020, 0.015, 0.012, 0.012, 0.015, 0.030,
        0.050, 0.045, 0.035, 0.030, 0.028, 0.030,
        0.032, 0.032, 0.030, 0.032, 0.040, 0.060,
        0.075, 0.080, 0.070, 0.050, 0.032, 0.022
    ],
    # meer overdag
    "thuiswerker": [
        0.022, 0.016, 0.013, 0.013, 0.016, 0.028,
        0.040, 0.040, 0.038, 0.038, 0.040, 0.045,
        0.045, 0.045, 0.040, 0.038, 0.040, 0.050,
        0.060, 0.060, 0.055, 0.040, 0.030, 0.024
    ],
}

# simpele maandfactoren (winter hoger, zomer lager) — som ≈ 12
MONTH_LOAD_FACTORS = [1.10, 1.08, 1.02, 0.98, 0.95, 0.92, 0.90, 0.90, 0.94, 1.00, 1.05, 1.06]

# PV maandfactoren (zomer hoger) — som ≈ 12
MONTH_PV_FACTORS = [0.35, 0.45, 0.75, 1.05, 1.25, 1.35, 1.35, 1.20, 0.95, 0.65, 0.40, 0.30]


def _normalize(vec: List[float]) -> List[float]:
    s = sum(vec)
    if s <= 0:
        return vec
    return [v / s for v in vec]


def _pv_shape_hour(hour: int) -> float:
    # simpele “bel-curve” rond 13:00, nul in nacht
    if hour < 6 or hour > 20:
        return 0.0
    x = (hour - 13) / 4.2
    return math.exp(-0.5 * x * x)


def generate_year_timestamps(year: int = 2025, dt_hours: float = 1.0) -> List[datetime]:
    start = datetime(year, 1, 1)
    steps = int(round(8760 / dt_hours))
    return [start + timedelta(hours=i * dt_hours) for i in range(steps)]


def generate_load_profile_kwh(
    annual_load_kwh: float,
    household_profile: str,
    has_heatpump: bool,
    has_ev: bool,
    dt_hours: float = 1.0,
    year: int = 2025
) -> Tuple[List[datetime], List[float]]:
    """
    Genereert een synthetisch jaarprofiel (kWh per timestep).
    - household_profile bepaalt 24u verdeling
    - maandfactoren geven seizoensvorm
    - warmtepomp/EV zijn modifiers op vorm (niet op 'eerlijke' data)
    """
    profile = HOUSEHOLD_PROFILES.get(household_profile, HOUSEHOLD_PROFILES["gezin_kinderen"])
    profile = _normalize(profile)

    ts = generate_year_timestamps(year=year, dt_hours=dt_hours)
    values = [0.0] * len(ts)

    # Modifier templates (simpel, verdedigbaar)
    # Warmtepomp: meer ochtend/avond + winter zwaarder
    hp_hour_boost = [1.0] * 24
    if has_heatpump:
        for h in range(6, 9):
            hp_hour_boost[h] = 1.10
        for h in range(17, 22):
            hp_hour_boost[h] = 1.12

    # EV: extra in avond/nacht
    ev_hour_boost = [1.0] * 24
    if has_ev:
        for h in range(18, 24):
            ev_hour_boost[h] = 1.12
        for h in range(0, 2):
            ev_hour_boost[h] = 1.08

    # per maand eerst normaliseren zodat elk maandblok netjes verdeeld is
    month_f = MONTH_LOAD_FACTORS[:]
    if has_heatpump:
        # warmtepomp maakt winter sterker
        month_f = month_f[:]
        for m in [0, 1, 10, 11]:  # jan, feb, nov, dec
            month_f[m] *= 1.10
    month_f = _normalize(month_f)

    # dagen per maand (geen schrikkeljaar)
    days_per_month = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]

    # totale kWh verdelen over maanden → dagen → uren
    idx = 0
    for month_idx, days in enumerate(days_per_month):
        month_kwh = annual_load_kwh * month_f[month_idx]
        day_kwh = month_kwh / days

        # uurshape incl modifiers
        hour_shape = [profile[h] * hp_hour_boost[h] * ev_hour_boost[h] for h in range(24)]
        hour_shape = _normalize(hour_shape)

        for _ in range(days):
            for hour in range(24):
                # dt_hours is 1.0 in onze default; als je later kwartier wil: opsplitsen
                values[idx] = day_kwh * hour_shape[hour]
                idx += 1

    # guard
    values = values[:len(ts)]
    return ts, values


def generate_pv_profile_kwh(
    annual_pv_kwh: float,
    dt_hours: float = 1.0,
    year: int = 2025
) -> Tuple[List[datetime], List[float]]:
    """
    Synthetisch PV-profiel per uur:
    - maandfactoren
    - dagcurve (belvorm)
    """
    ts = generate_year_timestamps(year=year, dt_hours=dt_hours)
    values = [0.0] * len(ts)

    month_f = _normalize(MONTH_PV_FACTORS[:])

    days_per_month = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]

    idx = 0
    for month_idx, days in enumerate(days_per_month):
        month_kwh = annual_pv_kwh * month_f[month_idx]

        # eerst dagcurve normaliseren zodat per dag sum=1 (alleen over 24 uren)
        day_shape = [_pv_shape_hour(h) for h in range(24)]
        day_shape = _normalize(day_shape)

        day_kwh = month_kwh / days

        for _ in range(days):
            for hour in range(24):
                values[idx] = day_kwh * day_shape[hour]
                idx += 1

    values = values[:len(ts)]
    return ts, values


def generate_dynamic_prices_eur_per_kwh(
    avg_price: float,
    spread: float,
    cheap_hours_per_day: int,
    dt_hours: float = 1.0,
    year: int = 2025
) -> List[float]:
    """
    Maakt synthetische uurprijzen voor een jaar.
    - avg_price: gemiddelde importprijs
    - spread: +/-
    - cheap_hours_per_day: aantal goedkope uren (laag), rest duurder
    """
    ts = generate_year_timestamps(year=year, dt_hours=dt_hours)
    n = len(ts)
    prices = [avg_price] * n

    cheap = max(1, min(12, int(cheap_hours_per_day)))
    expensive = 24 - cheap

    low = max(0.01, avg_price - spread)
    high = max(0.01, avg_price + spread)

    # per dag pattern: goedkoop in nacht + middag, duurder ochtend/avond
    idx = 0
    days = int(round(365))
    for _ in range(days):
        # cheap hours: 0-5 + 12-? (simpel)
        cheap_hours = set(list(range(0, min(6, cheap))) + list(range(12, 12 + max(0, cheap - 6))))
        for h in range(24):
            prices[idx] = low if h in cheap_hours else high
            idx += 1

    return prices[:n]
