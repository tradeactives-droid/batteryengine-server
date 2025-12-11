import pytest

from battery_engine_pro3.peak_optimizer import PeakOptimizer
from battery_engine_pro3.battery_model import BatteryModel
from battery_engine_pro3.types import TimeSeries


def make_ts(values):
    """Helper: maak een TimeSeries met dt = 1 uur."""
    from datetime import datetime, timedelta
    start = datetime(2025, 1, 1)
    timestamps = [start + timedelta(hours=i) for i in range(len(values))]
    return TimeSeries(timestamps=timestamps, values=values, dt_hours=1.0)


# ------------------------------------------------------------
# 1. compute_monthly_peaks
# ------------------------------------------------------------

def test_compute_monthly_peaks():
    """
    Test een klein profiel van 48 uur (2 dagen, maand = januari).
    Netbelasting = load - pv
    """
    load = make_ts([5, 3, 1, 8, 7, 2, 3, 1])
    pv   = make_ts([1, 1, 1, 1, 1, 1, 1, 1])

    peaks = PeakOptimizer.compute_monthly_peaks(load, pv)

    # Net load: [4,2,0,7,6,1,2,0] → max = 7 kW → januari
    assert len(peaks) == 12
    assert peaks[0] == 7
    assert all(p == 0 for p in peaks[1:])


# ------------------------------------------------------------
# 2. compute_monthly_targets
# ------------------------------------------------------------

def test_compute_monthly_targets():
    baseline = [10, 20, 30] + [0]*9

    targets = PeakOptimizer.compute_monthly_targets(baseline, reduction_factor=0.8)

    # 20% reductie
    assert targets[0] == pytest.approx(8.0)
    assert targets[1] == pytest.approx(16.0)
    assert targets[2] == pytest.approx(24.0)
    assert all(t == 0 for t in targets[3:])


# ------------------------------------------------------------
# 3. simulate_with_peak_shaving
# ------------------------------------------------------------

def test_simulate_with_peak_shaving_basic():
    """
    Test een eenvoudige peak shaving situatie:
    - Laadprofiel veroorzaakt een maandpiek van 10 kW
    - Target is 6 kW
    - Batterij moet 4 kW leveren
    """

    load = make_ts([10])   # 10 kW vraag
    pv   = make_ts([0])    # geen PV

    battery = BatteryModel(
        E_cap=10,   # 10 kWh
        P_max=10,   # 10 kW maximum
        dod=0.9,
        eta=1.0     # geen efficiency complicaties
    )

    targets = [6] + [0]*11

    new_peaks, imp, exp, soc = PeakOptimizer.simulate_with_peak_shaving(
        load, pv, battery, targets
    )

    # 10 → target 6 → reductie 4 kW
    assert new_peaks[0] == pytest.approx(6.0)

    # import moet 6 zijn (want 4 uit batterij)
    assert imp == pytest.approx([6.0])

    # export = 0
    assert exp == pytest.approx([0.0])

    # SoC moet omlaag zijn gegaan
    assert soc[0] < battery.E_max
