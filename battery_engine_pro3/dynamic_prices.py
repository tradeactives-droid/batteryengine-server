from __future__ import annotations
from typing import List, Optional

try:
    from battery_engine_pro3.data.nl_day_ahead_2024 import (
        NL_2024_PRICES_EUR_MWH,
    )
    _HISTORIC_PRICES_EUR_MWH = NL_2024_PRICES_EUR_MWH
    _HISTORIC_SOURCE = "historic_2024_nl"
except ImportError:
    _HISTORIC_PRICES_EUR_MWH = None
    _HISTORIC_SOURCE = "fallback_profile"


def _normalize_profile(p: List[float]) -> List[float]:
    avg = sum(p) / len(p) if p else 1.0
    if avg <= 0:
        return [1.0 for _ in p]
    return [x / avg for x in p]


def _fallback_hourly_profile() -> List[float]:
    """
    Simpel NL/BE-achtig uurprofiel:
    - nacht laag
    - ochtend piek
    - middag gemiddeld
    - avond hoogste piek
    Gemiddelde wordt later genormaliseerd naar 1.0
    """
    p = [
        0.75, 0.72, 0.70, 0.70, 0.72, 0.78,  # 00-05
        0.95, 1.05, 1.10,                    # 06-08
        1.02, 0.98, 0.95,                    # 09-11
        0.92, 0.95, 0.98,                    # 12-14
        1.05, 1.15, 1.25,                    # 15-17
        1.35, 1.45, 1.40,                    # 18-20
        1.20, 1.00, 0.85                     # 21-23
    ]
    return _normalize_profile(p)


def _historic_scaled_eur_kwh(avg_import_price: float) -> List[float]:
    hist = _HISTORIC_PRICES_EUR_MWH or []
    historic_avg_eur_kwh = (
        sum(hist) / len(hist) / 1000.0
    )
    if historic_avg_eur_kwh <= 0:
        historic_avg_eur_kwh = 1e-9
    scale = avg_import_price / historic_avg_eur_kwh
    return [
        round((p / 1000.0) * scale, 6)
        for p in hist
    ]


def _resample_year_hourly_to_steps(
    hourly_year: List[float],
    n_steps: int,
    dt_hours: float,
) -> List[float]:
    """Trim of herhaal 8760 uurwaarden naar exact n_steps stappen."""
    if dt_hours <= 0:
        dt_hours = 1.0
    L = len(hourly_year)
    if L == 0:
        return [0.0] * n_steps
    out: List[float] = []
    for i in range(n_steps):
        pos = int(i * dt_hours) % L
        out.append(hourly_year[pos])
    return out


def build_dynamic_prices_hybrid(
    n_steps: int,
    dt_hours: float,
    avg_import_price: float,
    historic_prices: Optional[List[float]] = None,
) -> tuple[List[float], str]:
    """
    Return:
      prices: length == n_steps
      source: "historic" | "historic_2024_nl_scaled" | "fallback_profile"

    historic_prices worden alleen gebruikt als ze exact passen.
    Anders: NL 2024 day-ahead (€/MWh) geschaald naar avg_import_price (€/kWh),
    of fallback-uurprofiel.
    """
    if avg_import_price <= 0:
        avg_import_price = 0.01

    # 1) Historic indien beschikbaar en passend
    if historic_prices and len(historic_prices) == n_steps:
        return historic_prices, "historic"

    # 2) Vooringeladen NL 2024-serie (€/MWh) → schaal naar €/kWh, resample
    if _HISTORIC_PRICES_EUR_MWH is not None:
        scaled_full = _historic_scaled_eur_kwh(avg_import_price)
        prices = _resample_year_hourly_to_steps(scaled_full, n_steps, dt_hours)
        return prices, "historic_2024_nl_scaled"

    # 3) Fallback profiel herhalen en schalen
    prof24 = _fallback_hourly_profile()
    prices_fb: List[float] = []

    if dt_hours <= 0:
        dt_hours = 1.0

    for i in range(n_steps):
        hour_of_day = int((i * dt_hours) % 24)
        prices_fb.append(avg_import_price * prof24[hour_of_day])

    return prices_fb, "fallback_profile"
