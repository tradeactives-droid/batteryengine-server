from battery_engine_pro3.profile_generator import generate_load_profile_kwh


def test_daytime_fraction_applied_to_generated_profile():
    _, vals = generate_load_profile_kwh(
        annual_load_kwh=3650,
        household_profile="gezin_kinderen",
        has_heatpump=False,
        has_ev=False,
        daytime_fraction=0.70,
        dt_hours=1.0,
        year=2025,
    )

    total = sum(vals)
    assert total > 0

    daytime = 0.0
    for i, v in enumerate(vals):
        hour = i % 24
        if 7 <= hour <= 22:
            daytime += v

    fraction = daytime / total
    assert 0.68 <= fraction <= 0.72

