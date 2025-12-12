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

    def simulate_no_battery(self) -> SimulationResult:
        import_p, export_p = [], []
        for l, p in zip(self.load.values, self.pv.values):
            net = l - p
            import_p.append(max(0, net))
            export_p.append(max(0, -net))

        return SimulationResult(
            sum(import_p), sum(export_p),
            import_p, export_p,
            [0.0]*len(import_p),
            self.load.dt_hours
        )

    def simulate_with_battery(self) -> SimulationResult:
        if self.battery is None:
            return self.simulate_no_battery()

        soc = self.battery.initial_soc_kwh
        dt = self.load.dt_hours

        import_p, export_p, soc_p = [], [], []

        for l, p in zip(self.load.values, self.pv.values):
            net = l - p

            if net < 0:
                charge = min(-net, self.battery.power_kw)
                energy = charge * dt * self.battery.eta_charge
                energy = min(energy, self.battery.E_max - soc)
                soc += energy
                export_p.append(max(0, -net - energy / dt))
                import_p.append(0)
            else:
                discharge = min(net, self.battery.power_kw)
                energy = discharge * dt / self.battery.eta_discharge
                energy = min(energy, soc - self.battery.E_min)
                soc -= energy
                delivered = energy * self.battery.eta_discharge / dt
                import_p.append(max(0, net - delivered))
                export_p.append(0)

            soc_p.append(soc)

        return SimulationResult(
            sum(import_p), sum(export_p),
            import_p, export_p, soc_p, dt
        )
