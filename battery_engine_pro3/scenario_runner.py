from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, List

from .types import TimeSeries, TariffConfig, BatteryConfig, ScenarioResult, PeakInfo
from .battery_model import BatteryModel
from .battery_simulator import BatterySimulator
from .cost_engine import CostEngine
from .peak_optimizer import PeakOptimizer


@dataclass
class FullScenarioOutput:
    A1: ScenarioResult
    B1: Dict[str, ScenarioResult]
    C1: Dict[str, ScenarioResult]
    roi: float
    peaks: PeakInfo


class ScenarioRunner:

    def __init__(self, load, pv, tariff_cfg, batt_cfg):
        self.load = load
        self.pv = pv
        self.tariff_cfg = tariff_cfg
        self.batt_cfg = batt_cfg

    def run(self) -> FullScenarioOutput:
        cost = CostEngine(self.tariff_cfg)

        sim_no = BatterySimulator(self.load, self.pv, None).simulate_no_battery()
        A1 = cost.compute_cost(sim_no.import_profile, sim_no.export_profile, self.tariff_cfg.current_tariff)

        B1 = {
            t: cost.compute_cost(sim_no.import_profile, sim_no.export_profile, t)
            for t in ["enkel", "dag_nacht", "dynamisch"]
        }

        battery = BatteryModel(
            self.batt_cfg.E,
            self.batt_cfg.P,
            self.batt_cfg.DoD,
            self.batt_cfg.eta_rt
        )

        sim_batt = BatterySimulator(self.load, self.pv, battery).simulate_with_battery()

        C1 = {
            t: cost.compute_cost(sim_batt.import_profile, sim_batt.export_profile, t)
            for t in ["enkel", "dag_nacht", "dynamisch"]
        }

        peaks = PeakInfo([], [])

        roi = (B1[self.tariff_cfg.current_tariff].total_cost_eur -
               C1[self.tariff_cfg.current_tariff].total_cost_eur) / self.batt_cfg.investment_eur

        return FullScenarioOutput(A1, B1, C1, roi, peaks)
