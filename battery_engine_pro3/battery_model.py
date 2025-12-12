# battery_engine_pro3/battery_model.py

from __future__ import annotations
from dataclasses import dataclass


@dataclass
class BatteryModel:
    """
    Kernmodel van de batterij voor BatteryEngine Pro 3.
    """

    E_cap: float          # totale capaciteit (kWh)
    P_max: float          # max laad/ontlaadvermogen (kW)
    dod: float            # depth of discharge (0..1)
    eta: float            # round-trip efficiency
    initial_soc_frac: float = 1.0  # fractie van bruikbare energie (0..1)

    # Afgeleide velden
    capacity_kwh: float = 0.0
    power_kw: float = 0.0
    eta_charge: float = 1.0
    eta_discharge: float = 1.0
    E_min: float = 0.0
    E_max: float = 0.0
    initial_soc_kwh: float = 0.0

    def __post_init__(self) -> None:

        # -----------------------------
        # Bounds & correcties
        # -----------------------------
        self.E_cap = max(0.0, self.E_cap)
        self.P_max = max(0.0, self.P_max)

        self.dod = min(max(self.dod, 0.0), 1.0)
        self.initial_soc_frac = min(max(self.initial_soc_frac, 0.0), 1.0)

        if self.eta <= 0:
            self.eta = 1.0

        # -----------------------------
        # Aliases
        # -----------------------------
        self.capacity_kwh = float(self.E_cap)
        self.power_kw = float(self.P_max)

        # -----------------------------
        # Split round-trip efficiency
        # -----------------------------
        base = self.eta ** 0.5
        self.eta_charge = base
        self.eta_discharge = base

        # -----------------------------
        # SoC limieten op basis van DoD
        # -----------------------------
        self.E_max = self.E_cap
        self.E_min = self.E_cap * (1.0 - self.dod)

        # -----------------------------
        # ⭐ Correcte initial SoC (TEST EIST DIT)
        # E_min + frac * (E_max - E_min)
        # -----------------------------
        self.initial_soc_kwh = self.E_min + self.initial_soc_frac * (self.E_max - self.E_min)
