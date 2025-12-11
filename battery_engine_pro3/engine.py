# battery_engine_pro3/engine.py

from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, Any

from .types import (
    TimeSeries,
    TariffConfig,
    BatteryConfig,
)
from .scenario_runner import ScenarioRunner, FullScenarioOutput


@dataclass
class ComputeV3Input:
    """Structuur die 1-op-1 lijkt op je FastAPI request body."""
    load_kwh: list[float]
    pv_kwh: list[float]
    prices_dyn: list[float]

    # Tarieven
    p_enkel_imp: float
    p_enkel_exp: float
    p_dag: float
    p_nacht: float
    p_exp_dn: float
    p_export_dyn: float

    # Batterij
    E: float
    P: float
    DoD: float
    eta_rt: float
    vastrecht: float
    battery_cost: float
    battery_degradation: float

    # Feed-in / omvormer
    feedin_monthly_cost: float
    feedin_cost_per_kwh: float
    feedin_free_kwh: float
    feedin_price_after_free: float
    inverter_power_kw: float
    inverter_cost_per_kw_year: float
    capacity_tariff_kw_year: float

    current_tariff: str
    country: str


class BatteryEnginePro3:
    """
    Publieke interface van de engine.
    Wordt aangeroepen door FastAPI in main.py (endpoint /compute_v3).
    """

    @staticmethod
    def compute(input_data: ComputeV3Input) -> Dict[str, Any]:
        """
        Hoofdfunctie:

        - Bouwt TimeSeries, TariffConfig, BatteryConfig
        - Roept ScenarioRunner.run()
        - Formatteert output naar JSON-achtig dict
        """
        # TODO: implementatie volgt in volgende stap
        raise NotImplementedError("BatteryEnginePro3.compute is not implemented yet")
