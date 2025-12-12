# battery_engine_pro3/cost_engine.py

from __future__ import annotations
from dataclasses import dataclass
from typing import List

from .types import TariffConfig, TariffCode, ScenarioResult


@dataclass
class CostBreakdown:
    energy_cost_eur: float
    feedin_fixed_eur_year: float
    feedin_variable_eur_year: float
    inverter_cost_eur_year: float
    capacity_tariff_eur_year: float
    vastrecht_eur_year: float
    total_eur: float


class CostEngine:

    def __init__(self, cfg: TariffConfig):
        self.cfg = cfg

    def compute_cost(
        self,
        import_profile_kwh: List[float],
        export_profile_kwh: List[float],
        tariff_type: TariffCode,
        peak_kw_before: float | None = None,
        peak_kw_after: float | None = None
    ) -> ScenarioResult:

        cfg = self.cfg
        total_import = sum(import_profile_kwh)
        total_export = sum(export_profile_kwh)

        # --------------------------------------------------
        # 1. Energieprijzen
        # --------------------------------------------------
        if tariff_type == "enkel":
            cost_energy = total_import * cfg.p_enkel_imp
            revenue = total_export * cfg.p_enkel_exp

        elif tariff_type == "dag_nacht":
            avg_price = 0.5 * cfg.p_dag + 0.5 * cfg.p_nacht
            cost_energy = total_import * avg_price
            revenue = total_export * cfg.p_exp_dn

        elif tariff_type == "dynamisch":
            prices = cfg.dynamic_prices

            if not prices:
                dyn_avg = cfg.p_enkel_imp
            else:
                dyn_avg = sum(prices) / len(prices)

            cost_energy = total_import * dyn_avg
            revenue = total_export * cfg.p_export_dyn

        else:
            raise ValueError("Unknown tariff type")

        energy_net = cost_energy - revenue

        # --------------------------------------------------
        # 2. Feed-in kosten (volgens tests)
        # --------------------------------------------------
        feedin_fixed = cfg.feedin_monthly_cost * 12

        extra_kwh = max(0.0, total_export - cfg.feedin_free_kwh)
        feedin_var = extra_kwh * cfg.feedin_price_after_free

        feedin_cost = feedin_fixed + feedin_var

        # --------------------------------------------------
        # 3. Omvormerkosten
        # --------------------------------------------------
        inverter_cost = cfg.inverter_power_kw * cfg.inverter_cost_per_kw

        # --------------------------------------------------
        # 4. Capaciteitstarief (BE)
        # --------------------------------------------------
        if cfg.country == "BE" and peak_kw_before is not None and peak_kw_after is not None:
            delta_kw = peak_kw_after - peak_kw_before
            cap_cost = delta_kw * cfg.capacity_tariff_kw
        else:
            cap_cost = 0.0

        # --------------------------------------------------
        # 5. Vastrecht
        # --------------------------------------------------
        vastrecht = cfg.vastrecht_year

        total = energy_net + feedin_cost + inverter_cost + cap_cost + vastrecht

        return ScenarioResult(
            import_kwh=total_import,
            export_kwh=total_export,
            total_cost_eur=total
        )
