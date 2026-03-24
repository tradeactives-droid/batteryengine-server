from battery_engine_pro3.profile_generator import generate_load_profile_kwh


def _daytime_fraction(values):
    total = sum(values)
    if total <= 0:
        return 0.0
    day = 0.0
    for i, v in enumerate(values):
        hour = i % 24
        if 7 <= hour <= 22:
            day += v
    return day / total


def test_home_during_day_never_has_lower_daytime_share_than_always():
    _, never_vals = generate_load_profile_kwh(
        annual_load_kwh=3600,
        household_profile="gezin_kinderen",
        has_heatpump=False,
        has_ev=False,
        home_during_day="never",
        daytime_fraction=None,
        dt_hours=1.0,
        year=2025,
    )
    _, always_vals = generate_load_profile_kwh(
        annual_load_kwh=3600,
        household_profile="gezin_kinderen",
        has_heatpump=False,
        has_ev=False,
        home_during_day="always",
        daytime_fraction=None,
        dt_hours=1.0,
        year=2025,
    )
    assert _daytime_fraction(never_vals) < _daytime_fraction(always_vals)


def test_home_during_day_always_has_higher_daytime_share_than_never():
    _, always_vals = generate_load_profile_kwh(
        annual_load_kwh=4000,
        household_profile="gepensioneerd",
        has_heatpump=True,
        has_ev=False,
        home_during_day="always",
        daytime_fraction=None,
        dt_hours=1.0,
        year=2025,
    )
    _, never_vals = generate_load_profile_kwh(
        annual_load_kwh=4000,
        household_profile="gepensioneerd",
        has_heatpump=True,
        has_ev=False,
        home_during_day="never",
        daytime_fraction=None,
        dt_hours=1.0,
        year=2025,
    )
    assert _daytime_fraction(always_vals) > _daytime_fraction(never_vals)


def test_daytime_fraction_overrides_home_during_day():
    _, vals = generate_load_profile_kwh(
        annual_load_kwh=3650,
        household_profile="gezin_kinderen",
        has_heatpump=False,
        has_ev=True,
        home_during_day="never",
        daytime_fraction=0.70,
        dt_hours=1.0,
        year=2025,
    )
    frac = _daytime_fraction(vals)
    assert 0.68 <= frac <= 0.72

