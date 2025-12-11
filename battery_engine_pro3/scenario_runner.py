# battery_engine_pro3/scenario_runner.py

from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, Optional

from .types import (
    TimeSeries,
    TariffConfig,
    BatteryConfig,
    ScenarioResult,
    ROIResult,
    PeakInfo,
)
from .battery_model import BatteryModel
    # (BatteryModel wordt later gebruikt voor simulate_with_battery)
from .battery_simulator import BatterySimulator
from .cost_engine import CostEngine
from .roi_engine import ROIEngine, ROIConfig


@dataclass
class FullScenarioOutput:
    """
    Structuur voor volledige output:
    - A1 = huidige kosten
    - B1 = toekomst zonder batterij
    - C1 = toekomst met batterij
    - ROI = rendement / terugverdientijd
    - peaks = BE peak shaving info
    """
    A1: ScenarioResult
    B1: Dict[str, ScenarioResult]
    C1: Dict[str, ScenarioResult]
    roi: ROIResult
    peaks: PeakInfo


class ScenarioRunner:
    """
    Voert alle scenario’s uit: A1, B1, C1 en ROI.
    """

    def __init__(
        self,
        load: TimeSeries,
        pv: TimeSeries,
        tariff_cfg: TariffConfig,
        batt_cfg: Optional[BatteryConfig],  # mag None zijn bij scenario's zonder batterij
        roi_cfg: ROIConfig
    ) -> None:
        self.load = load
        self.pv = pv
        self.tariff_cfg = tariff_cfg
        self.batt_cfg = batt_cfg
        self.roi_cfg = roi_cfg

    def run(self) -> FullScenarioOutput:
        """
        Voert A1 / B1 / C1 simulaties uit + ROI + peaks.
        """

        # ----------------------------------
        # INITIALISATIE
        # ----------------------------------
        sim_no_batt = BatterySimulator(self.load, self.pv)
        cost = CostEngine(self.tariff_cfg)

        # ----------------------------------
        # A1: HUIDIGE SITUATIE (zonder batterij)
        # ----------------------------------
        A1_sim = sim_no_batt.simulate_no_battery()
        A1_cost = cost.compute_cost(
            A1_sim.import_profile,
            A1_sim.export_profile,
            self.tariff_cfg.tariff_type
        )

        # ----------------------------------
        # B1: TOEKOMST ZONDER BATTERIJ
        # ----------------------------------
        B1_sim = sim_no_batt.simulate_no_battery()

        B1_costs = {
            "enkel":     cost.compute_cost(B1_sim.import_profile, B1_sim.export_profile, "enkel"),
            "dag_nacht": cost.compute_cost(B1_sim.import_profile, B1_sim.export_profile, "dag_nacht"),
            "dynamisch": cost.compute_cost(B1_sim.import_profile, B1_sim.export_profile, "dynamisch"),
        }

        # ----------------------------------
        # C1: TOEKOMST MET BATTERIJ
        # ----------------------------------
        if self.batt_cfg is None:
            raise ValueError("BatteryConfig is required for scenario C1")

        sim_batt = BatterySimulator(self.load, self.pv, self.batt_cfg)

        # Let op: simulate_with_battery wordt later geïmplementeerd.
        C1_sim = sim_batt.simulate_no_battery()  # tijdelijk; wordt vervangen in stap 7-8

        C1_costs = {
            "enkel":     cost.compute_cost(C1_sim.import_profile, C1_sim.export_profile, "enkel"),
            "dag_nacht": cost.compute_cost(C1_sim.import_profile, C1_sim.export_profile, "dag_nacht"),
            "dynamisch": cost.compute_cost(C1_sim.import_profile, C1_sim.export_profile, "dynamisch"),
        }

        # ----------------------------------
        # ROI-BEREKENING
        # ----------------------------------
        baseline_cost = B1_costs[self.tariff_cfg.tariff_type].total_cost_eur
        with_batt_cost = C1_costs[self.tariff_cfg.tariff_type].total_cost_eur

        roi_engine = ROIEngine(self.roi_cfg)
        roi_info = roi_engine.compute(baseline_cost, with_batt_cost)

        # ----------------------------------
        # PEAKS (BE)
        # ----------------------------------
        if self.tariff_cfg.country == "BE":
            peaks = PeakInfo(monthly_before=[], monthly_after=[])  # placeholder (Stap 7)
        else:
            peaks = PeakInfo(monthly_before=[], monthly_after=[])

        # ----------------------------------
        # RETOURNEER STRUCTUUR
        # ----------------------------------
        return FullScenarioOutput(
            A1=A1_cost,
            B1=B1_costs,
            C1=C1_costs,
            roi=roi_info,
            peaks=peaks
        )
