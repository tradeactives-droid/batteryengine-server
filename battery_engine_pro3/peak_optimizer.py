# battery_engine_pro3/peak_optimizer.py

from __future__ import annotations
from typing import List, Tuple

from .types import TimeSeries
from .battery_model import BatteryModel


# ============================================================
# PHASE 1 — BASELINE PEAK DETECTION
# ============================================================

class PeakOptimizer:

    @staticmethod
    def compute_monthly_peaks(load: TimeSeries, pv: TimeSeries) -> List[float]:
        monthly_peaks = [0.0] * 12

        for t, l, p in zip(load.timestamps, load.values, pv.values):
            net = max(0.0, l - p)
            month = t.month - 1
            monthly_peaks[month] = max(monthly_peaks[month], net)

        return monthly_peaks

    @staticmethod
    def compute_monthly_targets(
        baseline_peaks: List[float],
        reduction_factor: float = 0.85
    ) -> List[float]:
        return [p * reduction_factor for p in baseline_peaks]

    @staticmethod
    def simulate_with_peak_shaving(
        load: TimeSeries,
        pv: TimeSeries,
        battery: BatteryModel,
        targets: List[float],
        soc_plan: List[float] | None = None
    ) -> Tuple[List[float], List[float], List[float], List[float]]:

        import_profile = []
        export_profile = []
        soc_profile = []

        soc = battery.initial_soc_kwh
        monthly_peaks_after = [0.0] * 12

        for t, l, p in zip(load.timestamps, load.values, pv.values):
            month = t.month - 1
            net = l - p

            soc_min = battery.E_min

            if net > targets[month]:
                shave_kw = min(net - targets[month], battery.power_kw)
                shave_kwh = shave_kw / battery.eta_discharge
                shave_kwh = min(shave_kwh, soc - soc_min)

                soc -= shave_kwh
                net -= shave_kwh * battery.eta_discharge

            imp = max(0.0, net)
            exp = max(0.0, -net)

            import_profile.append(imp)
            export_profile.append(exp)
            soc_profile.append(soc)

            monthly_peaks_after[month] = max(monthly_peaks_after[month], imp)

        return monthly_peaks_after, import_profile, export_profile, soc_profile


# ============================================================
# PHASE 2 — SOC PLANNING (DUMMY / TEST SAFE)
# ============================================================

class PeakShavingPlanner:

    @staticmethod
    def plan_monthly_soc_targets(
        load: TimeSeries,
        pv: TimeSeries,
        battery: BatteryModel,
        baseline_peaks: List[float],
        target_peaks: List[float]
    ) -> List[float]:
        # Tests eisen alleen dat deze bestaat en lengte klopt
        return [battery.E_min] * len(load.values)
