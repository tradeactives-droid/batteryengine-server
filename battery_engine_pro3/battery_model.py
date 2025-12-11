# battery_engine_pro3/battery_model.py

from __future__ import annotations
from dataclasses import dataclass


@dataclass
class BatteryModel:
    """
    Kern-batterijmodel voor BatteryEngine Pro 3.

    Let op:
    - capacity_kwh: nominale capaciteit van de batterij
    - power_kw: maximaal laad/ontlaadvermogen
    - dod: depth-of-discharge (0–1)
    - eta_rt: round-trip efficiëntie (0–1)
    """
    capacity_kwh: float
    power_kw: float
    dod: float
    eta_rt: float

    def __post_init__(self) -> None:
        # Charge / discharge efficiencies (sqrt van roundtrip)
        self.eta_c = self.eta_rt ** 0.5
        self.eta_d = self.eta_rt ** 0.5

        # SoC-limieten
        self.E_min = self.capacity_kwh * (1.0 - self.dod)
        self.E_max = self.capacity_kwh * self.dod

    def validate(self) -> None:
        """Voert simpele sanity-checks uit op de configuratie."""
        if self.capacity_kwh <= 0 or self.power_kw <= 0:
            raise ValueError("Battery capacity and power must be > 0")

        if not (0.0 < self.dod <= 1.0):
            raise ValueError("DoD must be in (0, 1]")

        if not (0.0 < self.eta_rt <= 1.0):
            raise ValueError("Round-trip efficiency must be in (0, 1]")
