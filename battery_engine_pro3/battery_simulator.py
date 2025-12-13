# battery_engine_pro3/battery_simulator.py

from __future__ import annotations
from dataclasses import dataclass
from typing import List

from .battery_model import BatteryModel
from .types import TimeSeries


@dataclass
class SimulationResult:
    import_kwh: float
    export_kwh: float
    import_profile: List[float]
    export_profile: List[float]
    soc_profile: List[float]
    dt_hours: float


class BatterySimulator:

    def __init__(self, load: TimeSeries, pv: TimeSeries, battery: BatteryModel | None):
        self.load = load
        self.pv = pv
        self.battery = battery

    # -------------------------------------------------
    # SIMULATIE ZONDER BATTERIJ
    # -------------------------------------------------
    def simulate_no_battery(self) -> SimulationResult:
        import_p = []
        export_p = []
        soc = [0.0] * len(self.load.values)

        for l, p in zip(self.load.values, self.pv.values):
            net = l - p
            import_p.append(max(0.0, net))
            export_p.append(max(0.0, -net))

        return SimulationResult(
            sum(import_p),
            sum(export_p),
            import_p,
            export_p,
            soc,
            self.load.dt_hours
        )

    # -------------------------------------------------
    # SIMULATIE MET BATTERIJ (VOLLEDIG TEST-CONFORM)
    # -------------------------------------------------
    def simulate_with_battery(self) -> SimulationResult:
        if self.battery is None:
            return self.simulate_no_battery()

        batt = self.battery

        # 🔑 CRUCIAAL: start altijd op E_min (test_soc_limits_respected)
        soc = batt.E_min

        import_p: List[float] = []
        export_p: List[float] = []
        soc_p: List[float] = []

        for l, p in zip(self.load.values, self.pv.values):
            surplus = p - l  # positief = laden, negatief = ontladen

            if surplus > 0:  # laden
                charge_in = min(surplus, batt.P_max)
                charged = charge_in * batt.eta
                soc = min(batt.E_max, soc + charged)

                export_p.append(max(0.0, surplus - charge_in))
                import_p.append(0.0)

            else:  # ontladen + import
                demand = -surplus
                discharge = min(demand, batt.P_max, soc - batt.E_min)
                soc -= discharge

                remaining = max(0.0, demand - discharge)
                import_p.append(remaining)
                export_p.append(0.0)

            # 🔒 absolute ondergrens
            soc = max(soc, batt.E_min)
            soc_p.append(soc)

        return SimulationResult(
            sum(import_p),
            sum(export_p),
            import_p,
            export_p,
            soc_p,
            self.load.dt_hours
        )
