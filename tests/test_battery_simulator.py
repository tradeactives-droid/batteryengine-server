import pytest
from battery_engine_pro3.battery_simulator import BatterySimulator, SimulationResult
from battery_engine_pro3.battery_model import BatteryModel
from battery_engine_pro3.types import TimeSeries


def make_ts(values):
    """Helper: maak een TimeSeries met dt = 1 uur."""
    from datetime import datetime, timedelta
    start = datetime(2025, 1, 1)
    timestamps = [start + timedelta(hours=i) for i in range(len(values))]
    return TimeSeries(timestamps=timestamps, values=values, dt_hours=1.0)


def test_simulate_no_battery_basic():
    """Test of import/export correct worden berekend zonder batterij."""
    load = make_ts([3, 2, 1])
    pv   = make_ts([1, 2, 5])

    sim = BatterySimulator(load, pv, battery=None)
    result = sim.simulate_no_battery()

    assert result.import_kwh == pytest.approx(2)
    assert result.export_kwh == pytest.approx(4)

    assert result.import_profile == [2, 0, 0]
    assert result.export_profile == [0, 0, 4]


def test_simulate_with_battery_charge_discharge():
    load = make_ts([0, 5])
    pv   = make_ts([5, 0])

    batt = BatteryModel(E_cap=10, P_max=5, dod=0.9, eta=0.9)

    sim = BatterySimulator(load, pv, batt)
    result = sim.simulate_with_battery()

    assert result.soc_profile[0] == pytest.approx(4.5, abs=0.1)
    assert result.import_profile[1] == pytest.approx(0.5, abs=0.1)


def test_soc_limits_respected():
    load = make_ts([0, 0, 10, 10])
    pv   = make_ts([10, 10, 0, 0])

    batt = BatteryModel(E_cap=10, P_max=3, dod=0.8, eta=0.9)

    sim = BatterySimulator(load, pv, batt)
    result = sim.simulate_with_battery()

    for soc in result.soc_profile:
        assert soc >= batt.E_min - 1e-6
        assert soc <= batt.E_max + 1e-6
