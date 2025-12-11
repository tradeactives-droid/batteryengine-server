import random
from datetime import datetime, timedelta

def build_timeseries(values, dt=1.0):
    start = datetime(2025, 1, 1)
    timestamps = [start + timedelta(hours=dt * i) for i in range(len(values))]
    return timestamps

def random_profile(n=24, low=0.0, high=1.0):
    return [random.uniform(low, high) for _ in range(n)]
