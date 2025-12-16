# battery_engine_pro3/scenario_runner.py

from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, Optional

from .types import ScenarioResult, PeakInfo, TariffCode, ROIResult
from .battery_simulator import BatterySimulator
from .battery_model import BatteryModel
from .cost_engine import CostEngine
from .peak_optimizer import PeakOptimizer, PeakShavingPlanner
from .roi_engine import ROIEngine, ROIConfig


FullScenarioOutput = Dict[str, object]


class ScenarioRunner:
    """
    Orkestreert alle scenario’s:
    - A1: huidige situatie
    - B1: toekomst zonder batterij
    - C1: toekomst met batterij
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

    def run(self) -> FullScenarioOutput:

        current_tariff = self.tariff_cfg.current_tariff
        
        cost_engine = CostEngine(self.tariff_cfg)

        # =================================================
        # A1 — huidige situatie (geen batterij)
        # =================================================
        sim_no = BatterySimulator(self.load, self.pv, battery=None)
        A1_sim = sim_no.simulate_no_battery()

        self.tariff_cfg.saldering = True

        # A1 per tarief (MET saldering) — nodig voor tariefmatrix
        A1_per_tariff = {
            "enkel": cost_engine.compute_cost(
                A1_sim.import_profile, A1_sim.export_profile, "enkel"
            ),
            "dag_nacht": cost_engine.compute_cost(
                A1_sim.import_profile, A1_sim.export_profile, "dag_nacht"
            ),
            "dynamisch": cost_engine.compute_cost(
                A1_sim.import_profile, A1_sim.export_profile, "dynamisch"
            ),
        }

        # A1 tile blijft gebaseerd op het gekozen tarief uit stap 1
        A1 = A1_per_tariff[self.tariff_cfg.current_tariff]

        # =================================================
        # B1 — toekomst zonder batterij (alle tarieven)
        # =================================================
        self.tariff_cfg.saldering = False
        
        B1 = {
            "enkel": cost_engine.compute_cost(
                A1_sim.import_profile, A1_sim.export_profile, "enkel"
            ),
            "dag_nacht": cost_engine.compute_cost(
                A1_sim.import_profile, A1_sim.export_profile, "dag_nacht"
            ),
            "dynamisch": cost_engine.compute_cost(
                A1_sim.import_profile, A1_sim.export_profile, "dynamisch"
            ),
        }

        # =================================================
        # C1 — toekomst met batterij
        # =================================================
        if self.batt_cfg is None:
            C1 = B1
            peak_info = PeakInfo(monthly_before=[], monthly_after=[])
        else:
            battery_model = BatteryModel(
                E_cap=self.batt_cfg.E,
                P_max=self.batt_cfg.P,
                dod=self.batt_cfg.DoD,
                eta=self.batt_cfg.eta_rt,
            )

            sim_batt = BatterySimulator(self.load, self.pv, battery_model)
            sim_res = sim_batt.simulate_with_battery()

            self.tariff_cfg.saldering = False

            # -----------------------------
            # COST C1 (alle tarieven, ZONDER saldering)
            # -----------------------------
            C1 = {
                "enkel": cost_engine.compute_cost(
                    sim_res.import_profile, sim_res.export_profile, "enkel"
                ),
                "dag_nacht": cost_engine.compute_cost(
                    sim_res.import_profile, sim_res.export_profile, "dag_nacht"
                ),
                "dynamisch": cost_engine.compute_cost(
                    sim_res.import_profile, sim_res.export_profile, "dynamisch"
                ),
            }

            # -----------------------------
            # PEAK SHAVING (alleen BE)
            # -----------------------------
            if self.tariff_cfg.country == "BE":
                monthly_before = PeakOptimizer.compute_monthly_peaks(
                    self.load, self.pv
                )

                targets = PeakOptimizer.compute_monthly_targets(monthly_before)

                monthly_after, _, _, _ = PeakOptimizer.simulate_with_peak_shaving(
                    self.load,
                    self.pv,
                    battery_model,
                    targets
                )

                peak_info = PeakInfo(
                    monthly_before=monthly_before,
                    monthly_after=monthly_after
                )
            else:
                peak_info = PeakInfo(monthly_before=[], monthly_after=[])

        # =================================================
        # ROI (met degradatie) — Optie A
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
                roi_percent=0.0
            )

        return {
            "A1": A1,
            "A1_per_tariff": A1_per_tariff,
            "B1": B1,
            "C1": C1,
            "roi": roi,
            "peaks": peak_info,
        }
