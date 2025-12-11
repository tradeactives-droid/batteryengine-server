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
    capacity_tariff_kw=0.0
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

        capacity_tariff_kw=capacity_tariff_kw
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
    expected_extra = 24 + 2

    assert res.total_cost_eur == pytest.approx(
        cfg.vastrecht_year + cfg.inverter_power_kw * cfg.inverter_cost_per_kw + expected_extra
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
