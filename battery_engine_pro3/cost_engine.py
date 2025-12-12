# battery_engine_pro3/cost_engine.py

from __future__ import annotations
from dataclasses import dataclass
from typing import List

from .types import TariffConfig, TariffCode, CountryCode, ScenarioResult


@dataclass
class CostBreakdown:
    """Optionele uitsplitsing voor debug / diagnostiek."""
    energy_cost_eur: float
    feedin_fixed_eur_year: float
    feedin_variable_eur_year: float
    inverter_cost_eur_year: float
    capacity_tariff_eur_year: float
    vastrecht_eur_year: float

    total_eur: float


class CostEngine:
    """
    Centrale kostencalculator voor alle scenario's en landen.
    """

    def __init__(self, tariff_config: TariffConfig) -> None:
        self.cfg = tariff_config

    def compute_cost(
        self,
        import_profile_kwh: List[float],
        export_profile_kwh: List[float],
        tariff_type: TariffCode,
        peak_kw_before: float | None = None,
        peak_kw_after: float | None = None
    ) -> ScenarioResult:
        """
        Bereken totale kosten (per jaar) voor een gegeven import/export profiel
        + optioneel capaciteitstarief (BE).
        """

        cfg = self.cfg
        country = cfg.country
        total_import_kwh = sum(import_profile_kwh)
        total_export_kwh = sum(export_profile_kwh)

        # -------------------------------
        # 1. Energieprijzen
        # -------------------------------
        if tariff_type == "enkel":
            cost_energy = total_import_kwh * cfg.p_enkel_imp
            revenue_energy = total_export_kwh * cfg.p_enkel_exp

        elif tariff_type == "dag_nacht":
            avg_price = 0.5 * cfg.p_dag + 0.5 * cfg.p_nacht
            cost_energy = total_import_kwh * avg_price
            revenue_energy = total_export_kwh * cfg.p_exp_dn

        elif tariff_type == "dynamisch":
            prices = cfg.dynamic_prices

            # Fallback wanneer er GEEN dynamische prijzen zijn (tests eisen dit)
            if prices is None or len(prices) == 0:
                # Gebruik vaste importprijs als fallback
                dyn_price_avg = cfg.p_enkel_imp
            else:
                dyn_price_avg = sum(prices) / len(prices)

    cost_energy = total_import_kwh * dyn_price_avg
    revenue_energy = total_export_kwh * cfg.p_export_dyn
            cost_energy = total_import_kwh * dyn_price_avg
            revenue_energy = total_export_kwh * cfg.p_export_dyn

        else:
            raise ValueError(f"Unknown tariff type: {tariff_type}")

        energy_net = cost_energy - revenue_energy

        # -------------------------------
        # 2. Feed-in kosten
        # -------------------------------
        feedin_cost = 0.0

        # 1) vaste kosten
        feedin_cost += cfg.feedin_monthly_cost * 12.0

        # 2) variabele kosten (alleen boven gratis drempel)
        extra_kwh = max(0.0, total_export_kwh - cfg.feedin_free_kwh)
        feedin_cost += extra_kwh * cfg.feedin_price_after_free

        # -------------------------------
        # 3. Omvormerkosten
        # -------------------------------
        inverter_cost = cfg.inverter_power_kw * cfg.inverter_cost_per_kw

        # -------------------------------
        # 4. Capaciteitstarief BE
        # -------------------------------
        if country == "BE" and peak_kw_before is not None and peak_kw_after is not None:
            delta_kw = peak_kw_after - peak_kw_before
            capacity_tariff = delta_kw * cfg.capacity_tariff_kw
        else:
            capacity_tariff = 0.0

        # -------------------------------
        # 5. Vastrecht
        # -------------------------------
        vastrecht_year = cfg.vastrecht_year

        # -------------------------------
        # 6. Totale kosten
        # -------------------------------
        total_cost = (
            energy_net
            + feedin_var
            + feedin_fixed_year
            + inverter_cost
            + capacity_tariff
            + vastrecht_year
        )

        return ScenarioResult(
            import_kwh=total_import_kwh,
            export_kwh=total_export_kwh,
            total_cost_eur=total_cost,
        )
