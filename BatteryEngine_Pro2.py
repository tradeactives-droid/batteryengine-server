# ============================================================
# BATTERYENGINE PRO 2 — CLEAN BACKEND ENGINE v2
# ============================================================

from dataclasses import dataclass
from typing import List, Dict


# ============================================================
# TARIEFMODEL
# ============================================================

@dataclass
class TariffModel:
    name: str
    import_price: float
    export_price: float
    dynamic_prices: List[float] = None   # uurprijzen voor dynamisch import

    def get_import_price(self, i: int) -> float:
        """Dynamisch tarief gebruikt uurprijs; anders vaste prijs."""
        if self.dynamic_prices:
            return self.dynamic_prices[i] if i < len(self.dynamic_prices) else self.dynamic_prices[-1]
        return self.import_price

    def get_export_price(self, i: int) -> float:
        return self.export_price


# ============================================================
# BATTERY MODEL
# ============================================================

@dataclass
class BatteryModel:
    E_cap: float     # kWh
    P_max: float     # kW
    dod: float       # DoD 0–1
    eta: float       # round-trip efficiency 0–1

    def __post_init__(self):
        self.E_min = self.E_cap * (1 - self.dod)
        self.E_max = self.E_cap
        self.eta_c = self.eta ** 0.5
        self.eta_d = self.eta ** 0.5


# ============================================================
# SIMULATIE ENGINE (ZONDER & MET BATTERIJ)
# ============================================================

class SimulationEngine:
    def __init__(self, load: List[float], pv: List[float], tariff: TariffModel, battery: BatteryModel = None):
        self.load = load
        self.pv = pv
        self.tariff = tariff
        self.battery = battery
        self.N = len(load)
        self.dt = 1.0  # urenstappen

    # -------------------------
    # Scenario zonder batterij
    # -------------------------
    def simulate_no_battery(self):
        total_import = 0.0
        total_export = 0.0

        for i in range(self.N):
            net = self.pv[i] - self.load[i]
            if net >= 0:
                total_export += net
            else:
                total_import += -net

        cost = 0.0
        for i in range(self.N):
            imp = max(0, self.load[i] - self.pv[i])
            exp = max(0, self.pv[i] - self.load[i])
            cost += imp * self.tariff.get_import_price(i)
            cost -= exp * self.tariff.get_export_price(i)

        return {
            "import": total_import,
            "export": total_export,
            "total_cost": cost
        }

    # -------------------------
    # Scenario MET batterij
    # -------------------------
    def simulate_with_battery(self):
        if self.battery is None:
            return self.simulate_no_battery()

        E = self.battery.E_min  # start SoC op minimum
        total_import = 0.0
        total_export = 0.0

        for i in range(self.N):
            load = self.load[i]
            pv = self.pv[i]
            net = pv - load

            if net > 0:
                # Overschot → batterij laden
                max_charge = self.battery.P_max * self.dt
                charge_space = self.battery.E_max - E
                charge = min(net, max_charge, charge_space / self.battery.eta_c)

                if charge > 0:
                    E += charge * self.battery.eta_c
                    net -= charge

                total_export += max(0, net)

            else:
                # Tekort → batterij ontladen
                deficit = -net
                max_discharge = self.battery.P_max * self.dt
                available_discharge = (E - self.battery.E_min) * self.battery.eta_d

                discharge = min(deficit, max_discharge, available_discharge)

                if discharge > 0:
                    E -= discharge / self.battery.eta_d
                    deficit -= discharge

                total_import += max(0, deficit)

        # -------------------------
        # Kostberekening — gebruik import/export van simulatie
        # -------------------------
        cost = 0.0
        for i in range(self.N):
            imp = max(0, self.load[i] - self.pv[i])
            exp = max(0, self.pv[i] - self.load[i])
            cost += imp * self.tariff.get_import_price(i)
            cost -= exp * self.tariff.get_export_price(i)

        return {
            "import": total_import,
            "export": total_export,
            "total_cost": cost
        }


# ============================================================
# SCENARIO ENGINE
# ============================================================

class ScenarioEngine:
    def __init__(self, load: List[float], pv: List[float], tariffs: Dict[str, TariffModel], battery: BatteryModel):
        self.load = load
        self.pv = pv
        self.tariffs = tariffs
        self.battery = battery

    # Huidige situatie — MET saldering
    def scenario_A1(self, current_tariff: str):
        tariff = self.tariffs[current_tariff]
        sim = SimulationEngine(self.load, self.pv, tariff)
        r = sim.simulate_no_battery()

        imp = r["import"]
        exp = r["export"]

        net = imp - exp
        if net >= 0:
            return net * tariff.import_price
        else:
            return -abs(net) * tariff.export_price

    # Toekomst zonder batterij
    def scenario_B1_all(self):
        out = {}
        for key, tariff in self.tariffs.items():
            sim = SimulationEngine(self.load, self.pv, tariff)
            out[key] = sim.simulate_no_battery()
        return out

    # Toekomst MET batterij
    def scenario_C1_all(self):
        out = {}
        for key, tariff in self.tariffs.items():
            sim = SimulationEngine(self.load, self.pv, tariff, self.battery)
            out[key] = sim.simulate_with_battery()
        return out


# ============================================================
# HOOFDFUNCTIE — wordt aangeroepen door main.py
# ============================================================

def compute_scenarios_v2(
    load_kwh: List[float],
    pv_kwh: List[float],
    prices_dyn: List[float],
    p_enkel_imp: float,
    p_enkel_exp: float,
    p_dag: float,
    p_nacht: float,
    p_exp_dn: float,
    p_export_dyn: float,
    E: float,
    P: float,
    DoD: float,
    eta_rt: float,
    vastrecht: float,
    current_tariff: str = "enkel"
):

    tariffs = {
        "enkel": TariffModel("enkel", p_enkel_imp, p_enkel_exp),
        "dag_nacht": TariffModel("dag_nacht", p_dag, p_exp_dn),
        "dynamisch": TariffModel("dynamisch", 0, p_export_dyn, dynamic_prices=prices_dyn)
    }

    batt = BatteryModel(E, P, DoD, eta_rt)
    SE = ScenarioEngine(load_kwh, pv_kwh, tariffs, batt)

    A1 = SE.scenario_A1(current_tariff)
    B1 = SE.scenario_B1_all()
    C1 = SE.scenario_C1_all()

    return {
        "A1_current": A1,
        "A1_per_tariff": {
            "enkel": SE.scenario_A1("enkel"),
            "dag_nacht": SE.scenario_A1("dag_nacht"),
            "dynamisch": SE.scenario_A1("dynamisch")
        },

        "B1_future_no_batt": B1[current_tariff]["total_cost"],
        "C1_future_with_batt": C1[current_tariff]["total_cost"],

        "S2_enkel": B1["enkel"],
        "S2_dn": B1["dag_nacht"],
        "S2_dyn": B1["dynamisch"],

        "S3_enkel": C1["enkel"],
        "S3_dn": C1["dag_nacht"],
        "S3_dyn": C1["dynamisch"],

        "vastrecht": vastrecht
    }
