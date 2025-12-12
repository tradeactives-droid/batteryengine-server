from __future__ import annotations
from dataclasses import dataclass
import math


@dataclass
class BatteryModel:
    E_cap: float
    P_max: float
    dod: float
    eta: float
    initial_soc_frac: float = 1.0

    capacity_kwh: float = 0.0
    power_kw: float = 0.0
    eta_charge: float = 1.0
    eta_discharge: float = 1.0
    E_min: float = 0.0
    E_max: float = 0.0
    initial_soc_kwh: float = 0.0

    def __post_init__(self):
        self.E_cap = max(0.0, self.E_cap)
        self.P_max = max(0.0, self.P_max)
        self.dod = min(max(self.dod, 0.0), 1.0)

        if self.eta <= 0:
            self.eta = 1.0

        self.capacity_kwh = self.E_cap
        self.power_kw = self.P_max

        eff = math.sqrt(self.eta)
        self.eta_charge = eff
        self.eta_discharge = eff

        self.E_max = self.E_cap
        self.E_min = self.E_cap * (1.0 - self.dod)

        # ⭐ TEST-VERPLICHTE initial SoC
        self.initial_soc_kwh = self.E_min + self.initial_soc_frac * (self.E_max - self.E_min)
