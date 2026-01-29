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
        allow_grid_charge: bool = False,
    ):
        self.load = load
        self.pv = pv
        self.battery = battery
        self.prices = prices_dyn
        self.dt = load.dt_hours
        self.allow_grid_charge = allow_grid_charge

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
        soc = batt.initial_soc_kwh

        # --------------------------------------------------
        # STRATEGISCHE SOC-RESERVE (realistisch EMS-gedrag)
        # --------------------------------------------------
        reserve_frac = 0.20  # 20% van bruikbare capaciteit
        E_reserve = batt.E_min + reserve_frac * (batt.E_max - batt.E_min)
        
        import_p = []
        export_p = []
        soc_p = []

        dt = self.dt  # uren per timestep
        prices = self.prices or []

        for i, (load_kwh, pv_kwh) in enumerate(zip(self.load.values, self.pv.values)):
            price = prices[i] if i < len(prices) else None

            import_kwh = 0.0
            export_kwh = 0.0

            # ==================================================
            # 1️⃣ PV → DIRECT EIGEN VERBRUIK
            # ==================================================
            load_remaining = max(0.0, load_kwh - pv_kwh)
            pv_surplus = max(0.0, pv_kwh - load_kwh)

            # ==================================================
            # 2️⃣ BATTERIJ ONTLAADT NAAR LOAD
            # Dynamisch: bij hoge prijs altijd,
            # anders alleen als SOC boven reserve zit
            # ==================================================
            allow_discharge = True

            if self.prices and price is not None and self.price_high is not None:
                if price < self.price_high:
                    # alleen ontladen als er echt ruimte is boven reserve
                    if soc <= E_reserve:
                        allow_discharge = False

            if allow_discharge and load_remaining > 0 and soc > E_reserve:

                max_deliverable = min(
                    batt.P_max * dt,
                    (soc - batt.E_min) * batt.eta_discharge
                )

                delivered = min(load_remaining, max_deliverable)

                soc -= delivered / batt.eta_discharge
                load_remaining -= delivered

            # ==================================================
            # 3️⃣ BATTERIJ LADEN MET PV-OVERSCHOT
            # ==================================================
            if pv_surplus > 0 and soc < batt.E_max:
                charge = min(
                    pv_surplus,
                    batt.P_max * dt,
                    batt.E_max - soc,
                )
                soc += charge * batt.eta_charge
                pv_surplus -= charge

            # ==================================================
            # 4️⃣ PRIJS-GESTUURD NET-LADEN (ARBITRAGE)
            # Laden tot target SOC, niet altijd 100%
            # ==================================================
            if (
                self.allow_grid_charge
                and price is not None
                and self.price_low is not None
                and price < self.price_low
            ):
                target_soc = batt.E_min + 0.80 * (batt.E_max - batt.E_min)

                if soc < target_soc:
                    charge = min(
                        batt.P_max * dt,
                        target_soc - soc,
                    )
                    soc += charge * batt.eta_charge
                    import_kwh += charge

            # ==================================================
            # 5️⃣ REST → NET
            # ==================================================
            import_kwh += load_remaining
            export_kwh += pv_surplus

            # =========================
            # NUMERIEKE GUARDRAILS
            # =========================
            soc = min(max(soc, batt.E_min), batt.E_max)

            if load_remaining < 0:
                load_remaining = 0.0

            if pv_surplus < 0:
                pv_surplus = 0.0
            
            import_p.append(import_kwh)
            export_p.append(export_kwh)
            soc_p.append(soc)

        return SimulationResult(
            import_kwh=sum(import_p),
            export_kwh=sum(export_p),
            import_profile=import_p,
            export_profile=export_p,
            soc_profile=soc_p,
            dt_hours=dt,
        )
