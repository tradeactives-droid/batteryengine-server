import pytest
from battery_engine_pro3.battery_model import BatteryModel

def test_battery_model_init_basic():
    """Test of BatteryModel basisvelden correct berekent."""
    batt = BatteryModel(E_cap=10, P_max=5, dod=0.9, eta=0.9)

    assert batt.capacity_kwh == 10
    assert batt.power_kw == 5

    # DoD 0.9 → minimaal 10% over → E_min = 1.0
    assert pytest.approx(batt.E_min, 0.01) == 1.0
    assert pytest.approx(batt.E_max, 0.01) == 10.0

def test_efficiency_split():
    """Test of round-trip efficiency correct wordt gesplitst."""
    batt = BatteryModel(E_cap=10, P_max=5, dod=0.9, eta=0.81)  # sqrt(0.81) = 0.9
    assert pytest.approx(batt.eta_charge, 0.001) == 0.9
    assert pytest.approx(batt.eta_discharge, 0.001) == 0.9

def test_soc_initialisation():
    """Controleer of initial_soc_frac correct wordt toegepast."""
    batt = BatteryModel(E_cap=10, P_max=5, dod=0.8, eta=0.9, initial_soc_frac=0.5)

    # DoD 0.8 → E_min = 2 kWh, E_max = 10 kWh
    # SoC = 2 + 0.5 * (10 - 2) = 2 + 4 = 6
    assert pytest.approx(batt.initial_soc_kwh, 0.01) == 6.0
