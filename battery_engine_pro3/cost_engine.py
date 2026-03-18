# battery_engine_pro3/cost_engine.py

from __future__ import annotations
from typing import List
from .types import TariffConfig, ScenarioResult


def _is_night_hour(hour: int, night_start: int, night_end: int) -> bool:
    """
    Bepaal of een uur van de dag onder nachttarief valt.
    NL: 23:00-07:00 → hours 23, 0, 1, 2, 3, 4, 5, 6
    """
    if night_start > night_end:
        return night_start <= hour or hour < night_end
    return night_start <= hour < night_end


class CostEngine:
    def __init__(self, cfg: TariffConfig):
        self.cfg = cfg

    def _compute_dag_nacht_energy(
        self,
        import_profile_kwh: List[float],
        export_profile_kwh: List[float],
        dt_hours: float | None,
    ) -> float:
        """
        Berekent energiekosten voor dag/nacht met time-of-use.
        Import: p_dag overdag (07:00-23:00), p_nacht 's nachts (23:00-07:00).
        Export: p_exp_dn (meeste NL tarieven hebben één terugleverprijs).
        """
        ns = getattr(self.cfg, "night_start_hour", 23)
        ne = getattr(self.cfg, "night_end_hour", 7)

        if (
            dt_hours is None
            or len(import_profile_kwh) <= 1
            or len(export_profile_kwh) <= 1
        ):
            avg_import = 0.5 * (self.cfg.p_dag + self.cfg.p_nacht)
            if self.cfg.saldering:
                net = max(sum(import_profile_kwh) - sum(export_profile_kwh), 0.0)
                return net * avg_import
            return (
                sum(import_profile_kwh) * avg_import
                - sum(export_profile_kwh) * self.cfg.p_exp_dn
            )

        n = min(len(import_profile_kwh), len(export_profile_kwh))
        energy = 0.0

        for i in range(n):
            hour = int(i * dt_hours) % 24
            is_night = _is_night_hour(hour, ns, ne)
            p_imp = self.cfg.p_nacht if is_night else self.cfg.p_dag

            imp_i = import_profile_kwh[i]
            exp_i = export_profile_kwh[i] if i < len(export_profile_kwh) else 0.0

            if self.cfg.saldering:
                net_i = max(0.0, imp_i - exp_i)
                energy += net_i * p_imp
            else:
                energy += imp_i * p_imp - exp_i * self.cfg.p_exp_dn

        return energy

    def compute_cost(
        self,
        import_profile_kwh: List[float],
        export_profile_kwh: List[float],
        tariff_type: str,
        peak_kw_before: float | None = None,
        peak_kw_after: float | None = None,
        dt_hours: float | None = None,
    ) -> ScenarioResult:

        imp = sum(import_profile_kwh)
        exp = sum(export_profile_kwh)

        # -------------------------
        # ENERGIEKOSTEN
        # -------------------------
        if tariff_type == "enkel":
            import_price = self.cfg.p_enkel_imp
            export_price = self.cfg.p_enkel_exp

            if self.cfg.saldering:
                net_import = max(imp - exp, 0.0)
                energy = net_import * import_price
            else:
                energy = (imp * import_price) - (exp * export_price)

        elif tariff_type == "dag_nacht":
            energy = self._compute_dag_nacht_energy(
                import_profile_kwh,
                export_profile_kwh,
                dt_hours,
            )

        elif tariff_type == "dynamisch":
            export_price = self.cfg.p_export_dyn

            dyn = getattr(self.cfg, "dynamic_prices", None) or []
            if len(dyn) == 0:
                raise ValueError("Dynamisch tarief: dynamic_prices ontbreekt of is leeg.")

            if len(dyn) < len(import_profile_kwh):
                raise ValueError(
                    f"Dynamisch tarief: dynamic_prices te kort ({len(dyn)}) voor profiel ({len(import_profile_kwh)})."
                )

            import_cost = sum(
                imp_kwh * price
                for imp_kwh, price in zip(import_profile_kwh, dyn)
            )

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
