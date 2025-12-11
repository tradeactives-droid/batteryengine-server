# battery_engine_pro3/cost_engine.py

from __future__ import annotations
from dataclasses import dataclass
from typing import List

from .types import TariffConfig, TariffCode, CountryCode, ScenarioResult


@dataclass
class CostBreakdown:
    """Optionele uitsplitsing voor debug / diagnostiek."""
    energy_cost_eur: float
    feedin_fixed_eur_year: float
    feedin_variable_eur_year: float
    inverter_cost_eur_year: float
    capacity_tariff_eur_year: float
    vastrecht_eur_year: float

    total_eur: float


class CostEngine:
    """
    Centrale kostencalculator voor alle scenario's en landen.
    """

    def __init__(self, tariff_config: TariffConfig) -> None:
        self.cfg = tariff_config

    def compute_cost(
        self,
        import_profile_kwh: List[float],
        export_profile_kwh: List[float],
        tariff_type: TariffCode
    ) -> ScenarioResult:
        """
        Bereken totale kosten (per jaar) voor een gegeven import/export profiel
        onder een bepaald tarief.

        TODO: implementatie van:
        - import * prijs
        - export * feed-in
        - feed-in vaste kosten
        - staffel
        - omvormer
        - capaciteitstarief (BE)
        - vastrecht
        """
        raise NotImplementedError("CostEngine.compute_cost is not implemented yet")
