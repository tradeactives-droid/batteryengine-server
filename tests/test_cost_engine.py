import pytest

from battery_engine_pro3.cost_engine import CostEngine
from battery_engine_pro3.types import TariffConfig, ScenarioResult


def make_tariff(
    country="NL",
    current_tariff="enkel",
    p_enkel_imp=0.40,
    p_enkel_exp=0.10,
    p_dag=0.50,
    p_nacht=0.30,
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
    capacity_tariff_kw=0.0,
    saldering=False,
):
    return TariffConfig(
        country=country,
        current_tariff=current_tariff,

        p_enkel_imp=p_enkel_imp,
        p_enkel_exp=p_enkel_exp,

        p_dag=p_dag,
        p_nacht=p_nacht,
        p_exp_dn=p_exp_dn,

        p_export_dyn=p_export_dyn,
        dynamic_prices=dynamic_prices,

        vastrecht_year=vastrecht_year,

        feedin_monthly_cost=feedin_monthly_cost,
        feedin_cost_per_kwh=feedin_cost_per_kwh,
        feedin_free_kwh=feedin_free_kwh,
        feedin_price_after_free=feedin_price_after_free,

        inverter_power_kw=inverter_power_kw,
        inverter_cost_per_kw=inverter_cost_per_kw,

        capacity_tariff_kw=capacity_tariff_kw,
        saldering=saldering,
    )


def test_enkel_tarief_basic():
    """
    import_kwh = 100 kWh
    export_kwh = 40 kWh
    prijs import = 0.40
    prijs export = 0.10
    """
    cfg = make_tariff()

    cost_engine = CostEngine(cfg)

    res = cost_engine.compute_cost(
        import_profile_kwh=[100],
        export_profile_kwh=[40],
        tariff_type="enkel"
    )

    # import 100 * 0.40 = 40
    # export 40 * 0.10 = 4 → aftrek
    # vastrecht = 100
    # omvormer = 5 kW * €10 = 50
    expected = 40 - 4 + 100 + 50

    assert res.total_cost_eur == pytest.approx(expected)


def test_enkel_saldering_uses_profile_not_annual_totals():
    """
    Regressie: bij gelijke jaarimport/jaarexport mag kosten niet 0 worden
    door jaarlijkse wegstreping; gebruik tijdsprofiel.
    """
    cfg = make_tariff()
    cfg.saldering = True

    cost_engine = CostEngine(cfg)

    # Jaarimport = 2 kWh, jaarexport = 2 kWh, maar op verschillende tijdstappen.
    import_profile = [1.0, 1.0, 0.0, 0.0]
    export_profile = [0.0, 0.0, 1.0, 1.0]

    res = cost_engine.compute_cost(
        import_profile_kwh=import_profile,
        export_profile_kwh=export_profile,
        tariff_type="enkel",
        dt_hours=1.0,
    )

    expected_energy = 2.0 * cfg.p_enkel_imp
    expected_total = expected_energy + cfg.vastrecht_year + cfg.inverter_power_kw * cfg.inverter_cost_per_kw

    assert sum(import_profile) == pytest.approx(sum(export_profile))
    assert res.total_cost_eur == pytest.approx(expected_total)


def test_feedin_costs():
    """
    feed-in vaste kosten + variabele kosten boven drempel
    """
    cfg = make_tariff(
        feedin_monthly_cost=2.0,
        feedin_cost_per_kwh=1.0,          # geactiveerd
        feedin_free_kwh=10,
        feedin_price_after_free=0.05
    )

    cost_engine = CostEngine(cfg)

    res = cost_engine.compute_cost(
        import_profile_kwh=[0],
        export_profile_kwh=[50],  # 40 kWh boven gratis 10
        tariff_type="enkel"
    )

    # vaste feedin: 2*12 = 24
    # variabel: (50 - 10) * 0.05 = 2
    # energie enkel: 0 import − 50 * p_enkel_exp (terugleververgoeding)
    expected_extra = 24 + 2
    energy = -50.0 * cfg.p_enkel_exp
    assert res.total_cost_eur == pytest.approx(
        cfg.vastrecht_year + cfg.inverter_power_kw * cfg.inverter_cost_per_kw + expected_extra + energy
    )


def test_capacity_tariff_BE():
    """
    Test of capaciteitstarief goed verwerkt wordt.
    """
    cfg = make_tariff(
        country="BE",
        capacity_tariff_kw=50.0  # €/kW/jaar
    )

    cost_engine = CostEngine(cfg)

    # simulate peak_before = 10 kW, peak_after = 6 kW
    res = cost_engine.compute_cost(
        import_profile_kwh=[0],
        export_profile_kwh=[0],
        tariff_type="enkel",
        peak_kw_before=10,
        peak_kw_after=6
    )

    # 4 kW reductie * 50 €/kW/jaar = 200 € besparing
    # Kosten worden NEGATIEF (besparing)
    assert res.total_cost_eur == pytest.approx(
        cfg.vastrecht_year +
        cfg.inverter_power_kw * cfg.inverter_cost_per_kw -
        (4 * 50)
    )


def test_dag_nacht_fallback_single_value():
    """Backward compat: single-value profile gebruikt gemiddelde prijs."""
    cfg = make_tariff(p_dag=0.50, p_nacht=0.30, p_exp_dn=0.08)
    cfg.saldering = False

    cost_engine = CostEngine(cfg)
    res = cost_engine.compute_cost(
        import_profile_kwh=[100],
        export_profile_kwh=[40],
        tariff_type="dag_nacht",
    )
    # Gemiddelde import: 0.40, dus 100*0.40 - 40*0.08 = 40 - 3.20 = 36.80
    expected_energy = 100 * 0.40 - 40 * 0.08
    assert res.total_cost_eur == pytest.approx(
        expected_energy + cfg.vastrecht_year + cfg.inverter_power_kw * cfg.inverter_cost_per_kw
    )


def test_dag_nacht_time_of_use():
    """Time-of-use: nachtimport goedkoper dan dagimport."""
    cfg = make_tariff(p_dag=0.50, p_nacht=0.30, p_exp_dn=0.08)
    cfg.saldering = False

    cost_engine = CostEngine(cfg)

    # 100 kWh alleen 's nachts (uren 23, 0-6) → 8 uur
    # 8760 uur = 365 dagen. Uur 0, 1, 2, 3, 4, 5, 6, 23 = nacht
    # 8 uur per dag * 365 = 2920 nachturen
    # 100 kWh / 2920 = ~0.034 kWh per nachtuur
    night_hours = [0, 1, 2, 3, 4, 5, 6, 23]
    import_profile = [0.0] * 24
    for h in night_hours:
        import_profile[h] = 100 / (8 * 365)
    # Eén dag, herhalen voor 365 dagen
    import_full = import_profile * 365
    export_full = [0.0] * len(import_full)

    res = cost_engine.compute_cost(
        import_profile_kwh=import_full,
        export_profile_kwh=export_full,
        tariff_type="dag_nacht",
        dt_hours=1.0,
    )
    # 100 kWh * 0.30 = 30 € energiekosten
    expected_energy = 100 * 0.30
    assert res.import_kwh == pytest.approx(100.0)
    assert res.total_cost_eur == pytest.approx(
        expected_energy + cfg.vastrecht_year + cfg.inverter_power_kw * cfg.inverter_cost_per_kw
    )

    # 100 kWh alleen overdag (uren 7-22)
    import_profile_day = [0.0] * 24
    for h in range(7, 23):
        import_profile_day[h] = 100 / (16 * 365)
    import_full_day = import_profile_day * 365

    res_day = cost_engine.compute_cost(
        import_profile_kwh=import_full_day,
        export_profile_kwh=export_full,
        tariff_type="dag_nacht",
        dt_hours=1.0,
    )
    expected_energy_day = 100 * 0.50
    assert res_day.total_cost_eur == pytest.approx(
        expected_energy_day + cfg.vastrecht_year + cfg.inverter_power_kw * cfg.inverter_cost_per_kw
    )


def test_dynamisch_saldering_uses_profile_level_netting():
    cfg = make_tariff(
        current_tariff="dynamisch",
        dynamic_prices=[0.20, 0.50],
        p_export_dyn=0.12,
    )
    cost_engine = CostEngine(cfg)

    import_profile = [1.0, 0.0]
    export_profile = [0.0, 1.0]

    cfg.saldering = True
    with_saldering = cost_engine.compute_cost(
        import_profile_kwh=import_profile,
        export_profile_kwh=export_profile,
        tariff_type="dynamisch",
        dt_hours=1.0,
    )

    cfg.saldering = False
    without_saldering = cost_engine.compute_cost(
        import_profile_kwh=import_profile,
        export_profile_kwh=export_profile,
        tariff_type="dynamisch",
        dt_hours=1.0,
    )

    expected_energy_saldering = 1.0 * 0.20
    expected_energy_no_saldering = (1.0 * 0.20) - (1.0 * 0.12)
    fixed = cfg.vastrecht_year + cfg.inverter_power_kw * cfg.inverter_cost_per_kw

    assert with_saldering.total_cost_eur == pytest.approx(expected_energy_saldering + fixed)
    assert without_saldering.total_cost_eur == pytest.approx(expected_energy_no_saldering + fixed)
    assert with_saldering.total_cost_eur > without_saldering.total_cost_eur
