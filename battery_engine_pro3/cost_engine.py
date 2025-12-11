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
        onder een bepaald tarief.

        TODO: implementatie van:
        - import * prijs
        - export * feed-in
        - feed-in vaste kosten
        - staffel
        - omvormer
        - capaciteitstarief (BE)
        - vastrecht
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
            # Baseline benadering — later uitbreiden op timestamps
            avg_price = 0.5 * cfg.p_dag + 0.5 * cfg.p_nacht
            cost_energy = total_import_kwh * avg_price
            revenue_energy = total_export_kwh * cfg.p_exp_dn

        elif tariff_type == "dynamisch":
            if cfg.dynamic_prices is None:
                raise ValueError("Dynamic tariff selected but dynamic_prices missing")

            dyn_price_avg = sum(cfg.dynamic_prices) / len(cfg.dynamic_prices)
            cost_energy = total_import_kwh * dyn_price_avg
            revenue_energy = total_export_kwh * cfg.p_export_dyn

        else:
            raise ValueError(f"Unknown tariff type: {tariff_type}")

        energy_net = cost_energy - revenue_energy

        # -------------------------------
        # 2. Feed-in kosten
        # -------------------------------
        feedin_fixed_year = cfg.feedin_monthly_cost * 12.0

        feedin_var = 0.0
        if cfg.feedin_cost_per_kwh > 0:
            overage = max(0.0, total_export_kwh - cfg.feedin_free_kwh)
            feedin_var = overage * cfg.feedin_price_after_free

        # -------------------------------
        # 3. Omvormerkosten
        # -------------------------------
        # LET OP — correcte variabele naam
        inverter_cost = cfg.inverter_power_kw * cfg.inverter_cost_per_kw

        # -------------------------------
        # 4. Capaciteitstarief (BE)
        # Wordt later overschreven door PeakEngine
        # -------------------------------
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
