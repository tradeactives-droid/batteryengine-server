# battery_engine_pro3/battery_model.py

from __future__ import annotations
from dataclasses import dataclass


@dataclass
class BatteryModel:
    """
    Kernmodel van de batterij voor BatteryEngine Pro 3.

    Parameters (input):
    - E_cap : totale batterijcapaciteit (kWh)
    - P_max : max. laad/ontlaadvermogen (kW)
    - dod   : Depth of Discharge (0..1, bijv. 0.9 = 90% bruikbaar)
    - eta   : round-trip efficiëntie (0..1, bijv. 0.9 = 90%)
    - initial_soc_frac : start-SoC als fractie van E_max (0..1)

    Afgeleide velden (worden in __post_init__ gezet):
    - capacity_kwh      : alias voor E_cap
    - power_kw          : alias voor P_max
    - eta_charge        : laad-efficiëntie (≈ sqrt(eta))
    - eta_discharge     : ontlaad-efficiëntie (≈ sqrt(eta))
    - E_min             : minimale SoC (kWh) volgens DoD
    - E_max             : maximale SoC (kWh) = E_cap
    - initial_soc_kwh   : start-SoC in kWh
    """

    E_cap: float          # kWh
    P_max: float          # kW
    dod: float            # 0..1 (bruikbare fractie, bv. 0.9)
    eta: float            # 0..1 (round-trip efficiëntie)
    initial_soc_frac: float = 1.0  # start standaard vol (100% van E_max)

    # Deze velden worden in __post_init__ ingevuld:
    capacity_kwh: float = 0.0
    power_kw: float = 0.0
    eta_charge: float = 1.0
    eta_discharge: float = 1.0
    E_min: float = 0.0
    E_max: float = 0.0
    initial_soc_kwh: float = 0.0

    def __post_init__(self) -> None:
        # Zorg dat inputs binnen redelijke grenzen liggen
        if self.E_cap < 0:
            self.E_cap = 0.0
        if self.P_max < 0:
            self.P_max = 0.0
        if self.dod < 0:
            self.dod = 0.0
        if self.dod > 1:
            self.dod = 1.0
        if self.eta <= 0:
            self.eta = 1.0
        if self.initial_soc_frac < 0:
            self.initial_soc_frac = 0.0
        if self.initial_soc_frac > 1:
            self.initial_soc_frac = 1.0

        # Basisaliases
        self.capacity_kwh = float(self.E_cap)
        self.power_kw = float(self.P_max)

        # Efficiëntie: split round-trip in laad + ontlaad
        # simpel model: beide gelijk aan sqrt(eta)
        self.eta_charge = self.eta ** 0.5
        self.eta_discharge = self.eta ** 0.5

        # DoD-limieten
        # dod = bruikbaar deel → bij 0.9 mag je 90% van de capaciteit aanspreken
        # E_max = totale capaciteit
        # E_min = ondergrens SoC (dus 10% over als dod=0.9)
        self.E_max = self.E_cap
        self.E_min = self.E_cap * (1.0 - self.dod)

        # Start-SoC (in kWh)
        self.initial_soc_kwh = self.E_min + self.initial_soc_frac * (self.E_max - self.E_min)
