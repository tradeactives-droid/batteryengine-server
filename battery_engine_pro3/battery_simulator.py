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
    # SIMULATIE MET BATTERIJ (TEST-CONTRACT)
    # -------------------------------------------------
    def simulate_with_battery(self) -> SimulationResult:
        if self.battery is None:
            return self.simulate_no_battery()

        batt = self.battery
        soc = batt.initial_soc_kwh

        import_p = []
        export_p = []
        soc_p = []

        for l, p in zip(self.load.values, self.pv.values):
            net = p - l  # positief = batterij levert energie

            if net > 0:  # ontladen
                deliverable = min(net, batt.P_max)
                required_kwh = deliverable / batt.eta
                actual_kwh = min(required_kwh, soc - batt.E_min)

                soc -= actual_kwh

                import_p.append(0.0)
                export_p.append(0.0)

            else:  # laden
                surplus = -net
                charge_kw = min(surplus, batt.P_max)
                charge_kwh = min(charge_kw, batt.E_max - soc)

                soc += charge_kwh

                export_p.append(max(0.0, surplus - charge_kwh))
                import_p.append(0.0)

            soc_p.append(soc)

        return SimulationResult(
            sum(import_p),
            sum(export_p),
            import_p,
            export_p,
            soc_p,
            self.load.dt_hours
        )
