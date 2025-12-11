# battery_engine_pro3/roi_engine.py

from __future__ import annotations
from dataclasses import dataclass
from typing import Optional

from .types import ROIResult


@dataclass
class ROIConfig:
    battery_cost_eur: float
    degradation_per_year: float  # 0–1
    horizon_years: int = 15


class ROIEngine:
    """
    Berekent ROI, totale besparing over levensduur en terugverdientijd.
    """

    def __init__(self, config: ROIConfig) -> None:
        self.cfg = config

    def compute_roi(self, base_saving_per_year_eur: float) -> ROIResult:
        """
        base_saving_per_year_eur = besparing in jaar 1.

        Later nemen we hier batterijdegradatie in mee over meerdere jaren.
        """
        raise NotImplementedError("ROIEngine.compute_roi is not implemented yet")
