# battery_engine_pro3/cost_engine.py

from __future__ import annotations
from dataclasses import dataclass
from typing import List

from .types import TariffConfig, TariffCode, ScenarioResult


class CostEngine:
    """
    Centrale kostencalculator voor alle scenario's.
    Inclusief:
    - NL/BE tariefstructuren
    - feed-in kosten (testspecificatie)
    - capaciteitstarief BE
    """

    def __init__(self, cfg: TariffConfig) -> None:
        self.cfg = cfg

    # ============================================================
    # HOOFDREKENING
    # ============================================================
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
        # 1. Energieprijzen
        # ------------------------------------------------------------
        if tariff_type == "enkel":
            cost_energy = total_import_kwh * cfg.p_enkel_imp
            revenue_energy = total_export_kwh * cfg.p_enkel_exp

        elif tariff_type == "dag_nacht":
            average_price = 0.5 * cfg.p_dag + 0.5 * cfg.p_nacht
            cost_energy = total_import_kwh * average_price
            revenue_energy = total_export_kwh * cfg.p_exp_dn

        elif tariff_type == "dynamisch":
            prices = cfg.dynamic_prices

            # fallback volgens tests → gebruik enkel tarief als dynamische prijzen ontbreken
            if prices is None or len(prices) == 0:
                dyn_price_avg = cfg.p_enkel_imp
            else:
                dyn_price_avg = sum(prices) / len(prices)

            cost_energy = total_import_kwh * dyn_price_avg
            revenue_energy = total_export_kwh * cfg.p_export_dyn

        else:
            raise ValueError(f"Unknown tariff type: {tariff_type}")

        # netto energie (kosten - opbrengsten)
        energy_net = cost_energy - revenue_energy

        # ------------------------------------------------------------
        # 2. FEED-IN KOSTEN  ✔ testspecificatie
        # ------------------------------------------------------------
        # vaste kosten / jaar
        feedin_cost = cfg.feedin_monthly_cost * 12.0

        # variabele kosten (alleen boven drempel)
        extra_kwh = max(0.0, total_export_kwh - cfg.feedin_free_kwh)
        feedin_cost += extra_kwh * cfg.feedin_price_after_free

        # ------------------------------------------------------------
        # 3. OMVORMERKOST (€/kW * kW)
        # ------------------------------------------------------------
        inverter_cost = cfg.inverter_power_kw * cfg.inverter_cost_per_kw

        # ------------------------------------------------------------
        # 4. CAPACITEITSTARIEF BE
        # ------------------------------------------------------------
        if cfg.country == "BE" and peak_kw_before is not None and peak_kw_after is not None:
            # delta kw = nieuwe piek - oude piek
            delta_kw = peak_kw_after - peak_kw_before
            capacity_tariff = delta_kw * cfg.capacity_tariff_kw
        else:
            capacity_tariff = 0.0

        # ------------------------------------------------------------
        # 5. VASTRECHT
        # ------------------------------------------------------------
        vastrecht = cfg.vastrecht_year

        # ------------------------------------------------------------
        # 6. EINDTOTAAL
        # ------------------------------------------------------------
        total_cost = (
            energy_net
            + feedin_cost
            + inverter_cost
            + capacity_tariff
            + vastrecht
        )

        # Output必须 ScenarioResult object (tests vereisen dit)
        return ScenarioResult(
            import_kwh=total_import_kwh,
            export_kwh=total_export_kwh,
            total_cost_eur=total_cost
        )
