# battery_engine_pro3/scenario_runner.py

from __future__ import annotations
from typing import Dict, Optional

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
    def split_by_month(self, values, dt_hours):
        """
        Splitst een tijdreeks in 12 maanden.
        Aannames:
        - start op 1 januari
        - dt_hours constant (bijv. 0.25)
        """
        steps_per_day = int(24 / dt_hours)
        days_per_month = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]

        months = []
        idx = 0

        for days in days_per_month:
            steps = days * steps_per_day
            months.append(values[idx : idx + steps])
            idx += steps

        return months

    # =================================================
    # MAIN RUNNER
    # =================================================
    def run(self) -> FullScenarioOutput:

        current_tariff = self.tariff_cfg.current_tariff
        cost_engine = CostEngine(self.tariff_cfg)

        # =================================================
        # A1 — huidige situatie (GEEN batterij, MET saldering)
        # =================================================
        sim_no = BatterySimulator(self.load, self.pv, battery=None)
        A1_sim = sim_no.simulate_no_battery()

        self.tariff_cfg.saldering = True

        A1_per_tariff = {
            "enkel": cost_engine.compute_cost(
                A1_sim.import_profile,
                A1_sim.export_profile,
                "enkel",
            ),
            "dag_nacht": cost_engine.compute_cost(
                A1_sim.import_profile,
                A1_sim.export_profile,
                "dag_nacht",
            ),
            "dynamisch": cost_engine.compute_cost(
                A1_sim.import_profile,
                A1_sim.export_profile,
                "dynamisch",
            ),
        }

        A1 = A1_per_tariff[current_tariff]

        # =================================================
        # B1 — toekomst zonder batterij (GEEN saldering)
        # =================================================
        self.tariff_cfg.saldering = False

        B1 = {
            "enkel": cost_engine.compute_cost(
                A1_sim.import_profile,
                A1_sim.export_profile,
                "enkel",
            ),
            "dag_nacht": cost_engine.compute_cost(
                A1_sim.import_profile,
                A1_sim.export_profile,
                "dag_nacht",
            ),
            "dynamisch": cost_engine.compute_cost(
                A1_sim.import_profile,
                A1_sim.export_profile,
                "dynamisch",
            ),
        }

        # --- B1 maandelijkse kosten ---
        B1_monthly = {}

        for tariff in B1.keys():
            imp_months = self.split_by_month(
                A1_sim.import_profile, self.load.dt_hours
            )
            exp_months = self.split_by_month(
                A1_sim.export_profile, self.load.dt_hours
            )

            monthly_costs = []
            for imp_m, exp_m in zip(imp_months, exp_months):
                monthly_costs.append(
                    cost_engine.compute_cost(
                        imp_m,
                        exp_m,
                        tariff,
                    ).total_cost_eur
                )

            B1_monthly[tariff] = monthly_costs

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

            self.tariff_cfg.saldering = False

            C1 = {
                "enkel": cost_engine.compute_cost(
                    sim_res.import_profile,
                    sim_res.export_profile,
                    "enkel",
                ),
                "dag_nacht": cost_engine.compute_cost(
                    sim_res.import_profile,
                    sim_res.export_profile,
                    "dag_nacht",
                ),
                "dynamisch": cost_engine.compute_cost(
                    sim_res.import_profile,
                    sim_res.export_profile,
                    "dynamisch",
                ),
            }

            # --- C1 maandelijkse kosten ---
            C1_monthly = {}

            for tariff in C1.keys():
                imp_months = self.split_by_month(
                    sim_res.import_profile, self.load.dt_hours
                )
                exp_months = self.split_by_month(
                    sim_res.export_profile, self.load.dt_hours
                )

                monthly_costs = []
                for imp_m, exp_m in zip(imp_months, exp_months):
                    monthly_costs.append(
                        cost_engine.compute_cost(
                            imp_m,
                            exp_m,
                            tariff,
                        ).total_cost_eur
                    )

                C1_monthly[tariff] = monthly_costs

            # Peak shaving alleen voor BE
            if self.tariff_cfg.country == "BE":
                monthly_before = PeakOptimizer.compute_monthly_peaks(
                    self.load, self.pv
                )
                targets = PeakOptimizer.compute_monthly_targets(monthly_before)

                monthly_after, _, _, _ = PeakOptimizer.simulate_with_peak_shaving(
                    self.load,
                    self.pv,
                    battery_model,
                    targets,
                )

                peak_info = PeakInfo(
                    monthly_before=monthly_before,
                    monthly_after=monthly_after,
                )
            else:
                peak_info = PeakInfo(monthly_before=[], monthly_after=[])

        # =================================================
        # ROI — NOG STEEDS JAARLIJKS (volgende stap = maand-ROI)
        # =================================================
        if self.batt_cfg is not None:
            if current_tariff not in C1:
                current_tariff = "enkel"

            yearly_saving = (
                B1[current_tariff].total_cost_eur
                - C1[current_tariff].total_cost_eur
            )

            roi = ROIEngine.compute(
                ROIConfig(
                    battery_cost_eur=self.batt_cfg.investment_eur,
                    yearly_saving_eur=yearly_saving,
                    degradation=self.batt_cfg.degradation_per_year,
                    horizon_years=self.batt_cfg.lifetime_years,
                )
            )
        else:
            roi = ROIResult(
                yearly_saving_eur=0.0,
                payback_years=None,
                roi_percent=0.0,
            )

        return {
            "A1": A1,
            "A1_per_tariff": A1_per_tariff,
            "B1": B1,
            "C1": C1,
            "B1_monthly": B1_monthly,
            "C1_monthly": C1_monthly,
            "roi": roi,
            "peaks": peak_info,
        }
