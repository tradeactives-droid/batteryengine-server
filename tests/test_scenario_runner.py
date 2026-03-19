import pytest

from battery_engine_pro3.scenario_runner import ScenarioRunner
from battery_engine_pro3.types import TimeSeries, TariffConfig, BatteryConfig


def make_ts(values):
    """Helper voor TimeSeries dt=1h."""
    from datetime import datetime, timedelta
    start = datetime(2025, 1, 1)
    timestamps = [start + timedelta(hours=i) for i in range(len(values))]
    return TimeSeries(timestamps=timestamps, values=values, dt_hours=1.0)


# ------------------------------------------------------------
# Helpers
# ------------------------------------------------------------

def base_tariff(country="NL", current="enkel"):
    return TariffConfig(
        country=country,
        current_tariff=current,

        p_enkel_imp=0.40,
        p_enkel_exp=0.10,

        p_dag=0.45,
        p_nacht=0.25,
        p_exp_dn=0.08,

        p_export_dyn=0.12,
        dynamic_prices=None,

        vastrecht_year=100.0,

        feedin_monthly_cost=0.0,
        feedin_cost_per_kwh=0.0,
        feedin_free_kwh=0.0,
        feedin_price_after_free=0.0,

        inverter_power_kw=5.0,
        inverter_cost_per_kw=10.0,

        capacity_tariff_kw=50.0 if country == "BE" else 0.0
    )


def base_battery():
    return BatteryConfig(
        E=10,
        P=5,
        DoD=0.9,
        eta_rt=0.9,
        investment_eur=4000,
        degradation_per_year=0.01
    )


# ------------------------------------------------------------
# NL TEST
# ------------------------------------------------------------

def test_scenario_runner_NL_end_to_end():
    load = make_ts([2, 2, 2])
    pv   = make_ts([1, 3, 0])

    tariff = base_tariff(country="NL", current="enkel")
    batt   = base_battery()

    runner = ScenarioRunner(load, pv, tariff, batt)
    out = runner.run()

    # Outputstructuur testen
    assert "A1" in out
    assert "B1" in out
    assert "C1" in out
    assert "roi" in out
    assert "peaks" in out

    # A1 moet dict zijn met total_cost_eur
    A1 = out["A1"]
    assert "total_cost_eur" in A1

    # NL heeft geen peaks
    assert out["peaks"]["monthly_before"] == []
    assert out["peaks"]["monthly_after"] == []

    # ROI moet een geldige dict zijn
    assert "yearly_saving_eur" in out["roi"]


# ------------------------------------------------------------
# BE TEST (peak shaving)
# ------------------------------------------------------------

def test_scenario_runner_BE_peak_shaving():
    load = make_ts([5, 5, 5])
    pv   = make_ts([0, 0, 0])

    tariff = base_tariff(country="BE", current="enkel")
    batt   = base_battery()

    runner = ScenarioRunner(load, pv, tariff, batt)
    out = runner.run()

    # BE → peaks structuur moet bestaan
    assert "monthly_before" in out["peaks"]
    assert "monthly_after" in out["peaks"]

    # Kosten moeten bestaan
    assert out["C1"]["enkel"]["total_cost_eur"] is not None

    # ROI structure ok
    assert "yearly_saving_eur" in out["roi"]
