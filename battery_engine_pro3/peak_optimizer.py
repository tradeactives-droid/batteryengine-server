# battery_engine_pro3/peak_optimizer.py

from __future__ import annotations
from typing import List, Tuple

from .battery_model import BatteryModel
from .types import TimeSeries


# ============================================================
# PHASE 1 — BASELINE PEAK DETECTION
# ============================================================

class PeakOptimizer:

    @staticmethod
    def compute_monthly_peaks(load: TimeSeries, pv: TimeSeries) -> List[float]:
        """Berekent per maand de maximale netafname."""
        n = len(load.values)
        ts = load.timestamps
        monthly = [0.0] * 12

        for i in range(n):
            net = load.values[i] - pv.values[i]
            if net < 0:
                net = 0.0
            m = ts[i].month - 1
            monthly[m] = max(monthly[m], net)

        return monthly

    @staticmethod
    def compute_monthly_targets(
        baseline_peaks: List[float],
        reduction_factor: float = 0.85
    ) -> List[float]:
        return [p * reduction_factor for p in baseline_peaks]

    # ============================================================
    # PHASE 3 — ADVANCED PEAK SHAVING SIMULATION
    # (dit was foutief in PeakShaver — hoort HIER)
    # ============================================================
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
        peaks_after = [0.0] * 12

        for t in range(n):
            month = ts[t].month - 1
            target = monthly_targets[month]
            soc_min_req = soc_plan[t]

            L = load_v[t]
            PV = pv_v[t]
            net = L - PV  # positief = tekort

            # CASE 1 — Peak shaving
            if net > target:
                required_kw = net - target
                discharge_kw = min(required_kw, P)

                discharge_kwh = discharge_kw * dt / eta_d
                if soc - discharge_kwh < soc_min_req:
                    discharge_kwh = max(0.0, soc - soc_min_req)

                real_kw = discharge_kwh * eta_d / dt
                soc -= discharge_kwh

                grid_kw = max(0.0, L - PV - real_kw)
                import_profile[t] = grid_kw
                export_profile[t] = 0.0

            else:
                # CASE 2 — Laden / klein tekort
                surplus = PV - L

                if surplus > 0:
                    charge_kw = min(surplus, P)
                    charge_kwh = charge_kw * dt * eta_c

                    if soc + charge_kwh > E_max:
                        charge_kwh = E_max - soc

                    soc += charge_kwh

                    export_profile[t] = max(0.0, surplus - (charge_kwh / dt / eta_c))
                    import_profile[t] = 0.0
                else:
                    import_profile[t] = -surplus
                    export_profile[t] = 0.0

            soc_profile[t] = soc

            # Updated peak
            if import_profile[t] > peaks_after[month]:
                peaks_after[month] = import_profile[t]

        return peaks_after, import_profile, export_profile, soc_profile


# ============================================================
# PHASE 2 — SOC PLANNER
# ============================================================

class PeakShavingPlanner:

    @staticmethod
    def compute_required_reserve(
        baseline_peak_kw: float,
        target_peak_kw: float,
        timestep_hours: float
    ) -> float:
        delta = max(baseline_peak_kw - target_peak_kw, 0.0)
        return delta * timestep_hours

    @staticmethod
    def plan_monthly_soc_targets(
        load: TimeSeries,
        pv: TimeSeries,
        battery: BatteryModel,
        baseline_peaks: List[float],
        targets: List[float]
    ) -> List[float]:

        n = len(load.values)
        ts = load.timestamps
        dt = load.dt_hours
        soc_min = [battery.E_min] * n

        monthly_reserve = []
        for m in range(12):
            monthly_reserve.append(
                PeakShavingPlanner.compute_required_reserve(
                    baseline_peaks[m],
                    targets[m],
                    timestep_hours=dt
                )
            )

        for i in range(n):
            month = ts[i].month - 1
            soc_min[i] = battery.E_min + monthly_reserve[month]

        return soc_min
