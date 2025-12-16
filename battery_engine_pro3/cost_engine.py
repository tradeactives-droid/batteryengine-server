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
        # ENERGIEKOSTEN
        # -------------------------

        # ENKEL
        if tariff_type == "enkel":
            import_price = self.cfg.p_enkel_imp
            export_price = self.cfg.p_enkel_exp

            if self.cfg.saldering:
                net_import = max(imp - exp, 0.0)
                energy = net_import * import_price
            else:
                energy = (imp * import_price) - (exp * export_price)

        # DAG/NACHT (simpel gemiddelde)
        elif tariff_type == "dag_nacht":
            import_price = 0.5 * (self.cfg.p_dag + self.cfg.p_nacht)
            export_price = self.cfg.p_exp_dn

            if self.cfg.saldering:
                net_import = max(imp - exp, 0.0)
                energy = net_import * import_price
            else:
                energy = (imp * import_price) - (exp * export_price)

        # DYNAMISCH (uurtarieven)
        elif tariff_type == "dynamisch":
            export_price = self.cfg.p_export_dyn

            dyn = getattr(self.cfg, "dynamic_prices", None) or []
            if len(dyn) == 0:
                raise ValueError("Dynamisch tarief: dynamic_prices ontbreekt of is leeg.")
            if len(dyn) < len(import_profile_kwh):
                raise ValueError(
                    f"Dynamisch tarief: dynamic_prices te kort ({len(dyn)}) voor profiel ({len(import_profile_kwh)})."
                )

            if self.cfg.saldering:
                # Per tijdstap salderen: net import = max(import - export, 0)
                energy = sum(
                    max(imp_kwh - exp_kwh, 0.0) * price
                    for imp_kwh, exp_kwh, price in zip(import_profile_kwh, export_profile_kwh, dyn)
                )
            else:
                # Geen saldering: import tegen uurprijs, export tegen vaste vergoeding
                import_cost = sum(imp_kwh * price for imp_kwh, price in zip(import_profile_kwh, dyn))
                export_revenue = exp * export_price
                energy = import_cost - export_revenue

        else:
            raise ValueError(f"Onbekend tarieftype: {tariff_type}")

        # -------------------------
        # FEED-IN KOSTEN
        # -------------------------
        feedin = 0.0
        if not self.cfg.saldering and exp > 0:
            feedin += self.cfg.feedin_monthly_cost * 12
            excess = max(0.0, exp - self.cfg.feedin_free_kwh)
            feedin += excess * self.cfg.feedin_price_after_free

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
