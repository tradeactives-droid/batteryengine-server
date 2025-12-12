# battery_engine_pro3/cost_engine.py

from __future__ import annotations
from dataclasses import dataclass
from typing import List
from .types import TariffConfig, ScenarioResult


class CostEngine:

    def __init__(self, cfg: TariffConfig):
        self.cfg = cfg

    def compute_cost(
        self,
        import_profile_kwh: List[float],
        export_profile_kwh: List[float],
        tariff_type: str,
        peak_kw_before=None,
        peak_kw_after=None
    ) -> ScenarioResult:

        imp = sum(import_profile_kwh)
        exp = sum(export_profile_kwh)

        if tariff_type == "enkel":
            energy = imp * self.cfg.p_enkel_imp - exp * self.cfg.p_enkel_exp
        else:
            energy = imp * self.cfg.p_enkel_imp

        feedin = self.cfg.feedin_monthly_cost * 12
        extra = max(0, exp - self.cfg.feedin_free_kwh)
        feedin += extra * self.cfg.feedin_price_after_free

        inverter = self.cfg.inverter_power_kw * self.cfg.inverter_cost_per_kw
        capacity = 0

        if self.cfg.country == "BE" and peak_kw_before is not None:
            capacity = (peak_kw_after - peak_kw_before) * self.cfg.capacity_tariff_kw

        total = energy + feedin + inverter + self.cfg.vastrecht_year + capacity

        return ScenarioResult(
            import_kwh=imp,
            export_kwh=exp,
            total_cost_eur=total
        )
