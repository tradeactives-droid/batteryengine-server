# battery_engine_pro3/scenario_runner.py

from __future__ import annotations
from dataclasses import dataclass
from typing import Dict

from .types import (
    TimeSeries,
    TariffConfig,
    BatteryConfig,
    ScenarioResult,
    CountryCode,
    TariffCode,
    ROIResult,
    PeakInfo,
)
from .battery_model import BatteryModel
from .battery_simulator import BatterySimulator, SimulationResult
from .cost_engine import CostEngine
from .roi_engine import ROIEngine, ROIConfig


@dataclass
class FullScenarioOutput:
    """
    Outputstructuur voor de frontend: A1 / B1 / C1 + ROI + peaks.
    """
    A1: ScenarioResult
    B1: ScenarioResult
    C1: ScenarioResult
    roi: ROIResult
    peaks: PeakInfo


class ScenarioRunner:
    """
    Orkestreert de simulaties:
    - Bouwt BatteryModel
    - Simuleert no battery / with battery
    - Laat CostEngine rekenen
    - Laat ROIEngine werken
    """

    def __init__(
        self,
        load: TimeSeries,
        pv: TimeSeries,
        tariff_cfg: TariffConfig,
        batt_cfg: BatteryConfig
    ) -> None:
        self.load = load
        self.pv = pv
        self.tariff_cfg = tariff_cfg
        self.batt_cfg = batt_cfg

    def run(self) -> FullScenarioOutput:
        """
        Voert alle scenario's uit (A1, B1, C1) en retourneert samenvatting.
        """
        raise NotImplementedError("ScenarioRunner.run is not implemented yet")
