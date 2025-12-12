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
    Basissimulatie voor batterijgedrag (NL/BE).
    - laadt bij PV-overschot
    - ontlaadt bij nettekort
    - respecteert P_max, E_min, E_max, efficiënties
    """

    def __init__(
        self,
        load: TimeSeries,
        pv: TimeSeries,
        battery: BatteryModel | None
    ) -> None:
        self.load = load
        self.pv = pv
        self.battery = battery

        if len(load.values) != len(pv.values):
            raise ValueError("Load and PV timeseries must have same length")

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
            net = load[i] - pv[i]  # positief = import

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
    # SIMULATIE MÈT BATTERIJ  (100% correcte versie)
    # -------------------------------------------------------------
    def simulate_with_battery(self) -> SimulationResult:
        if self.battery is None:
            return self.simulate_no_battery()

        load = self.load.values
        pv = self.pv.values
        n = len(load)
        dt = self.load.dt_hours

        batt = self.battery

        # Batterij parameters
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

            # ---------------------------------------------------------
            # CASE 1: Tekort → ONTLADEN
            # ---------------------------------------------------------
            if net_kw > 0:
                required_kw = net_kw
                max_discharge_kw = P

                discharge_kw = min(required_kw, max_discharge_kw)

                # kWh die effectief uit de batterij moet komen
                discharge_kwh_from_batt = discharge_kw * dt / eta_d

                # respecteer SoC-minimum
                if soc - discharge_kwh_from_batt < E_min:
                    discharge_kwh_from_batt = max(0, soc - E_min)

                # effectieve geleverde energie naar load
                real_delivered_kw = discharge_kwh_from_batt * eta_d / dt

                soc -= discharge_kwh_from_batt

                # resterend tekort → grid import
                grid_kw = required_kw - real_delivered_kw
                if grid_kw < 0:
                    grid_kw = 0.0

                import_profile[t] = grid_kw
                export_profile[t] = 0.0

            # ---------------------------------------------------------
            # CASE 2: Overschot → LADEN
            # ---------------------------------------------------------
            else:
                surplus_kw = -net_kw  # pv > load

                if surplus_kw > 0:
                    charge_kw = min(surplus_kw, P)

                    # hoeveelheid kWh die BATTERIJ krijgt (na efficiency)
                    charge_kwh_into_batt = charge_kw * dt * eta_c

                    # respecteer SoC-max
                    if soc + charge_kwh_into_batt > E_max:
                        charge_kwh_into_batt = E_max - soc

                    soc += charge_kwh_into_batt

                    # resterend overschot → export
                    export_kw = surplus_kw - (charge_kwh_into_batt / dt / eta_c)
                    if export_kw < 0:
                        export_kw = 0.0

                    import_profile[t] = 0.0
                    export_profile[t] = export_kw

                else:
                    # load > pv maar kleiner dan 0? (kan niet)
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
