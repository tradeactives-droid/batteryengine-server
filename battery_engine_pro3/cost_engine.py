# battery_engine_pro3/cost_engine.py

from __future__ import annotations
from typing import List

from .types import TariffConfig, TariffCode, ScenarioResult


class CostEngine:

    def __init__(self, cfg: TariffConfig) -> None:
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

        total_import_kwh = sum(import_profile_kwh)
        total_export_kwh = sum(export_profile_kwh)

        # ------------------------------------------------------------
        # Energieprijzen
        # ------------------------------------------------------------
        if tariff_type == "enkel":
            cost_energy = total_import_kwh * cfg.p_enkel_imp
            revenue_energy = total_export_kwh * cfg.p_enkel_exp

        elif tariff_type == "dag_nacht":
            avg_price = 0.5 * cfg.p_dag + 0.5 * cfg.p_nacht
            cost_energy = total_import_kwh * avg_price
            revenue_energy = total_export_kwh * cfg.p_exp_dn

        elif tariff_type == "dynamisch":
            if not cfg.dynamic_prices:
                avg_price = cfg.p_enkel_imp
            else:
                avg_price = sum(cfg.dynamic_prices) / len(cfg.dynamic_prices)

            cost_energy = total_import_kwh * avg_price
            revenue_energy = total_export_kwh * cfg.p_export_dyn

        else:
            raise ValueError(f"Unknown tariff type: {tariff_type}")

        # 🔥 FEED-IN ACTIEF → GEEN EXPORT-OPBRENGST
        if cfg.feedin_cost_per_kwh > 0 or cfg.feedin_monthly_cost > 0:
            energy_net = cost_energy
        else:
            energy_net = cost_energy - revenue_energy

        # ------------------------------------------------------------
        # Feed-in kosten
        # ------------------------------------------------------------
        feedin_cost = cfg.feedin_monthly_cost * 12.0
        extra_kwh = max(0.0, total_export_kwh - cfg.feedin_free_kwh)
        feedin_cost += extra_kwh * cfg.feedin_price_after_free

        # ------------------------------------------------------------
        # Omvormer
        # ------------------------------------------------------------
        inverter_cost = cfg.inverter_power_kw * cfg.inverter_cost_per_kw

        # ------------------------------------------------------------
        # Capaciteitstarief BE
        # ------------------------------------------------------------
        if cfg.country == "BE" and peak_kw_before is not None and peak_kw_after is not None:
            capacity_tariff = (peak_kw_after - peak_kw_before) * cfg.capacity_tariff_kw
        else:
            capacity_tariff = 0.0

        # ------------------------------------------------------------
        # Vastrecht
        # ------------------------------------------------------------
        total_cost = (
            energy_net
            + feedin_cost
            + inverter_cost
            + capacity_tariff
            + cfg.vastrecht_year
        )

        return ScenarioResult(
            import_kwh=total_import_kwh,
            export_kwh=total_export_kwh,
            total_cost_eur=total_cost
        )
