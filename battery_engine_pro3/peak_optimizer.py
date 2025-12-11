# battery_engine_pro3/peak_optimizer.py

from __future__ import annotations
from dataclasses import dataclass
from typing import List

from .types import TimeSeries, PeakInfo


@dataclass
class MonthlyPeaks:
    before: List[float]
    after: List[float]


class PeakOptimizer:
    """
    BE Peak Shaving Engine (versie 1)
    - Detecteert maandpieken vóór batterij
    - Berekent maandpieken NA batterij (placeholder)
    """

    @staticmethod
    def compute_monthly_peaks(load: TimeSeries, pv: TimeSeries) -> List[float]:
        """
        Berekent maandpieken (kW) ZONDER batterij.
        load en pv zijn TimeSeries met dt_hours (bv. 0.25).
        """
        dt = load.dt_hours
        net = [load.values[i] - pv.values[i] for i in range(len(load))]

        peaks = [0.0 for _ in range(12)]  # 12 maanden

        for i, value in enumerate(net):
            month_index = load.month_index[i]  # 0..11
            power_kw = value / dt             # kWh → kW

            if power_kw > peaks[month_index]:
                peaks[month_index] = power_kw

        return peaks

    @staticmethod
    def compute_monthly_peaks_after(load: TimeSeries, pv: TimeSeries, limits: List[float]) -> List[float]:
        """
        Placeholder voor peak-shaved pieken NA batterij.
        Voor nu: return dezelfde waarden als ervoor.

        Wordt in Stap 7B vervangen door echte peak shaving.
        """
        return PeakOptimizer.compute_monthly_peaks(load, pv)

    @staticmethod
    def compute_peakinfo(load: TimeSeries, pv: TimeSeries, limits: List[float]) -> PeakInfo:
        """
        Bouwt PeakInfo object zoals ScenarioRunner verwacht.
        """
        before = PeakOptimizer.compute_monthly_peaks(load, pv)
        after  = PeakOptimizer.compute_monthly_peaks_after(load, pv, limits)

        return PeakInfo(monthly_before=before, monthly_after=after)


    # ------------------------------------------------------------
    #  PEAK SHAVING – FASE 1
    # ------------------------------------------------------------
    @staticmethod
    def compute_monthly_targets(before_peaks: List[float], reduction_factor: float = 0.85) -> List[float]:
        """
        Bepaalt peak targets per maand.
        reduction_factor = 0.85 betekent 15% reductie t.o.v. oorspronkelijke piek.
        Dit is een eenvoudige, maar effectief startpunt.
        """
        return [p * reduction_factor for p in before_peaks]

    @staticmethod
    def simulate_with_peak_shaving(
        load: TimeSeries,
        pv: TimeSeries,
        battery: BatteryModel,
        monthly_targets: List[float]
    ):
        """
        Simuleert batterijgedrag MET peak shaving:
        Ontlaadt batterij wanneer (load > target), zodat load nooit boven target komt.
        """

        dt = load.dt_hours
        values_load = load.values
        values_pv = pv.values
        n = len(values_load)

        soc = battery.initial_soc_kwh
        P = battery.power_kw
        eta_c = battery.eta_charge
        eta_d = battery.eta_discharge
        E_min = battery.E_min
        E_max = battery.E_max

        import_profile = []
        export_profile = []
        soc_profile = []

        new_monthly_peaks = [0.0] * 12

        for t in range(n):
            month = load.month_index[t]
            target = monthly_targets[month]

            net = values_load[t] - values_pv[t]      # positief = tekort
            dt_energy = P * dt                       # max dis/charge per timestep

            # ------------------------------------------------------------
            # 1. Als load onder target zit → normale simulatie
            # ------------------------------------------------------------
            if net <= target * dt:
                # Normale laad/ontlaadregels (zoals simulate_with_battery)
                # Maar eenvoudiger hier
                if net > 0:
                    # tekort → ontladen
                    discharge = min(net, dt_energy)
                    dis_batt = discharge / eta_d

                    if soc - dis_batt < E_min:
                        dis_batt = soc - E_min

                    delivered = dis_batt * eta_d
                    soc -= dis_batt
                    grid_import = net - delivered
                    if grid_import < 0:
                        grid_import = 0.0

                    import_profile.append(grid_import)
                    export_profile.append(0.0)

                else:
                    # overschot → laden
                    surplus = -net
                    charge = min(surplus, dt_energy)
                    charge_into = charge * eta_c

                    if soc + charge_into > E_max:
                        charge_into = E_max - soc

                    soc += charge_into
                    export_val = surplus - (charge_into / eta_c)
                    if export_val < 0:
                        export_val = 0.0

                    import_profile.append(0.0)
                    export_profile.append(export_val)

            # ------------------------------------------------------------
            # 2. Als load boven target komt → peak shaving
            # ------------------------------------------------------------
            else:
                # hoeveel moeten we verlagen?
                desired_kw = target                   # kW doel
                actual_kw = values_load[t] - values_pv[t] / dt  # kW
                reduction_kw = actual_kw - desired_kw

                reduction_kwh = reduction_kw * dt

                # hoeveel kan batterij leveren?
                deliverable = min(dt_energy, reduction_kwh)
                dis_batt = deliverable / eta_d

                if soc - dis_batt < E_min:
                    dis_batt = soc - E_min

                delivered = dis_batt * eta_d
                soc -= dis_batt

                # nieuwe net belasting:
                new_net = net - delivered
                if new_net < 0:
                    new_net = 0.0

                import_profile.append(new_net)
                export_profile.append(0.0)

            # track nieuwe maandpiek
            new_power_kw = max(0.0, (import_profile[-1]) / dt)
            if new_power_kw > new_monthly_peaks[month]:
                new_monthly_peaks[month] = new_power_kw

            soc_profile.append(soc)

        return new_monthly_peaks, import_profile, export_profile, soc_profile
