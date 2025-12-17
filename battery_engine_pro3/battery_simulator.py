# battery_engine_pro3/battery_simulator.py

from __future__ import annotations
from dataclasses import dataclass
from typing import List, Optional

from .battery_model import BatteryModel
from .types import TimeSeries


# ============================================================
# RESULT OBJECT
# ============================================================

@dataclass
class SimulationResult:
    import_kwh: float
    export_kwh: float
    import_profile: List[float]
    export_profile: List[float]
    soc_profile: List[float]
    dt_hours: float


# ============================================================
# BATTERY SIMULATOR
# ============================================================

class BatterySimulator:
    """
    Simuleert energieflows:
    - zonder batterij
    - met batterij
    - met optionele prijs-gestuurde arbitrage (dynamisch)
    """

    def __init__(
        self,
        load: TimeSeries,
        pv: TimeSeries,
        battery: Optional[BatteryModel],
        prices_dyn: Optional[List[float]] = None,
    ):
        self.load = load
        self.pv = pv
        self.battery = battery
        self.prices = prices_dyn
        self.dt = load.dt_hours

        # Voor arbitrage: percentielen bepalen (veilig, zonder numpy)
        if self.prices and len(self.prices) > 0:
            prices_sorted = sorted(self.prices)
            n = len(prices_sorted)
            self.price_low = prices_sorted[int(0.30 * n)]   # P30
            self.price_high = prices_sorted[int(0.75 * n)]  # P75
        else:
            self.price_low = None
            self.price_high = None

    # -------------------------------------------------
    # ZONDER BATTERIJ
    # -------------------------------------------------
    def simulate_no_battery(self) -> SimulationResult:
        import_p = []
        export_p = []
        soc_p = [0.0] * len(self.load.values)

        for l, p in zip(self.load.values, self.pv.values):
            net = l - p
            import_p.append(max(0.0, net))
            export_p.append(max(0.0, -net))

        return SimulationResult(
            import_kwh=sum(import_p),
            export_kwh=sum(export_p),
            import_profile=import_p,
            export_profile=export_p,
            soc_profile=soc_p,
            dt_hours=self.dt,
        )

    # -------------------------------------------------
    # MET BATTERIJ (PV + PRIJS-GESTUURDE ARBITRAGE)
    # -------------------------------------------------
    def simulate_with_battery(self) -> SimulationResult:
        if self.battery is None:
            return self.simulate_no_battery()

        import_profile = []
        export_profile = []
        soc_profile = []

        soc = self.battery.initial_soc_kwh
        dt = self.load.dt_hours

        prices = self.prices or []

        for i, (load_kwh, pv_kwh) in enumerate(zip(self.load.values, self.pv.values)):
            net = load_kwh - pv_kwh

            price_now = prices[i] if i < len(prices) else None
            price_future = (
                prices[i + 1] if i + 1 < len(prices) else price_now
            )

            # ==========================
            # 1️⃣ DIRECT EIGEN VERBRUIK
            # ==========================
            if net > 0:
                discharge_kwh = min(
                    net,
                    self.battery.power_kw * dt,
                    soc - self.battery.E_min
                )
                soc -= discharge_kwh
                net -= discharge_kwh

            # ==========================
            # 2️⃣ DYNAMISCHE ARBITRAGE (NET ←→ BATTERIJ)
            # ==========================
            if price_now is not None and price_future is not None:
                if price_future > price_now:
                    charge_kwh = min(
                        self.battery.power_kw * dt,
                        self.battery.E_max - soc
                    )
                    soc += charge_kwh
                    net += charge_kwh

            # ==========================
            # 3️⃣ NETAFHANDELING
            # ==========================
            imp = max(0.0, net)
            exp = max(0.0, -net)

            import_profile.append(imp)
            export_profile.append(exp)
            soc_profile.append(soc)

        return SimulationResult(
            import_kwh=sum(import_profile),
            export_kwh=sum(export_profile),
            import_profile=import_profile,
            export_profile=export_profile,
            soc_profile=soc_profile,
            dt_hours=dt,
            )
