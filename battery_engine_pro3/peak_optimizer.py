from __future__ import annotations
from dataclasses import dataclass
from typing import List, Tuple

from .battery_model import BatteryModel
from .types import TimeSeries


# ============================================================
# PHASE 1 — BASELINE PEAK DETECTION
# ============================================================

class PeakOptimizer:

    @staticmethod
    def compute_monthly_peaks(load: TimeSeries, pv: TimeSeries) -> List[float]:
        """
        Berekent per maand de maximale net-afname (kW).
        load - pv  (negatief = teruglevering telt niet)
        """
        n = len(load.values)
        dt = load.dt_hours
        timestamps = load.timestamps

        monthly_peaks = [0.0] * 12

        for i in range(n):
            net_kw = load.values[i] - pv.values[i]
            if net_kw < 0:
                net_kw = 0.0  # export telt niet
            month = timestamps[i].month - 1
            if net_kw > monthly_peaks[month]:
                monthly_peaks[month] = net_kw

        return monthly_peaks

    @staticmethod
    def compute_monthly_targets(baseline_peaks: List[float], reduction_factor: float = 0.85) -> List[float]:
        """
        Berekent doelpeaks (bijv. 15% reductie = factor 0.85).
        """
        return [p * reduction_factor for p in baseline_peaks]


# ============================================================
# PHASE 2 — MONTHLY SOC MINIMUM PLANNING
# ============================================================

class PeakShavingPlanner:

    @staticmethod
    def compute_required_reserve(
        baseline_peak_kw: float,
        target_peak_kw: float,
        timestep_hours: float = 0.25
    ) -> float:
        """
        Reserve (kWh) die nodig is om een piek te scheren.
        """
        delta_kw = max(0.0, baseline_peak_kw - target_peak_kw)
        return delta_kw * timestep_hours

    @staticmethod
    def plan_monthly_soc_targets(
        load: TimeSeries,
        pv: TimeSeries,
        battery: BatteryModel,
        baseline_peaks: List[float],
        target_peaks: List[float]
    ) -> List[float]:
        
        n = len(load.values)
        dt = load.dt_hours
        timestamps = load.timestamps

        soc_min_curve = [battery.E_min] * n

        # Reserve per maand
        monthly_reserve = []
        for m in range(12):
            reserve = PeakShavingPlanner.compute_required_reserve(
                baseline_peaks[m],
                target_peaks[m],
                timestep_hours=dt
            )
            monthly_reserve.append(reserve)

        # Toewijzen van maand-reserves aan tijdstappen
        for i in range(n):
            month = timestamps[i].month - 1
            soc_min_curve[i] = battery.E_min + monthly_reserve[month]

        return soc_min_curve


# ============================================================
# PHASE 3 — ADVANCED PEAK SHAVING SIMULATION
# ============================================================

class PeakShaver:

    @staticmethod
    def simulate_with_peak_shaving(
        load: TimeSeries,
        pv: TimeSeries,
        battery: BatteryModel,
        monthly_targets: List[float],
        soc_plan: List[float]
    ) -> Tuple[List[float], List[float], List[float], List[float]]:

        load_v = load.values
        pv_v = pv.values
        ts = load.timestamps
        dt = load.dt_hours
        n = len(load_v)

        P = battery.power_kw
        eta_c = battery.eta_charge
        eta_d = battery.eta_discharge
        E_min = battery.E_min
        E_max = battery.E_max

        soc = battery.initial_soc_kwh

        import_profile = [0.0] * n
        export_profile = [0.0] * n
        soc_profile = [0.0] * n
        monthly_peaks_after = [0.0] * 12

        for t in range(n):
            month = ts[t].month - 1
            target_peak = monthly_targets[month]
            soc_min_required = soc_plan[t]

            load_kw = load_v[t]
            pv_kw = pv_v[t]
            net_kw = load_kw - pv_kw

            # CASE 1 — Peak shaving
            if net_kw > target_peak:
                required_kw = net_kw - target_peak
                discharge_kw = min(required_kw, P)

                discharge_kwh_from_batt = discharge_kw * dt / eta_d

                if soc - discharge_kwh_from_batt < soc_min_required:
                    discharge_kwh_from_batt = max(0.0, soc - soc_min_required)

                real_kw = discharge_kwh_from_batt * eta_d / dt
                soc -= discharge_kwh_from_batt

                grid_kw = max(0.0, load_kw - pv_kw - real_kw)
                import_profile[t] = grid_kw
                export_profile[t] = 0.0

            else:
                # CASE 2 — Laden of klein import
                net_surplus_kw = pv_kw - load_kw

                if net_surplus_kw > 0:
                    charge_kw = min(net_surplus_kw, P)
                    charge_kwh = charge_kw * dt * eta_c

                    if soc + charge_kwh > E_max:
                        charge_kwh = E_max - soc

                    soc += charge_kwh
                    export_profile[t] = max(0.0, net_surplus_kw - (charge_kwh / dt / eta_c))
                    import_profile[t] = 0.0
                else:
                    import_profile[t] = -net_surplus_kw
                    export_profile[t] = 0.0

            soc_profile[t] = soc

            if import_profile[t] > monthly_peaks_after[month]:
                monthly_peaks_after[month] = import_profile[t]

        return monthly_peaks_after, import_profile, export_profile, soc_profile
