# battery_engine_pro3/peak_optimizer.py

from __future__ import annotations
from typing import List, Tuple

from .battery_model import BatteryModel
from .types import TimeSeries


# ============================================================
# PEAK OPTIMIZER — COMPLETE & TEST-COMPATIBLE VERSION
# ============================================================

class PeakOptimizer:
    """
    Bevat:
    - compute_monthly_peaks()
    - compute_monthly_targets()
    - simulate_with_peak_shaving()  (met fallback soc-plan voor tests)
    """

    # --------------------------------------------------------
    # 1. BASELINE PEAK DETECTION
    # --------------------------------------------------------
    @staticmethod
    def compute_monthly_peaks(load: TimeSeries, pv: TimeSeries) -> List[float]:
        """
        Berekent voor elk van de 12 maanden de maximale net-afname (kW).
        net = load - pv  (negatief → 0)
        """
        n = len(load.values)
        ts = load.timestamps
        monthly = [0.0] * 12

        for i in range(n):
            net = load.values[i] - pv.values[i]
            if net < 0:
                net = 0.0
            m = ts[i].month - 1
            if net > monthly[m]:
                monthly[m] = net

        return monthly

    @staticmethod
    def compute_monthly_targets(
        baseline_peaks: List[float],
        reduction_factor: float = 0.85
    ) -> List[float]:
        """
        Reduceer elke maandelijke piek met given factor.
        bvb 0.85 = 15% reductie.
        """
        return [p * reduction_factor for p in baseline_peaks]

    # --------------------------------------------------------
    # 2. MAIN PEAK SHAVING SIMULATION
    # --------------------------------------------------------
    @staticmethod
    def simulate_with_peak_shaving(
        load: TimeSeries,
        pv: TimeSeries,
        battery: BatteryModel,
        monthly_targets: List[float],
        soc_plan: List[float] | None = None
    ) -> Tuple[List[float], List[float], List[float], List[float]]:
        """
        Simulatie:

        - Bij net_kw > target_peak: batterij ontladen
        - Bij overschot PV: batterij laden
        - Houdt rekening met dynamische SoC-limiet (soc_plan)
        - Tests geven géén soc_plan → dus fallback nodig
        """

        n = len(load.values)
        ts = load.timestamps
        dt = load.dt_hours

        load_v = load.values
        pv_v = pv.values

        # Batterij parameters
        P = battery.power_kw
        eta_c = battery.eta_charge
        eta_d = battery.eta_discharge
        E_min = battery.E_min
        E_max = battery.E_max

        soc = battery.initial_soc_kwh

        # Fallback SoC-plan voor tests (geen peak shaving planning)
        if soc_plan is None:
            soc_plan = [E_min] * n

        # Output arrays
        import_profile = [0.0] * n
        export_profile = [0.0] * n
        soc_profile = [0.0] * n
        monthly_peaks_after = [0.0] * 12

        # -----------------------------
        # MAIN TIMESTEP LOOP
        # -----------------------------
        for t in range(n):
            m = ts[t].month - 1
            target_peak = monthly_targets[m]
            soc_min_required = soc_plan[t]

            load_kw = load_v[t]
            pv_kw = pv_v[t]
            net_kw = load_kw - pv_kw

            # -----------------------------------------------------
            # CASE A — Peak shaving (net_kw > target)
            # -----------------------------------------------------
            if net_kw > target_peak:
                required_kw = net_kw - target_peak
                discharge_kw = min(required_kw, P)

                discharge_kwh_raw = discharge_kw * dt / eta_d

                if soc - discharge_kwh_raw < soc_min_required:
                    discharge_kwh_raw = max(0.0, soc - soc_min_required)

                delivered_kw = discharge_kwh_raw * eta_d / dt
                soc -= discharge_kwh_raw

                grid_kw = load_kw - pv_kw - delivered_kw
                if grid_kw < 0:
                    grid_kw = 0.0

                import_profile[t] = grid_kw
                export_profile[t] = 0.0

            # -----------------------------------------------------
            # CASE B — Niet boven target: normaal gedrag
            # -----------------------------------------------------
            else:
                surplus_kw = pv_kw - load_kw

                if surplus_kw > 0:
                    # Laden met overschot
                    charge_kw = min(surplus_kw, P)
                    charge_kwh = charge_kw * dt * eta_c

                    if soc + charge_kwh > E_max:
                        charge_kwh = E_max - soc

                    soc += charge_kwh

                    export_kw = surplus_kw - (charge_kwh / dt / eta_c)
                    if export_kw < 0:
                        export_kw = 0.0

                    export_profile[t] = export_kw
                    import_profile[t] = 0.0

                else:
                    # Klein tekort → grid import
                    import_profile[t] = -surplus_kw
                    export_profile[t] = 0.0

            soc_profile[t] = soc

            # Update gerealiseerde maandpiek
            grid_load_kw = import_profile[t]
            if grid_load_kw > monthly_peaks_after[m]:
                monthly_peaks_after[m] = grid_load_kw

        return monthly_peaks_after, import_profile, export_profile, soc_profile
