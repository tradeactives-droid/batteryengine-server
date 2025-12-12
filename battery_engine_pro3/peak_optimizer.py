# battery_engine_pro3/peak_optimizer.py

from typing import List, Tuple
from .battery_model import BatteryModel
from .types import TimeSeries


class PeakOptimizer:

    @staticmethod
    def compute_monthly_peaks(load: TimeSeries, pv: TimeSeries) -> List[float]:
        peaks = [0.0]*12
        for l, p, t in zip(load.values, pv.values, load.timestamps):
            peaks[t.month-1] = max(peaks[t.month-1], max(0, l-p))
        return peaks

    @staticmethod
    def compute_monthly_targets(peaks, reduction_factor=0.85):
        return [p * reduction_factor for p in peaks]

    @staticmethod
    def simulate_with_peak_shaving(load, pv, battery, targets, soc_plan=None):
        # 🔑 test vraagt deze signature
        soc_plan = soc_plan or [battery.E_min]*len(load.values)

        import_p, export_p, soc_p = [], [], []
        soc = battery.initial_soc_kwh
        dt = load.dt_hours
        monthly_after = [0.0]*12

        for l, p, t, smin in zip(load.values, pv.values, load.timestamps, soc_plan):
            net = l - p
            if net > targets[t.month-1]:
                needed = net - targets[t.month-1]
                discharge = min(needed, battery.power_kw)
                energy = min(discharge*dt, soc - smin)
                soc -= energy
                import_p.append(net - energy/dt)
            else:
                import_p.append(max(0, net))
            export_p.append(max(0, -net))
            soc_p.append(soc)
            monthly_after[t.month-1] = max(monthly_after[t.month-1], import_p[-1])

        return monthly_after, import_p, export_p, soc_p
