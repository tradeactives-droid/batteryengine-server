# battery_engine_pro3/battery_simulator.py

from __future__ import annotations
from dataclasses import dataclass
from typing import List, Literal

from .battery_model import BatteryModel
from .types import TimeSeries, CountryCode, TariffCode


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

    - NL: focus op eigenverbruik / dynamische prijzen
    - BE: focus op peak shaving + eigenverbruik
    """

    def __init__(
        self,
        load: TimeSeries,
        pv: TimeSeries,
        battery: BatteryModel,
        country: CountryCode,
        tariff_type: TariffCode
    ) -> None:
        self.load = load
        self.pv = pv
        self.battery = battery
        self.country = country
        self.tariff_type = tariff_type

        if len(load.values) != len(pv.values):
            raise ValueError("Load and PV timeseries must have same length")

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

        import_kwh = sum(import_profile)
        export_kwh = sum(export_profile)

        # Geen batterij, dus SoC = 0 voor alle punten
        soc_profile = [0.0] * n

        return SimulationResult(
            import_kwh=import_kwh,
            export_kwh=export_kwh,
            import_profile=import_profile,
            export_profile=export_profile,
            soc_profile=soc_profile,
            dt_hours=dt
        )

    def simulate_with_battery(self) -> SimulationResult:
        """
        Baseline batterijsimulatie (zonder peak shaving).
        Laadt bij overschot, ontlaadt bij tekort, respecteert:
        - P_max
        - E_min / E_max
        - Efficiëntie (eta_c / eta_d)
        """

        load = self.load.values
        pv = self.pv.values
        n = len(load)

        dt = self.load.dt_hours
        batt = self.battery

        E = batt.capacity_kwh
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
            net = load[t] - pv[t]  # positief = import nodig

            if net > 0:
                # ------------------------------------------
                # ONTLADEN (vraag > opwek)
                # ------------------------------------------
                max_discharge_kwh = P_max * dt  # kWh
                discharge_needed = min(net, max_discharge_kwh)

                # Door efficiëntie geeft batt minder energie af dan SoC verliest
                discharge_from_batt = discharge_needed / eta_d

                if soc - discharge_from_batt < E_min:
                    discharge_from_batt = soc - E_min

                # werkelijke batterijoutput
                delivered = discharge_from_batt * eta_d

                soc -= discharge_from_batt
                grid_import = net - delivered

                if grid_import < 0:
                    grid_import = 0.0

                import_profile.append(grid_import)
                export_profile.append(0.0)

            else:
                # ------------------------------------------
                # LADEN (opwek > vraag)
                # ------------------------------------------
                surplus = -net
                max_charge_kwh = P_max * dt  # kWh

                charge_possible = min(surplus, max_charge_kwh)

                # Door efficiëntie neemt de batterij minder toe dan je erin stopt
                charge_into_batt = charge_possible * eta_c

                if soc + charge_into_batt > E_max:
                    charge_into_batt = E_max - soc

                soc += charge_into_batt

                # grid export = PV overschot dat niet in de batterij kan
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
