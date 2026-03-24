import pytest

from battery_engine_pro3.profile_generator import generate_load_profile_kwh


def _month_sums_from_hourly(values):
    days_per_month = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    out = []
    idx = 0
    for days in days_per_month:
        steps = days * 24
        out.append(sum(values[idx: idx + steps]))
        idx += steps
    return out


def test_monthly_kwh_matches_provided_values():
    monthly = [300, 250, 280, 220, 200, 180, 170, 175, 210, 260, 290, 310]
    _, vals = generate_load_profile_kwh(
        annual_load_kwh=2845,
        household_profile="gezin_kinderen",
        has_heatpump=False,
        has_ev=False,
        monthly_kwh=monthly,
        dt_hours=1.0,
        year=2025,
    )
    got = _month_sums_from_hourly(vals)
    for g, e in zip(got, monthly):
        assert g == pytest.approx(e, rel=0.01)


def test_monthly_kwh_invalid_length_falls_back_without_exception():
    bad_monthly = [250] * 11
    _, vals = generate_load_profile_kwh(
        annual_load_kwh=3000,
        household_profile="gezin_kinderen",
        has_heatpump=True,
        has_ev=False,
        monthly_kwh=bad_monthly,
        dt_hours=1.0,
        year=2025,
    )
    assert len(vals) == 8760
    assert sum(vals) > 0


def test_monthly_kwh_none_keeps_normal_behavior():
    _, vals = generate_load_profile_kwh(
        annual_load_kwh=3200,
        household_profile="thuiswerker",
        has_heatpump=False,
        has_ev=True,
        monthly_kwh=None,
        dt_hours=1.0,
        year=2025,
    )
    assert len(vals) == 8760
    assert sum(vals) > 0

