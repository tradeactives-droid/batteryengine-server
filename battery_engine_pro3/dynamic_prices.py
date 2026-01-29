from __future__ import annotations
from typing import List, Optional

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

def build_dynamic_prices_hybrid(
    n_steps: int,
    dt_hours: float,
    avg_import_price: float,
    historic_prices: Optional[List[float]] = None,
) -> tuple[List[float], str]:
    """
    Return:
      prices: length == n_steps
      source: "historic" or "fallback_profile"

    historic_prices worden alleen gebruikt als ze exact passen.
    """
    if avg_import_price <= 0:
        avg_import_price = 0.01

    # 1) Historic indien beschikbaar en passend
    if historic_prices and len(historic_prices) == n_steps:
        return historic_prices, "historic"

    # 2) Fallback profiel herhalen en schalen
    prof24 = _fallback_hourly_profile()
    prices: List[float] = []

    hours_total = n_steps * dt_hours
    if dt_hours <= 0:
        dt_hours = 1.0

    # We nemen aan dat step-index i overeenkomt met een “uur van de dag”
    # bij dt=1.0; bij dt!=1.0 gebruiken we floor(uur) om profiel te kiezen.
    for i in range(n_steps):
        hour_of_day = int((i * dt_hours) % 24)
        prices.append(avg_import_price * prof24[hour_of_day])

    return prices, "fallback_profile"
