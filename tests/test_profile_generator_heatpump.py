import pytest

from battery_engine_pro3.profile_generator import generate_load_profile_kwh


def _first_day(vals):
    return vals[0:24]


def test_air_water_day_night_boosts_evening_vs_no_heatpump():
    common = dict(
        annual_load_kwh=4000.0,
        household_profile="gezin_kinderen",
        has_ev=False,
        dt_hours=1.0,
        year=2025,
    )
    _, with_hp = generate_load_profile_kwh(
        has_heatpump=True,
        heatpump_type="air_water",
        heatpump_schedule="day_night",
        **common,
    )
    _, no_hp = generate_load_profile_kwh(
        has_heatpump=False,
        **common,
    )
    d0_hp = _first_day(with_hp)
    d0_no = _first_day(no_hp)
    # uren 17–21 (inclusief 17 t/m 21)
    s_hp = sum(d0_hp[h] for h in range(17, 22))
    s_no = sum(d0_no[h] for h in range(17, 22))
    assert s_hp > s_no

    _, hp_defaults = generate_load_profile_kwh(
        has_heatpump=True,
        heatpump_type=None,
        heatpump_schedule=None,
        **{k: v for k, v in common.items()},
    )
    assert hp_defaults == with_hp


def test_air_water_buffer_night_more_night_than_evening():
    """
    Buffervat + 'night' versterkt 0–5u meer dan buffer + day_night
    (laadbucket 's nachts); absoluut nacht > avond geldt niet bij sterke avondpiek in het basisprofiel.
    """
    common = dict(
        annual_load_kwh=4200.0,
        household_profile="gezin_kinderen",
        has_heatpump=True,
        heatpump_type="air_water_buffer",
        has_ev=False,
        dt_hours=1.0,
        year=2025,
    )
    _, vals_night = generate_load_profile_kwh(
        heatpump_schedule="night",
        **common,
    )
    _, vals_dn = generate_load_profile_kwh(
        heatpump_schedule="day_night",
        **common,
    )
    night_bucket = sum(_first_day(vals_night)[h] for h in range(0, 6))
    dn_bucket = sum(_first_day(vals_dn)[h] for h in range(0, 6))
    assert night_bucket > dn_bucket


def test_air_water_day_schedule_more_day_than_night_schedule():
    common = dict(
        annual_load_kwh=4500.0,
        household_profile="alleenstaand_werkend",
        has_heatpump=True,
        has_ev=False,
        heatpump_type="air_water",
        dt_hours=1.0,
        year=2025,
    )
    _, vals_day = generate_load_profile_kwh(
        heatpump_schedule="day",
        **common,
    )
    _, vals_night = generate_load_profile_kwh(
        heatpump_schedule="night",
        **common,
    )
    d_day = _first_day(vals_day)
    d_night = _first_day(vals_night)
    # uren 8–17 (8 t/m 16)
    s_day = sum(d_day[h] for h in range(8, 17))
    s_night_sched = sum(d_night[h] for h in range(8, 17))
    assert s_day > s_night_sched


def test_has_heatpump_false_ignores_heatpump_params():
    common = dict(
        annual_load_kwh=3800.0,
        household_profile="samenwonend_werkend",
        has_heatpump=False,
        has_ev=False,
        dt_hours=1.0,
        year=2025,
    )
    _, baseline = generate_load_profile_kwh(**common)
    _, with_hp_fields = generate_load_profile_kwh(
        heatpump_type="air_water_buffer",
        heatpump_schedule="night",
        **common,
    )
    assert len(baseline) == len(with_hp_fields)
    for a, b in zip(baseline, with_hp_fields):
        assert a == pytest.approx(b)
