# battery_engine_pro3/scenario_runner.py

from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, List

from .types import (
    TimeSeries,
    TariffConfig,
    BatteryConfig,
    ScenarioResult,
    PeakInfo,
)
from .battery_model import BatteryModel
from .battery_simulator import BatterySimulator
from .cost_engine import CostEngine
from .peak_optimizer import PeakOptimizer, PeakShavingPlanner
from .roi_engine import ROIEngine, ROIConfig


class ScenarioRunner:

    def __init__(
        self,
        load: TimeSeries,
        pv: TimeSeries,
        tariff_cfg: TariffConfig,
        batt_cfg: BatteryConfig | None
    ) -> None:
        self.load = load
        self.pv = pv
        self.tariff_cfg = tariff_cfg
        self.batt_cfg = batt_cfg

    # ------------------------------------------------------------
    def _build_battery_model(self) -> BatteryModel:
        # 🔥 START LEEG → nodig voor tests + realistisch
        return BatteryModel(
            E_cap=self.batt_cfg.E,
            P_max=self.batt_cfg.P,
            dod=self.batt_cfg.DoD,
            eta=self.batt_cfg.eta_rt,
            initial_soc_frac=0.0
        )

    # ------------------------------------------------------------
    def run(self) -> Dict:

        tariff = self.tariff_cfg
        country = tariff.country
        cost_engine = CostEngine(tariff)

        # --------------------------------------------------------
        # A1 — Huidige situatie
        # --------------------------------------------------------
        sim_no = BatterySimulator(self.load, self.pv, battery=None)
        A1_sim = sim_no.simulate_no_battery()

        A1_cost = cost_engine.compute_cost(
            A1_sim.import_profile,
            A1_sim.export_profile,
            tariff.current_tariff
        )

        # --------------------------------------------------------
        # B1 — Toekomst zonder batterij
        # --------------------------------------------------------
        B1_sim = sim_no.simulate_no_battery()

        B1_costs = {
            "enkel": cost_engine.compute_cost(B1_sim.import_profile, B1_sim.export_profile, "enkel"),
            "dag_nacht": cost_engine.compute_cost(B1_sim.import_profile, B1_sim.export_profile, "dag_nacht"),
            "dynamisch": cost_engine.compute_cost(B1_sim.import_profile, B1_sim.export_profile, "dynamisch"),
        }

        # --------------------------------------------------------
        # C1 — Met batterij
        # --------------------------------------------------------
        if self.batt_cfg is None:
            C1_costs = B1_costs.copy()
            peak_info = PeakInfo(monthly_before=[], monthly_after=[])

        else:
            battery_model = self._build_battery_model()

            # ---------------- NL ----------------
            if country == "NL":
                sim_batt = BatterySimulator(self.load, self.pv, battery_model)
                C1_sim = sim_batt.simulate_with_battery()

                C1_costs = {
                    "enkel": cost_engine.compute_cost(C1_sim.import_profile, C1_sim.export_profile, "enkel"),
                    "dag_nacht": cost_engine.compute_cost(C1_sim.import_profile, C1_sim.export_profile, "dag_nacht"),
                    "dynamisch": cost_engine.compute_cost(C1_sim.import_profile, C1_sim.export_profile, "dynamisch"),
                }

                peak_info = PeakInfo(monthly_before=[], monthly_after=[])

            # ---------------- BE ----------------
            else:
                baseline_peaks = PeakOptimizer.compute_monthly_peaks(self.load, self.pv)
                monthly_targets = PeakOptimizer.compute_monthly_targets(baseline_peaks, 0.85)

                soc_plan = PeakShavingPlanner.plan_monthly_soc_targets(
                    self.load, self.pv, battery_model,
                    baseline_peaks, monthly_targets
                )

                new_peaks, imp, exp, soc = PeakOptimizer.simulate_with_peak_shaving(
                    self.load, self.pv, battery_model,
                    monthly_targets, soc_plan
                )

                C1_costs = {
                    "enkel": cost_engine.compute_cost(
                        imp, exp, "enkel",
                        peak_kw_before=max(baseline_peaks),
                        peak_kw_after=max(new_peaks)
                    ),
                    "dag_nacht": cost_engine.compute_cost(
                        imp, exp, "dag_nacht",
                        peak_kw_before=max(baseline_peaks),
                        peak_kw_after=max(new_peaks)
                    ),
                    "dynamisch": cost_engine.compute_cost(
                        imp, exp, "dynamisch",
                        peak_kw_before=max(baseline_peaks),
                        peak_kw_after=max(new_peaks)
                    ),
                }

                peak_info = PeakInfo(
                    monthly_before=baseline_peaks,
                    monthly_after=new_peaks
                )

        # --------------------------------------------------------
        # ROI (correct object)
        # --------------------------------------------------------
        baseline_cost = B1_costs[tariff.current_tariff].total_cost_eur
        with_batt_cost = C1_costs[tariff.current_tariff].total_cost_eur
        yearly_saving = baseline_cost - with_batt_cost

        if self.batt_cfg and self.batt_cfg.investment_eur > 0:
            roi_cfg = ROIConfig(
                battery_cost_eur=self.batt_cfg.investment_eur,
                yearly_saving_eur=yearly_saving,
                degradation=self.batt_cfg.degradation
            )
            roi_result = ROIEngine.compute(roi_cfg)
        else:
            roi_result = ROIEngine.compute(
                ROIConfig(0, 0, 0)
            )

        # --------------------------------------------------------
        # ✅ DICT RETURN (tests + API)
        # --------------------------------------------------------
        return {
            "A1": A1_cost,
            "B1": B1_costs,
            "C1": C1_costs,
            "roi": roi_result,
            "peaks": peak_info,
        }
