# battery_engine_pro3/peak_optimizer.py

from __future__ import annotations
from typing import List, Tuple

from .battery_model import BatteryModel
from .types import TimeSeries


# ============================================================
# PHASE 1 — BASELINE PEAK DETECTION
# ============================================================

class PeakOptimizer:
    """
    PeakOptimizer:
    - compute_monthly_peaks: baseline net-afname per maand
    - compute_monthly_targets: doelpeaks (bv. 15% reductie)
    - simulate_with_peak_shaving: simulatie met/zonder soc_plan
    """

    @staticmethod
    def compute_monthly_peaks(load: TimeSeries, pv: TimeSeries) -> List[float]:
        """
        Berekent per maand de maximale net-afname (kW).
        net = load - pv  (negatief = export → telt niet mee)
        """
        n = len(load.values)
        timestamps = load.timestamps

        monthly_peaks = [0.0] * 12

        for i in range(n):
            net_kw = load.values[i] - pv.values[i]
            if net_kw < 0:
                net_kw = 0.0  # export telt niet mee als piek

            month = timestamps[i].month - 1  # 0..11
            if net_kw > monthly_peaks[month]:
                monthly_peaks[month] = net_kw

        return monthly_peaks

    @staticmethod
    def compute_monthly_targets(
        baseline_peaks: List[float],
        reduction_factor: float = 0.85
    ) -> List[float]:
        """
        Doelpeaks per maand. Bijvoorbeeld:
        - reduction_factor = 0.85 → 15% reductie t.o.v. baseline
        """
        return [p * reduction_factor for p in baseline_peaks]

    # ========================================================
    # PHASE 3 — PEAK SHAVING SIMULATOR
    # ========================================================
    @staticmethod
    def simulate_with_peak_shaving(
        load: TimeSeries,
        pv: TimeSeries,
        battery: BatteryModel,
        monthly_targets: List[float],
        soc_plan: List[float] | None = None
    ) -> Tuple[List[float], List[float], List[float], List[float]]:
        """
        Geavanceerde peak shaving simulatie.

        Wordt op twee manieren gebruikt:
        1) In unit test:
           PeakOptimizer.simulate_with_peak_shaving(load, pv, battery, targets)
           → soc_plan is dan None → we nemen E_min als ondergrens.

        2) In ScenarioRunner (BE):
           - baseline_peaks = PeakOptimizer.compute_monthly_peaks(...)
           - monthly_targets = PeakOptimizer.compute_monthly_targets(...)
           - soc_plan = PeakShavingPlanner.plan_monthly_soc_targets(...)
           - simulate_with_peak_shaving(..., monthly_targets, soc_plan)

        Output:
        - monthly_peaks_after: lijst van 12 pieken (kW)
        - import_profile [kW]
        - export_profile [kW]
        - soc_profile [kWh]
        """

        load_v = load.values
        pv_v = pv.values
        ts = load.timestamps
        dt = load.dt_hours
        n = len(load_v)

        # Batterijparam
        P = battery.power_kw
        eta_c = battery.eta_charge
        eta_d = battery.eta_discharge
        E_min = battery.E_min
        E_max = battery.E_max

        soc = battery.initial_soc_kwh

        # Als er geen soc_plan is (unit test), gebruik gewoon E_min
        if soc_plan is None:
            soc_plan = [E_min] * n

        import_profile = [0.0] * n
        export_profile = [0.0] * n
        soc_profile = [0.0] * n
        monthly_peaks_after = [0.0] * 12

        for t in range(n):
            month = ts[t].month - 1
            if month < 0 or month > 11:
                month = 0

            target_peak = monthly_targets[month] if month < len(monthly_targets) else monthly_targets[0]
            soc_min_required = soc_plan[t]

            load_kw = load_v[t]
            pv_kw = pv_v[t]
            net_kw = load_kw - pv_kw  # positief = tekort, negatief = overschot

            # -------------------------------------------------
            # CASE 1 — net_kw > target_peak → peak shaving
            # -------------------------------------------------
            if net_kw > target_peak:
                required_kw = net_kw - target_peak
                discharge_kw = min(required_kw, P)

                # kWh die uit batterij moet komen
                if eta_d > 0:
                    discharge_kwh_from_batt = discharge_kw * dt / eta_d
                else:
                    discharge_kwh_from_batt = 0.0

                # respecteer SoC-planning (soc_plan) + E_min
                lower_bound = max(E_min, soc_min_required)
                if soc - discharge_kwh_from_batt < lower_bound:
                    discharge_kwh_from_batt = max(0.0, soc - lower_bound)

                # effectieve geleverde kW naar load
                if dt > 0:
                    real_kw = discharge_kwh_from_batt * eta_d / dt
                else:
                    real_kw = 0.0

                soc -= discharge_kwh_from_batt

                # resterend tekort → net import
                grid_kw = load_kw - pv_kw - real_kw
                if grid_kw < 0:
                    grid_kw = 0.0

                import_profile[t] = grid_kw
                export_profile[t] = 0.0

            # -------------------------------------------------
            # CASE 2 — net_kw <= target_peak → normaal gedrag
            # + eventueel laden bij PV-overschot
            # -------------------------------------------------
            else:
                net_surplus_kw = pv_kw - load_kw

                if net_surplus_kw > 0:
                    # Laden tot P of totdat E_max bereikt is
                    charge_kw = min(net_surplus_kw, P)
                    charge_kwh = charge_kw * dt * eta_c

                    if soc + charge_kwh > E_max:
                        charge_kwh = max(0.0, E_max - soc)

                    soc += charge_kwh

                    # resterend overschot → export
                    if dt > 0 and eta_c > 0:
                        used_kw_equiv = charge_kwh / dt / eta_c
                    else:
                        used_kw_equiv = 0.0

                    export_kw = net_surplus_kw - used_kw_equiv
                    if export_kw < 0:
                        export_kw = 0.0

                    import_profile[t] = 0.0
                    export_profile[t] = export_kw

                else:
                    # klein tekort (maar onder target_peak) → gewoon import
                    import_profile[t] = -net_surplus_kw
                    export_profile[t] = 0.0

            # SoC opslaan
            soc_profile[t] = soc

            # maandpiek updaten
            if import_profile[t] > monthly_peaks_after[month]:
                monthly_peaks_after[month] = import_profile[t]

        return monthly_peaks_after, import_profile, export_profile, soc_profile


# ============================================================
# PHASE 2 — SOC-PLANNING (alleen gebruikt door BE-scenario)
# ============================================================

class PeakShavingPlanner:
    """
    Berekent een dynamische minimale SoC-curve (soc_plan) per tijdstap,
    op basis van baseline en target peaks.
    """

    @staticmethod
    def compute_required_reserve(
        baseline_peak_kw: float,
        target_peak_kw: float,
        timestep_hours: float = 0.25
    ) -> float:
        """
        Reserve (kWh) die nodig is om een piek te scheren.
        E = (baseline - target) * tijd
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
        """
        Geeft per tijdstap een minimale SoC (kWh) terug:
        E_min + maandelijkse reserve (voor peak shaving).
        """

        n = len(load.values)
        dt = load.dt_hours
        timestamps = load.timestamps

        soc_min_curve = [battery.E_min] * n

        monthly_reserve: List[float] = []
        for m in range(12):
            reserve = PeakShavingPlanner.compute_required_reserve(
                baseline_peaks[m],
                target_peaks[m],
                timestep_hours=dt
            )
            monthly_reserve.append(reserve)

        for i in range(n):
            month = timestamps[i].month - 1
            if month < 0 or month > 11:
                month = 0
            soc_min_curve[i] = battery.E_min + monthly_reserve[month]

        return soc_min_curve
