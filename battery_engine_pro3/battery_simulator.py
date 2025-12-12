# battery_engine_pro3/battery_simulator.py

from __future__ import annotations
from dataclasses import dataclass
from typing import List

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
    Basissimulatie voor batterijgedrag:
    - PV-overschot → laden
    - Tekort → ontladen
    - respecteert P_max, E_min, E_max, eta_c, eta_d
    """

    def __init__(
        self,
        load: TimeSeries,
        pv: TimeSeries,
        battery: BatteryModel | None
    ) -> None:

        if len(load.values) != len(pv.values):
            raise ValueError("Load and PV timeseries must have same length")

        self.load = load
        self.pv = pv
        self.battery = battery

    # -------------------------------------------------------------
    # SIMULATIE ZONDER BATTERIJ
    # -------------------------------------------------------------
    def simulate_no_battery(self) -> SimulationResult:
        load = self.load.values
        pv = self.pv.values
        n = len(load)
        dt = self.load.dt_hours

        import_profile = []
        export_profile = []
        soc_profile = [0.0] * n

        for i in range(n):
            net = load[i] - pv[i]
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
            soc_profile=soc_profile,
            dt_hours=dt
        )

    # -------------------------------------------------------------
    # SIMULATIE MET BATTERIJ
    # -------------------------------------------------------------
    def simulate_with_battery(self) -> SimulationResult:
        if self.battery is None:
            return self.simulate_no_battery()

        load = self.load.values
        pv = self.pv.values
        n = len(load)
        dt = self.load.dt_hours

        batt = self.battery

        # Parameters
        P = batt.power_kw
        eta_c = batt.eta_charge
        eta_d = batt.eta_discharge
        E_min = batt.E_min
        E_max = batt.E_max

        soc = batt.initial_soc_kwh

        import_profile = [0.0] * n
        export_profile = [0.0] * n
        soc_profile = [0.0] * n

        for t in range(n):
            load_kw = load[t]
            pv_kw = pv[t]
            net_kw = load_kw - pv_kw  # positief = tekort → ontladen

            # =====================================================
            # CASE 1: TEKORT → BATTERIJ ONTLADEN
            # =====================================================
            if net_kw > 0:
                required_kw = net_kw
                discharge_kw = min(required_kw, P)

                # kWh die UIT de batterij moet komen (corrigeer voor efficiency)
                discharge_kwh = discharge_kw * dt / eta_d

                # Respecteer SoC-min
                if soc - discharge_kwh < E_min:
                    discharge_kwh = max(0.0, soc - E_min)

                # Werkelijke geleverde kW
                real_kw = discharge_kwh * eta_d / dt

                soc -= discharge_kwh

                # Resterende import uit net
                grid_kw = max(0.0, required_kw - real_kw)
                import_profile[t] = grid_kw
                export_profile[t] = 0.0

            # =====================================================
            # CASE 2: OVERSCHOT → LADEN
            # =====================================================
            else:
                surplus_kw = -net_kw  # pv > load

                if surplus_kw > 0:
                    charge_kw = min(surplus_kw, P)

                    # kWh die BATTERIJ ontvangt
                    charge_kwh = charge_kw * dt * eta_c

                    # Respecteer SoC-max
                    if soc + charge_kwh > E_max:
                        charge_kwh = E_max - soc

                    soc += charge_kwh

                    # Resterend overschot → export
                    export_kw = surplus_kw - (charge_kwh / dt / eta_c)
                    export_profile[t] = max(0.0, export_kw)
                    import_profile[t] = 0.0

                else:
                    # Net exact gelijk of minimale discrepantie
                    import_profile[t] = 0.0
                    export_profile[t] = 0.0

            soc_profile[t] = soc

        return SimulationResult(
            import_kwh=sum(import_profile),
            export_kwh=sum(export_profile),
            import_profile=import_profile,
            export_profile=export_profile,
            soc_profile=soc_profile,
            dt_hours=dt
        )
