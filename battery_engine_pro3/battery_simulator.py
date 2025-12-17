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

        batt = self.battery

        soc = batt.E_min   # start veilig op minimum SoC

        import_p: List[float] = []
        export_p: List[float] = []
        soc_p: List[float] = []

        for i, (l, p) in enumerate(zip(self.load.values, self.pv.values)):
            price = self.prices[i] if self.prices and i < len(self.prices) else None
            net = l - p  # POSITIEF = vraag, NEGATIEF = overschot

            # ==================================================
            # 1️⃣ PRIJS-GESTUURDE ARBITRAGE (DYNAMISCH)
            # ==================================================
            if (
                price is not None
                and self.price_low is not None
                and self.price_high is not None
            ):
                # 🔋 Laden bij lage prijs
                if price < self.price_low and soc < batt.E_max:
                    charge_kw = min(batt.P_max, batt.E_max - soc)
                    soc += charge_kw * batt.eta_charge
                    import_p.append(charge_kw)
                    export_p.append(0.0)
                    soc_p.append(soc)
                    continue

                # 🔌 Ontladen bij hoge prijs
                if price > self.price_high and soc > batt.E_min:
                    discharge_kw = min(batt.P_max, soc - batt.E_min)
                    soc -= discharge_kw
                    import_p.append(0.0)
                    export_p.append(discharge_kw * batt.eta_discharge)
                    soc_p.append(soc)
                    continue

            # ==================================================
            # 2️⃣ NORMAAL GEDRAG (PV → LOAD → BATTERIJ)
            # ==================================================
            if net > 0:
                # Ontladen om load te dekken
                discharge = min(net, batt.P_max, soc - batt.E_min)
                soc -= discharge
                import_p.append(max(0.0, net - discharge))
                export_p.append(0.0)
            else:
                # Laden met PV-overschot
                surplus = -net
                charge = min(surplus, batt.P_max, batt.E_max - soc)
                soc += charge * batt.eta_charge
                import_p.append(0.0)
                export_p.append(max(0.0, surplus - charge))

            soc_p.append(soc)

        return SimulationResult(
            import_kwh=sum(import_p),
            export_kwh=sum(export_p),
            import_profile=import_p,
            export_profile=export_p,
            soc_profile=soc_p,
            dt_hours=self.dt,
        )
