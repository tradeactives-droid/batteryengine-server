import pytest
from battery_engine_pro3.types import TimeSeries
from datetime import datetime, timedelta

@pytest.fixture
def simple_load_pv():
    load = [1.0] * 24
    pv = [0.5] * 24

    ts = [datetime(2025, 1, 1) + timedelta(hours=i) for i in range(24)]

    load_ts = TimeSeries(ts, load, dt_hours=1.0)
    pv_ts = TimeSeries(ts, pv, dt_hours=1.0)

    return load_ts, pv_ts
