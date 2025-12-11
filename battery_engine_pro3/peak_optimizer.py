# battery_engine_pro3/peak_optimizer.py

from __future__ import annotations
from dataclasses import dataclass
from typing import List


@dataclass
class PeakOptimizerConfig:
    dt_hours: float
    capacity_tariff_kw_year: float


class PeakOptimizer:
    """
    Optimaliseert maandpieken voor BE-capaciteitstarief.

    In eerste instantie bouwen we een simpele target-peak benadering,
    later kunnen we dit uitbreiden naar een meer geavanceerde strategie.
    """

    def __init__(self, config: PeakOptimizerConfig) -> None:
        self.config = config

    def estimate_target_peaks(
        self,
        net_load_no_batt_kwh: List[float]
    ) -> List[float]:
        """
        Berekent per maand een 'target peak' (in kW) waar de batterij
        op moet gaan sturen.

        TODO: implementeren.
        """
        raise NotImplementedError("PeakOptimizer.estimate_target_peaks is not implemented yet")
