# battery_engine_pro3/cost_engine.py

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

        # -------------------------
        # ENERGIEKOST
        # -------------------------
        if tariff_type == "enkel":
            energy = imp * self.cfg.p_enkel_imp
        elif tariff_type == "dag_nacht":
            avg = 0.5 * (self.cfg.p_dag + self.cfg.p_nacht)
            energy = imp * avg
        else:
            energy = imp * self.cfg.p_enkel_imp

        # -------------------------
        # FEED-IN KOSTEN (TEST-CONTRACT)
        # -------------------------
        feedin = 0.0

        if exp > 0:
            # vaste kosten
            feedin += self.cfg.feedin_monthly_cost * 12

            # variabele boven drempel
            excess = max(0.0, exp - self.cfg.feedin_free_kwh)
            feedin += excess * self.cfg.feedin_price_after_free

            # ❗ altijd toepassen indien > 0
            if self.cfg.feedin_cost_per_kwh > 0:
                feedin += exp * self.cfg.feedin_cost_per_kwh

        # -------------------------
        # OMVORMER
        # -------------------------
        inverter = self.cfg.inverter_power_kw * self.cfg.inverter_cost_per_kw

        # -------------------------
        # CAPACITEITSTARIEF (BE)
        # -------------------------
        capacity = 0.0
        if self.cfg.country == "BE" and peak_kw_before is not None and peak_kw_after is not None:
            capacity = (peak_kw_after - peak_kw_before) * self.cfg.capacity_tariff_kw

        total = energy + feedin + inverter + capacity + self.cfg.vastrecht_year

        return ScenarioResult(imp, exp, total)
