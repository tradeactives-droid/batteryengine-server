from datetime import datetime, timedelta

import pytest

from battery_engine_pro3.data.nl_day_ahead_2024 import NL_2024_PRICES_EUR_MWH
from battery_engine_pro3.dynamic_prices import build_dynamic_prices_hybrid


def test_nl_2024_prices_length_and_positive():
    assert len(NL_2024_PRICES_EUR_MWH) == 8760
    assert all(p > 0 for p in NL_2024_PRICES_EUR_MWH)


def test_scaled_series_mean_matches_target_import_price():
    target = 0.25
    prices, source = build_dynamic_prices_hybrid(
        n_steps=8760,
        dt_hours=1.0,
        avg_import_price=target,
        historic_prices=None,
    )
    assert len(prices) == 8760
    assert source == "historic_2024_nl_scaled"
    mean_p = sum(prices) / len(prices)
    assert mean_p == pytest.approx(target, rel=0.02)


def test_evening_hours_higher_than_night_hours_on_average():
    prices, _ = build_dynamic_prices_hybrid(
        n_steps=8760,
        dt_hours=1.0,
        avg_import_price=0.25,
        historic_prices=None,
    )
    start = datetime(2024, 1, 1)
    evening_vals = []
    night_vals = []
    for i, p in enumerate(prices):
        dt = start + timedelta(hours=i)
        h = dt.hour
        if h in (18, 19, 20):
            evening_vals.append(p)
        if h in (1, 2, 3, 4):
            night_vals.append(p)
    assert evening_vals and night_vals
    assert sum(evening_vals) / len(evening_vals) > sum(night_vals) / len(night_vals)
