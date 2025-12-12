# battery_engine_pro3/scenario_runner.py

from dataclasses import dataclass
from typing import Dict
from .battery_simulator import BatterySimulator
from .cost_engine import CostEngine
from .peak_optimizer import PeakOptimizer
from .types import ScenarioResult


@dataclass
class PeakInfo:
    monthly_before: list
    monthly_after: list


class ScenarioRunner:

    def __init__(self, load, pv, tariff_cfg, batt_cfg):
        self.load = load
        self.pv = pv
        self.tariff_cfg = tariff_cfg
        self.batt_cfg = batt_cfg

    def run(self):
        sim = BatterySimulator(self.load, self.pv, None)
        base = sim.simulate_no_battery()
        cost_engine = CostEngine(self.tariff_cfg)

        A1 = cost_engine.compute_cost(base.import_profile, base.export_profile, self.tariff_cfg.current_tariff)

        return {
            "A1": A1,
            "B1": A1,
            "C1": A1,
            "roi": 0.0,
            "peaks": PeakInfo([0]*12, [0]*12)
        }
