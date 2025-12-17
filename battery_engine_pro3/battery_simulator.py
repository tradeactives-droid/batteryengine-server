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
        """
        Fysisch correcte batterij-simulatie.

        Regels:
        - Batterij levert alleen aan het huis (nooit aan het net)
        - Export naar het net komt uitsluitend van PV
        - Batterij kan laden van PV en (bij lage prijs) van het net
        - Import/export worden pas aan het einde bepaald
        """

        if self.battery is None:
            return self.simulate_no_battery()

        batt = self.battery
        soc = batt.E_min

        import_profile = []
        export_profile = []
        soc_profile = []

        prices = self.prices or []
        dt = self.dt  # ← altijd via simulator, NIET via load

        for i, (load_kwh, pv_kwh) in enumerate(zip(self.load.values, self.pv.values)):

            # =========================
            # 1️⃣ PV → HUIS
            # =========================
            pv_to_load = min(load_kwh, pv_kwh)
            load_remaining = load_kwh - pv_to_load
            pv_surplus = pv_kwh - pv_to_load

            # =========================
            # 2️⃣ BATTERIJ → HUIS
            # =========================
            batt_to_load = 0.0
            if load_remaining > 0 and soc > batt.E_min:
                batt_to_load = min(
                    load_remaining,
                    batt.P_max * dt,
                    soc - batt.E_min,
                )
                soc -= batt_to_load
                load_remaining -= batt_to_load

            # =========================
            # 3️⃣ PV → BATTERIJ
            # =========================
            pv_to_batt = 0.0
            if pv_surplus > 0 and soc < batt.E_max:
                pv_to_batt = min(
                    pv_surplus,
                    batt.P_max * dt,
                    batt.E_max - soc,
                )
                soc += pv_to_batt * batt.eta_charge
                pv_surplus -= pv_to_batt

            # =========================
            # 4️⃣ NET → BATTERIJ (ARBITRAGE)
            # =========================
            grid_to_batt = 0.0
            price_now = prices[i] if i < len(prices) else None

            if (
                price_now is not None
                and self.price_low is not None
                and price_now < self.price_low
                and soc < batt.E_max
            ):
                grid_to_batt = min(
                    batt.P_max * dt,
                    batt.E_max - soc,
                )
                soc += grid_to_batt * batt.eta_charge

            # =========================
            # 5️⃣ NETAFHANDELING
            # =========================
            import_kwh = load_remaining + grid_to_batt
            export_kwh = pv_surplus  # ⚠️ batterij exporteert NOOIT

            import_profile.append(import_kwh)
            export_profile.append(export_kwh)
            soc_profile.append(soc)

        return SimulationResult(
            import_kwh=sum(import_profile),
            export_kwh=sum(export_profile),
            import_profile=import_profile,
            export_profile=export_profile,
            soc_profile=soc_profile,
            dt_hours=dt,
        )
