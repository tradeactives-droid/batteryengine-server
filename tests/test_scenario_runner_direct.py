"""Directe jaarlijkse A1/B1 op basis van opgegeven jaargetallen."""

import pytest

from battery_engine_pro3.scenario_runner import ScenarioRunner
from battery_engine_pro3.types import BatteryConfig, TariffConfig, TimeSeries


def make_ts(values):
    from datetime import datetime, timedelta

    start = datetime(2025, 1, 1)
    timestamps = [start + timedelta(hours=i) for i in range(len(values))]
    return TimeSeries(timestamps=timestamps, values=values, dt_hours=1.0)


def _tiny_battery():
    return BatteryConfig(
        E=0.1,
        P=0.1,
        DoD=0.9,
        eta_rt=0.9,
        investment_eur=1.0,
        degradation_per_year=0.01,
    )


def _tariff_test1_2():
    return TariffConfig(
        country="NL",
        current_tariff="enkel",
        p_enkel_imp=0.29,
        p_enkel_exp=0.07,
        p_dag=0.32,
        p_nacht=0.26,
        p_exp_dn=0.07,
        p_export_dyn=0.07,
        dynamic_prices=[0.29] * 24,
        vastrecht_year=180.0,
        feedin_monthly_cost=0.0,
        feedin_cost_per_kwh=0.0,
        feedin_free_kwh=0.0,
        feedin_price_after_free=0.0,
        inverter_power_kw=0.0,
        inverter_cost_per_kw=0.0,
        capacity_tariff_kw=0.0,
        p_dyn_imp=0.29,
    )


def _tariff_test4():
    return TariffConfig(
        country="NL",
        current_tariff="enkel",
        p_enkel_imp=0.29,
        p_enkel_exp=0.07,
        p_dag=0.32,
        p_nacht=0.26,
        p_exp_dn=0.07,
        p_export_dyn=0.07,
        dynamic_prices=[0.29] * 24,
        vastrecht_year=180.0,
        feedin_monthly_cost=0.0,
        feedin_cost_per_kwh=0.0,
        feedin_free_kwh=0.0,
        feedin_price_after_free=0.0,
        inverter_power_kw=0.0,
        inverter_cost_per_kw=0.0,
        capacity_tariff_kw=0.0,
        p_dyn_imp=0.29,
    )


def _tariff_test5_6():
    return TariffConfig(
        country="NL",
        current_tariff="dag_nacht",
        p_enkel_imp=0.29,
        p_enkel_exp=0.07,
        p_dag=0.32,
        p_nacht=0.26,
        p_exp_dn=0.07,
        p_export_dyn=0.07,
        dynamic_prices=[0.29] * 24,
        vastrecht_year=180.0,
        feedin_monthly_cost=0.0,
        feedin_cost_per_kwh=0.0,
        feedin_free_kwh=0.0,
        feedin_price_after_free=0.0,
        inverter_power_kw=0.0,
        inverter_cost_per_kw=0.0,
        capacity_tariff_kw=0.0,
        p_dyn_imp=0.29,
    )


def _run_direct(load_kwh, pv_kwh, feedin_kwh, tariff, daytime_fraction=None):
    load = make_ts([load_kwh / 8760.0] * 8760)
    pv = make_ts([pv_kwh / 8760.0] * 8760)
    return ScenarioRunner(
        load,
        pv,
        tariff,
        _tiny_battery(),
        annual_load_kwh=load_kwh,
        annual_pv_kwh=pv_kwh,
        annual_feedin_kwh=feedin_kwh,
        daytime_fraction=daytime_fraction,
    ).run()


def test_direct_a1_enkel_more_export_than_import():
    out = _run_direct(3800, 5200, 2400, _tariff_test1_2())
    assert out["A1"]["total_cost_eur"] == pytest.approx(82.00)


def test_direct_b1_enkel_same_input():
    out = _run_direct(3800, 5200, 2400, _tariff_test1_2())
    assert out["B1"]["enkel"]["total_cost_eur"] == pytest.approx(302.00)


def test_direct_b1_greater_than_a1():
    out = _run_direct(3800, 5200, 2400, _tariff_test1_2())
    a1 = out["A1"]["total_cost_eur"]
    b1 = out["B1"]["enkel"]["total_cost_eur"]
    assert b1 > a1
    assert (b1 - a1) == pytest.approx(220.0)


def test_direct_a1_enkel_more_import_than_export():
    out = _run_direct(5000, 2000, 500, _tariff_test4())
    assert out["A1"]["total_cost_eur"] == pytest.approx(1050.00)


def test_direct_a1_dag_nacht_more_export_than_import():
    out = _run_direct(
        3800, 5200, 2400, _tariff_test5_6(), daytime_fraction=0.526
    )
    assert out["A1"]["total_cost_eur"] == pytest.approx(82.00)
    assert out["A1_per_tariff"]["dag_nacht"]["total_cost_eur"] == pytest.approx(
        82.00
    )


def test_direct_b1_dag_nacht_same_as_test5():
    out = _run_direct(
        3800, 5200, 2400, _tariff_test5_6(), daytime_fraction=0.526
    )
    assert out["B1"]["dag_nacht"]["total_cost_eur"] == pytest.approx(272.00)


def test_fallback_missing_feedin_uses_simulated_a1_b1():
    n = 8760
    load = make_ts([1.0] * n)
    pv = make_ts([0.5] * n)
    tariff = _tariff_test1_2()
    tariff.dynamic_prices = [0.29] * n
    runner = ScenarioRunner(
        load,
        pv,
        tariff,
        _tiny_battery(),
        annual_load_kwh=5000.0,
        annual_pv_kwh=3000.0,
        annual_feedin_kwh=None,
    )
    out = runner.run()
    assert "A1" in out and "B1" in out
    assert out["A1"]["total_cost_eur"] is not None
    assert out["B1"]["enkel"]["total_cost_eur"] is not None
