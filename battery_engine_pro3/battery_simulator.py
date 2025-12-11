# battery_engine_pro3/battery_simulator.py

from __future__ import annotations
from dataclasses import dataclass
from typing import List, Optional

from .battery_model import BatteryModel
from .types import TimeSeries


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
    
    - Zonder battery → simulate_no_battery()
    - Met battery → simulate_with_battery()
    """

    def __init__(
        self,
        load: TimeSeries,
        pv: TimeSeries,
        battery: Optional[BatteryModel] = None
    ) -> None:
        self.load = load
        self.pv = pv
        self.battery = battery

        if len(load.values) != len(pv.values):
            raise ValueError("Load and PV timeseries must have same length")

    # ------------------------------------------------------------
    # SCENARIO A1 / B1 — ZONDER BATTERIJ
    # ------------------------------------------------------------
    def simulate_no_battery(self) -> SimulationResult:
        """
        Basissimulatie zonder batterij.
        load = verbruik
        pv   = opwek
        import = max(load - pv, 0)
        export = max(pv - load, 0)
        """

        load = self.load.values
        pv = self.pv.values
        n = len(load)
        dt = self.load.dt_hours

        import_profile = []
        export_profile = []

        for i in range(n):
            net = load[i] - pv[i]  # positief = import, negatief = export

            if net >= 0:
                import_profile.append(net)
                export_profile.append(0.0)
            else:
                import_profile.append(0.0)
                export_profile.append(-net)

        return SimulationResult(
            import_kwh=sum(import_profile),
            export_kwh=sum(export_profile),
            import_profile=import_profile,
            export_profile=export_profile,
            soc_profile=[0.0] * n,
            dt_hours=dt
        )

    # ------------------------------------------------------------
    # SCENARIO C1 — MET BATTERIJ (baseline, geen peak shaving)
    # ------------------------------------------------------------
    def simulate_with_battery(self) -> SimulationResult:
        """
        Simuleert batterijgedrag:
        - laden bij overschot (pv > load)
        - ontladen bij tekort (load > pv)
        - respecteert DoD, efficiency & power limits
        """

        if self.battery is None:
            raise ValueError("simulate_with_battery() called but no BatteryModel provided")

        load = self.load.values
        pv = self.pv.values
        n = len(load)

        dt = self.load.dt_hours
        batt = self.battery

        P_max = batt.power_kw
        eta_c = batt.eta_charge
        eta_d = batt.eta_discharge
        E_min = batt.E_min
        E_max = batt.E_max

        soc = batt.initial_soc_kwh

        import_profile = []
        export_profile = []
        soc_profile = []

        for t in range(n):
            net = load[t] - pv[t]  # + → tekort, - → overschot

            if net > 0:
                # -----------------------------
                # ONTLADEN
                # -----------------------------
                max_discharge = P_max * dt
                discharge_needed = min(net, max_discharge)

                discharge_from_batt = discharge_needed / eta_d

                if soc - discharge_from_batt < E_min:
                    discharge_from_batt = soc - E_min

                delivered = discharge_from_batt * eta_d
                soc -= discharge_from_batt

                grid_import = net - delivered
                if grid_import < 0:
                    grid_import = 0.0

                import_profile.append(grid_import)
                export_profile.append(0.0)

            else:
                # -----------------------------
                # LADEN
                # -----------------------------
                surplus = -net
                max_charge = P_max * dt

                charge_possible = min(surplus, max_charge)
                charge_into_batt = charge_possible * eta_c

                if soc + charge_into_batt > E_max:
                    charge_into_batt = E_max - soc

                soc += charge_into_batt

                grid_export = surplus - (charge_into_batt / eta_c)
                if grid_export < 0:
                    grid_export = 0.0

                import_profile.append(0.0)
                export_profile.append(grid_export)

            soc_profile.append(soc)

        return SimulationResult(
            import_kwh=sum(import_profile),
            export_kwh=sum(export_profile),
            import_profile=import_profile,
            export_profile=export_profile,
            soc_profile=soc_profile,
            dt_hours=dt
        )
