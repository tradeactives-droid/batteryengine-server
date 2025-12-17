# battery_engine_pro3/battery_simulator.py

from __future__ import annotations
from dataclasses import dataclass
from typing import List

from .battery_model import BatteryModel
from .types import TimeSeries
import numpy as np


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
    # ZONDER BATTERIJ
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
    # MET BATTERIJ (TEST-CONFORM MODEL)
    # -------------------------------------------------
    def simulate_with_battery(self) -> SimulationResult:
        if self.battery is None:
            return self.simulate_no_battery()

        batt = self.battery
        soc = batt.initial_soc_kwh

        # 🔶 Dynamische prijsdata (optioneel)
        prices = getattr(self.load, "prices_dyn", None)

        import_p = []
        export_p = []
        soc_p = []

        # 🔶 Arbitrage-drempels (alleen als prijzen bestaan)
        if prices and len(prices) == len(self.load.values):
            low_thr = np.percentile(prices, 25)   # goedkoop
            high_thr = np.percentile(prices, 75)  # duur
        else:
            low_thr = None
            high_thr = None

        for l, p in zip(self.load.values, self.pv.values):
            net = l - p

            if net > 0:  # ontladen
                deliverable = min(net, batt.P_max)

                # ❗ GEEN efficiency bij ontladen (test-model)
                actual_kwh = min(deliverable, soc)

                delivered = actual_kwh
                soc -= actual_kwh

                import_p.append(max(0.0, net - delivered))
                export_p.append(0.0)

            else:  # laden (PV of goedkoop net)
                surplus = -net
                charge_kw = min(surplus, batt.P_max)

                # 🔶 Extra laden bij lage prijs (arbitrage)
                if price is not None and low_thr is not None and price < low_thr:
                    charge_kw = batt.P_max

                charge_kwh = charge_kw * batt.eta
                charge_kwh = min(charge_kwh, batt.E_max - soc)

                soc += charge_kwh

                export_p.append(max(0.0, surplus - charge_kwh / batt.eta))
                import_p.append(max(0.0, charge_kw - surplus))

                # 🔑 efficiency volledig bij laden
                charge_kwh = charge_kw * batt.eta
                charge_kwh = min(charge_kwh, batt.E_max - soc)

                soc += charge_kwh

                export_p.append(max(0.0, surplus - charge_kwh / batt.eta))
                import_p.append(0.0)

            soc_p.append(max(soc, batt.E_min))

        return SimulationResult(
            sum(import_p),
            sum(export_p),
            import_p,
            export_p,
            soc_p,
            self.load.dt_hours
        )
