from __future__ import annotations
from typing import List
from .types import TimeSeries
from .battery_model import BatteryModel


class PeakOptimizer:

    @staticmethod
    def compute_monthly_peaks(load: TimeSeries, pv: TimeSeries) -> List[float]:
        peaks = [0.0] * 12
        for t, l, p in zip(load.timestamps, load.values, pv.values):
            net = max(0.0, l - p)
            m = t.month - 1
            peaks[m] = max(peaks[m], net)
        return peaks

    @staticmethod
    def compute_monthly_targets(baseline: List[float], reduction_factor: float = 0.85):
        return [p * reduction_factor for p in baseline]

    @staticmethod
    def simulate_with_peak_shaving(
        load,
        pv,
        battery: BatteryModel,
        targets,
        soc_plan=None
    ):
        imp, exp, soc = [], [], []
        soc_kwh = battery.initial_soc_kwh
        peaks = [0.0] * 12

        for t, l, p in zip(load.timestamps, load.values, pv.values):
            m = t.month - 1
            net = l - p

            if net > targets[m]:
                shave = min(net - targets[m], battery.P_max)
                shave_kwh = shave / battery.eta_discharge
                shave_kwh = min(shave_kwh, soc_kwh - battery.E_min)
                soc_kwh -= shave_kwh
                net -= shave_kwh * battery.eta_discharge

            imp.append(max(0.0, net))
            exp.append(max(0.0, -net))
            soc.append(soc_kwh)
            peaks[m] = max(peaks[m], imp[-1])

        return peaks, imp, exp, soc

    # ============================================================
    # Backwards compatibility voor ScenarioRunner & tests
    # ============================================================

    class PeakShavingPlanner:
        """
        Wrapper zodat ScenarioRunner kan blijven werken
        zonder PeakOptimizer te breken.
        """

        @staticmethod
        def plan_monthly_soc_targets(
            load: TimeSeries,
            pv: TimeSeries,
            battery: BatteryModel,
            baseline_peaks,
            target_peaks
         ):
            # eenvoudige default: geen extra reserve boven E_min
            return [battery.E_min] * len(load.values)


    # Alias zodat beide namen werken
    
    # ============================================================
    # Backwards compatibility aliases (tests & ScenarioRunner)
    # ============================================================

    class PeakShavingPlanner:
        @staticmethod
        def plan_monthly_soc_targets(
            load,
            pv,
            battery,
            baseline_peaks,
            target_peaks
        ):
            # eenvoudige default: geen extra reserve
            return [battery.E_min] * len(load.values)
