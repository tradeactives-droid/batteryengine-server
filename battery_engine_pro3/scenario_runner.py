# battery_engine_pro3/scenario_runner.py

from __future__ import annotations
from typing import Dict, Optional, List

from .types import ScenarioResult, PeakInfo, ROIResult
from .battery_simulator import BatterySimulator
from .battery_model import BatteryModel
from .cost_engine import CostEngine
from .peak_optimizer import PeakOptimizer
from .roi_engine import ROIEngine, ROIConfig


FullScenarioOutput = Dict[str, object]


class ScenarioRunner:
    """
    Orkestreert alle scenario’s:
    - A1: huidige situatie (met saldering)
    - B1: toekomst zonder batterij (zonder saldering)
    - C1: toekomst met batterij (zonder saldering)
    Inclusief maandelijkse kosten + cumulatieve maand-ROI
    """

    def __init__(
        self,
        load,
        pv,
        tariff_cfg,
        batt_cfg: Optional[object] = None,
    ):
        self.load = load
        self.pv = pv
        self.tariff_cfg = tariff_cfg
        self.batt_cfg = batt_cfg

    # =================================================
    # HELPER — SPLITS TIJDREEKS PER MAAND
    # =================================================
    def split_by_month(self, values: List[float], dt_hours: float) -> List[List[float]]:
        steps_per_day = int(24 / dt_hours)
        days_per_month = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]

        months: List[List[float]] = []
        idx = 0

        for days in days_per_month:
            steps = days * steps_per_day
            months.append(values[idx: idx + steps])
            idx += steps

        return months

    # =================================================
    # MAIN RUNNER
    # =================================================
    def run(self) -> FullScenarioOutput:

        current_tariff = self.tariff_cfg.current_tariff
        cost_engine = CostEngine(self.tariff_cfg)

        # =================================================
        # A1 — huidige situatie (MET saldering)
        # =================================================
        sim_no = BatterySimulator(self.load, self.pv, battery=None)
        A1_sim = sim_no.simulate_no_battery()

        self.tariff_cfg.saldering = True

        A1_per_tariff = {
            tariff: cost_engine.compute_cost(
                A1_sim.import_profile,
                A1_sim.export_profile,
                tariff,
            )
            for tariff in ["enkel", "dag_nacht", "dynamisch"]
        }

        A1 = A1_per_tariff.get(current_tariff, A1_per_tariff["enkel"])

        # =================================================
        # B1 — toekomst zonder batterij (GEEN saldering)
        # =================================================
        self.tariff_cfg.saldering = False

        B1 = {
            tariff: cost_engine.compute_cost(
                A1_sim.import_profile,
                A1_sim.export_profile,
                tariff,
            )
            for tariff in ["enkel", "dag_nacht", "dynamisch"]
        }

        B1_monthly: Dict[str, List[float]] = {}
        for tariff in B1:
            imp_m = self.split_by_month(A1_sim.import_profile, self.load.dt_hours)
            exp_m = self.split_by_month(A1_sim.export_profile, self.load.dt_hours)

            B1_monthly[tariff] = [
                cost_engine.compute_cost(i, e, tariff).total_cost_eur
                for i, e in zip(imp_m, exp_m)
            ]

        # =================================================
        # C1 — toekomst met batterij (GEEN saldering)
        # =================================================
        if self.batt_cfg is None:
            C1 = B1
            C1_monthly = B1_monthly
            peak_info = PeakInfo(monthly_before=[], monthly_after=[])

        else:
            battery_model = BatteryModel(
                E_cap=self.batt_cfg.E,
                P_max=self.batt_cfg.P,
                dod=self.batt_cfg.DoD,
                eta=self.batt_cfg.eta_rt,
            )

            sim_batt = BatterySimulator(
                self.load,
                self.pv,
                battery_model,
                prices_dyn=self.tariff_cfg.dynamic_prices,
            )
            sim_res = sim_batt.simulate_with_battery()

            C1 = {
                tariff: cost_engine.compute_cost(
                    sim_res.import_profile,
                    sim_res.export_profile,
                    tariff,
                )
                for tariff in ["enkel", "dag_nacht", "dynamisch"]
            }

            C1_monthly: Dict[str, List[float]] = {}
            for tariff in C1:
                imp_m = self.split_by_month(sim_res.import_profile, self.load.dt_hours)
                exp_m = self.split_by_month(sim_res.export_profile, self.load.dt_hours)

                C1_monthly[tariff] = [
                    cost_engine.compute_cost(i, e, tariff).total_cost_eur
                    for i, e in zip(imp_m, exp_m)
                ]

            peak_info = PeakInfo(monthly_before=[], monthly_after=[])

        # =================================================
        # STAP 2.2 — CUMULATIEVE MAAND-ROI + PAYBACK
        # =================================================
        roi_monthly: Dict[str, Dict[str, object]] = {}

        if self.batt_cfg is not None:
            investment = self.batt_cfg.investment_eur

            for tariff in ["enkel", "dag_nacht", "dynamisch"]:
                monthly_savings = [
                    b - c
                    for b, c in zip(B1_monthly[tariff], C1_monthly[tariff])
                ]

                cumulative = []
                total = 0.0
                payback_month = None

                for idx, val in enumerate(monthly_savings):
                    total += val
                    cumulative.append(total)
                    if payback_month is None and total >= investment:
                        payback_month = idx + 1  # maanden tellen vanaf 1

                roi_monthly[tariff] = {
                    "monthly_savings": monthly_savings,
                    "cumulative_savings": cumulative,
                    "payback_month": payback_month,
                    "payback_years": (
                        round(payback_month / 12, 1)
                        if payback_month is not None
                        else None
                    ),
                }

        # =================================================
        # ROI — PER TARIEF (nodig voor UI-switch)
        # =================================================
        roi_per_tariff = {}

        if self.batt_cfg is not None:
            for tariff in ["enkel", "dag_nacht", "dynamisch"]:
                yearly_saving = (
                    B1[tariff].total_cost_eur
                    - C1[tariff].total_cost_eur
                )

                roi_per_tariff[tariff] = ROIEngine.compute(
                    ROIConfig(
                        battery_cost_eur=self.batt_cfg.investment_eur,
                        yearly_saving_eur=yearly_saving,
                        degradation=self.batt_cfg.degradation_per_year,
                        horizon_years=self.batt_cfg.lifetime_years,
                    )
                )
        else:
            for tariff in ["enkel", "dag_nacht", "dynamisch"]:
                roi_per_tariff[tariff] = ROIResult(
                    yearly_saving_eur=0.0,
                    payback_years=None,
                    roi_percent=0.0,
                )

        # =================================================
        # ENERGY PROFILE SUMMARY (backend facts for advice)
        # NL-only: gebaseerd op meetdata (load/pv) en basisflows zonder batterij
        # =================================================
        total_load_kwh = sum(self.load.values)
        total_pv_kwh = sum(self.pv.values)

        direct_self_consumption_kwh = 0.0
        pv_export_kwh = 0.0

        for l, p in zip(self.load.values, self.pv.values):
            direct_self_consumption_kwh += min(l, p)
            pv_export_kwh += max(p - l, 0.0)

        # Piekuren op uurniveau (werkt voor uur- en kwartierdata)
        steps_per_hour = int(round(1.0 / self.load.dt_hours))
        hourly_load = [0.0] * 24
        hourly_pv = [0.0] * 24

        for i, (l, p) in enumerate(zip(self.load.values, self.pv.values)):
            hour = int((i / steps_per_hour) % 24)
            hourly_load[hour] += l
            hourly_pv[hour] += p

        peak_load_hour = max(range(24), key=lambda h: hourly_load[h])
        peak_pv_hour = max(range(24), key=lambda h: hourly_pv[h])

        energy_profile = {
            "annual_load_kwh": total_load_kwh,
            "annual_pv_kwh": total_pv_kwh,
            "direct_self_consumption_kwh": direct_self_consumption_kwh,
            "pv_export_kwh": pv_export_kwh,
            "peak_load_hour": peak_load_hour,
            "peak_pv_hour": peak_pv_hour,
        }
        
        return {
            "A1": A1,
            "A1_per_tariff": A1_per_tariff,
            "B1": B1,
            "C1": C1,
            "B1_monthly": B1_monthly,
            "C1_monthly": C1_monthly,
            "roi_per_tariff": roi_per_tariff,
            "peaks": peak_info,
            "energy_profile": energy_profile,
        }
