# battery_engine_pro3/roi_engine.py

from __future__ import annotations
from dataclasses import dataclass
from typing import Optional

from .types import ROIResult


@dataclass
class ROIConfig:
    """
    Configuratie voor ROI-berekening.
    """
    battery_cost_eur: float          # totale investering in de batterij
    yearly_saving_eur: float         # besparing in het eerste jaar (€/jaar)
    degradation: float               # jaarlijkse degradatie (bijv. 0.02 = 2%)
    horizon_years: int = 15          # berekenhorizon (standaard 15 jaar)


class ROIEngine:
    """
    Berekent ROI, terugverdientijd en totale besparing over de levensduur.
    """

    @staticmethod
    def compute(cfg: ROIConfig) -> ROIResult:
        """
        Eenvoudig maar realistisch ROI-model:
        - elk jaar daalt de besparing met (1 - degradatie)^(jaar-1)
        - payback = eerste jaar waarin cumulatieve besparing >= investering
        - roi_percent = totale besparing / investering * 100
        """

        # Geen investering of besparing → geen ROI
        if cfg.battery_cost_eur <= 0 or cfg.yearly_saving_eur <= 0:
            return ROIResult(
                yearly_saving_eur=cfg.yearly_saving_eur,
                payback_years=None,
                roi_percent=0.0
            )

        total_savings = 0.0
        payback: Optional[int] = None

        for year in range(1, cfg.horizon_years + 1):
            factor = (1.0 - cfg.degradation) ** (year - 1)
            year_save = cfg.yearly_saving_eur * factor
            total_savings += year_save

            if payback is None and total_savings >= cfg.battery_cost_eur:
                payback = year

        roi_percent = (
            (total_savings - cfg.battery_cost_eur)
            / cfg.battery_cost_eur
        ) * 100.0

        return ROIResult(
            yearly_saving_eur=cfg.yearly_saving_eur,
            payback_years=payback,
            roi_percent=roi_percent
        )
