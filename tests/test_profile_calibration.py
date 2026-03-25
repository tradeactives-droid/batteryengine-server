import pytest

from battery_engine_pro3.profile_generator import (
    generate_load_profile_kwh,
    generate_pv_profile_kwh,
)


def _simulated_feedin_kwh(load_vals, pv_vals):
    n = min(len(load_vals), len(pv_vals))
    return sum(max(0.0, pv_vals[i] - load_vals[i]) for i in range(n))


def test_calibrate_feedin_brings_export_near_target():
    """
    PV alleen in uren 8–16 (calibratie-venster), opname 4000 kWh/jaar.
    Zonder calibratie ~2500 kWh teruglevering (load ~4750 kWh);
    met annual_feedin_kwh=1500 binnen 10% van target na calibratie.
    """
    ts_pv, pv_full = generate_pv_profile_kwh(
        annual_pv_kwh=4000.0,
        dt_hours=1.0,
        year=2025,
    )
    pv_vals = [v if 8 <= ts_pv[i].hour <= 16 else 0.0 for i, v in enumerate(pv_full)]
    s = sum(pv_vals)
    pv_vals = [v * 4000.0 / s for v in pv_vals]

    annual_load = 4750.0
    _, load_uncal = generate_load_profile_kwh(
        annual_load_kwh=annual_load,
        household_profile="gezin_kinderen",
        has_heatpump=False,
        has_ev=False,
        dt_hours=1.0,
        year=2025,
        annual_feedin_kwh=None,
        pv_values_for_calibration=None,
    )
    before = _simulated_feedin_kwh(load_uncal, pv_vals)
    assert 2300 < before < 2700

    _, load_cal = generate_load_profile_kwh(
        annual_load_kwh=annual_load,
        household_profile="gezin_kinderen",
        has_heatpump=False,
        has_ev=False,
        dt_hours=1.0,
        year=2025,
        annual_feedin_kwh=1500.0,
        pv_values_for_calibration=pv_vals,
    )
    after = _simulated_feedin_kwh(load_cal, pv_vals)
    assert after == pytest.approx(1500.0, rel=0.10)


def test_no_feedin_calibration_leaves_profile_unchanged():
    common = dict(
        annual_load_kwh=3200.0,
        household_profile="alleenstaand_werkend",
        has_heatpump=False,
        has_ev=False,
        dt_hours=1.0,
        year=2025,
    )
    ts_a, vals_a = generate_load_profile_kwh(
        annual_feedin_kwh=None,
        pv_values_for_calibration=None,
        **common,
    )
    ts_b, vals_b = generate_load_profile_kwh(**common)
    assert ts_a == ts_b
    assert len(vals_a) == len(vals_b)
    for x, y in zip(vals_a, vals_b):
        assert x == pytest.approx(y)
