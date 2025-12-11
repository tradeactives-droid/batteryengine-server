import pytest
from battery_engine_pro3.battery_simulator import BatterySimulator
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

    # Moment 1: load3 - pv1 = 2 import
    # Moment 2: load2 - pv2 = 0
    # Moment 3: load1 - pv5 = 4 export
    assert result.import_kwh == pytest.approx(2)
    assert result.export_kwh == pytest.approx(4)

    assert result.import_profile == [2, 0, 0]
    assert result.export_profile == [0, 0, 4]

def test_simulate_with_battery_charge_discharge():
    """
    Test eenvoudig laad/ontlaadscenario:
    - uur 1: PV overschot → batterij moet laden
    - uur 2: load > PV → batterij moet ontladen
    """
    load = make_ts([0, 5])
    pv   = make_ts([5, 0])

    batt = BatteryModel(E_cap=10, P_max=5, dod=0.9, eta=0.9)

    sim = BatterySimulator(load, pv, batt)
    result = sim.simulate_with_battery()

    # UUR 1 — laden
    # overschot = 5 kWh, max charge = 5 kW * 1h = 5 kWh
    # efficiency = 0.9 → SoC stijgt 4.5 kWh
    assert result.soc_profile[0] > 4.4 and result.soc_profile[0] < 4.6

    # UUR 2 — ontladen
    # load = 5, batterij kan 5 kW leveren → 5 kWh * eta_d = ~4.5kWh
    # grid_import = 5 - 4.5 = 0.5
    assert result.import_profile[1] == pytest.approx(0.5, abs=0.1)

def test_soc_limits_respected():
    """Test dat batterij nooit onder E_min of boven E_max komt."""
    load = make_ts([0, 0, 10, 10])
    pv   = make_ts([10, 10, 0, 0])

    batt = BatteryModel(E_cap=10, P_max=3, dod=0.8, eta=0.9)

    sim = BatterySimulator(load, pv, batt)
    result = sim.simulate_with_battery()

    for soc in result.soc_profile:
        assert soc >= batt.E_min - 1e-6
        assert soc <= batt.E_max + 1e-6
