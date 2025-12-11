# battery_engine_pro3/battery_simulator.py

from __future__ import annotations
from dataclasses import dataclass
from typing import List, Literal

from .battery_model import BatteryModel
from .types import TimeSeries, CountryCode, TariffCode


@dataclass
class SimulationResult:
    """Tijdreeks- en jaarresultaten van een batterijsimulatie."""
    import_kwh: float
    export_kwh: float
    import_profile: List[float]
    export_profile: List[float]
    soc_profile: List[float]
    dt_hours: float


class BatterySimulator:
    """
    Hoofdsimulator voor NL/BE batterijgedrag.

    - NL: focus op eigenverbruik / dynamische prijzen
    - BE: focus op peak shaving + eigenverbruik
    """

    def __init__(
        self,
        load: TimeSeries,
        pv: TimeSeries,
        battery: BatteryModel,
        country: CountryCode,
        tariff_type: TariffCode
    ) -> None:
        self.load = load
        self.pv = pv
        self.battery = battery
        self.country = country
        self.tariff_type = tariff_type

        if len(load.values) != len(pv.values):
            raise ValueError("Load and PV timeseries must have same length")

    def simulate_no_battery(self) -> SimulationResult:
        """
        Simulatie zonder batterij (baseline).
        """
        raise NotImplementedError("BatterySimulator.simulate_no_battery is not implemented yet")

    def simulate_with_battery(self) -> SimulationResult:
        """
        Simulatie mét batterij (automatische strategie per land).

        - BE: automatische peak shaving
        - NL: automatische optimalisatie op eigen verbruik / feed-in / prijzen
        """
        raise NotImplementedError("BatterySimulator.simulate_with_battery is not implemented yet")
