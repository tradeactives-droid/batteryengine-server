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
