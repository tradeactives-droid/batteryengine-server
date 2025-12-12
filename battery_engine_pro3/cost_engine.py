from __future__ import annotations
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
        peak_kw_before: float | None = None,
        peak_kw_after: float | None = None
    ) -> ScenarioResult:

        imp = sum(import_profile_kwh)
        exp = sum(export_profile_kwh)

        if tariff_type == "enkel":
            energy = imp * self.cfg.p_enkel_imp
        elif tariff_type == "dag_nacht":
            avg = 0.5 * (self.cfg.p_dag + self.cfg.p_nacht)
            energy = imp * avg
        else:
            price = self.cfg.p_enkel_imp
            energy = imp * price

        feedin = 0.0

        if exp > 0:
            feedin = self.cfg.feedin_monthly_cost * 12
            excess = max(0.0, exp - self.cfg.feedin_free_kwh)
            feedin += excess * self.cfg.feedin_price_after_free

        inverter = self.cfg.inverter_power_kw * self.cfg.inverter_cost_per_kw

        capacity = 0.0
        if self.cfg.country == "BE" and peak_kw_before is not None and peak_kw_after is not None:
            capacity = (peak_kw_after - peak_kw_before) * self.cfg.capacity_tariff_kw

        total = energy + feedin + inverter + capacity + self.cfg.vastrecht_year

        return ScenarioResult(imp, exp, total)
