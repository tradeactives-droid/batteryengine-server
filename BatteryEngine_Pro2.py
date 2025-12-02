# ============================================================
# BATTERYENGINE PRO 2 — CLEAN & FIXED VERSION
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
    dynamic_prices: List[float] = None   # alleen dynamisch import per uur

    def get_import_price(self, i: int) -> float:
        """Voor dynamische tarieven pak uurprijs, anders vast."""
        if self.dynamic_prices:
            if i < len(self.dynamic_prices):
                return self.dynamic_prices[i]
            return self.dynamic_prices[-1]
        return self.import_price

    def get_export_price(self, i: int) -> float:
        """Exportprijs: dynamisch heeft meestal vaste export."""
        return self.export_price


# ============================================================
# BATTERYMODEL
# ============================================================

@dataclass
class BatteryModel:
    E_cap: float     # kWh
    P_max: float     # kW
    dod: float       # 0–1
    eta: float       # round-trip efficiency 0–1

    def __post_init__(self):
        self.E_min = self.E_cap * (1 - self.dod)
        self.E_max = self.E_cap

        # laad- en ontlaad-efficiëntie (symmetrisch)
        self.eta_c = self.eta**0.5
        self.eta_d = self.eta**0.5


# ============================================================
# SIMULATION ENGINE — FIXED COST CALCULATION
# ============================================================

class SimulationEngine:
    def __init__(self, load, pv, tariff: TariffModel, battery: BatteryModel = None):
        self.load = load
        self.pv = pv
        self.tariff = tariff
        self.battery = battery
        self.N = len(load)
        self.dt = 1.0  # uur

    # --------------------------------------------------------
    # Scenario zonder batterij
    # --------------------------------------------------------
    def simulate_no_battery(self):
        total_import = 0.0
        total_export = 0.0
        cost = 0.0

        for i in range(self.N):
            pv = self.pv[i]
            load = self.load[i]

            imp = max(0, load - pv)
            exp = max(0, pv - load)

            total_import += imp
            total_export += exp

            cost += imp * self.tariff.get_import_price(i)
            cost -= exp * self.tariff.get_export_price(i)

        return {
            "import": total_import,
            "export": total_export,
            "total_cost": cost
        }

    # --------------------------------------------------------
    # Scenario met batterij — volledig gerepareerd
    # --------------------------------------------------------
    def simulate_with_battery(self):
        if self.battery is None:
            return self.simulate_no_battery()

        E = self.battery.E_min  # start bij minimale SoC

        total_import = 0.0
        total_export = 0.0
        cost = 0.0

        for i in range(self.N):
            pv = self.pv[i]
            load = self.load[i]
            net = pv - load

            # PV > load → batterij laden, rest export
            if net > 0:
                max_charge = self.battery.P_max * self.dt
                charge_space = self.battery.E_max - E
                charge = min(net, max_charge, charge_space / self.battery.eta_c)

                # laad
                if charge > 0:
                    E += charge * self.battery.eta_c
                    net -= charge

                # overblijvende net → export
                export = max(0, net)
                total_export += export
                cost -= export * self.tariff.get_export_price(i)

            else:
                # load > pv → batterij ontladen
                deficit = -net

                max_discharge = self.battery.P_max * self.dt
                available_discharge = (E - self.battery.E_min) * self.battery.eta_d

                discharge = min(deficit, max_discharge, available_discharge)

                if discharge > 0:
                    E -= discharge / self.battery.eta_d
                    deficit -= discharge

                # resterende tekort → import
                imp = max(0, deficit)
                total_import += imp
                cost += imp * self.tariff.get_import_price(i)

        return {
            "import": total_import,
            "export": total_export,
            "total_cost": cost
        }


# ============================================================
# Scenario engine
# ============================================================

class ScenarioEngine:
    def __init__(self, load, pv, tariffs: Dict[str, TariffModel], battery: BatteryModel):
        self.load = load
        self.pv = pv
        self.tariffs = tariffs
        self.battery = battery

    # -------------------------------------------
    # A1 – huidige situatie MET saldering
    # -------------------------------------------
    def scenario_A1(self, current_tariff: str):
        tariff = self.tariffs[current_tariff]
        sim = SimulationEngine(self.load, self.pv, tariff)
        r = sim.simulate_no_battery()

        imp = r["import"]
        exp = r["export"]

        net = imp - exp

        # Dynamisch gebruikt uurprijzen
        if tariff.dynamic_prices:
            # netto * gewogen gemiddelde importprijs (benadering)
            avg_price = sum(tariff.dynamic_prices) / len(tariff.dynamic_prices)
            if net >= 0:
                return net * avg_price
            else:
                return net * tariff.export_price  # export negatief → geld terug

        # Enkel / Dag-Nacht
        if net >= 0:
            return net * tariff.import_price
        else:
            return net * tariff.export_price

    # -------------------------------------------
    # B1 – toekomst zonder batterij
    # -------------------------------------------
    def scenario_B1_all(self):
        out = {}
        for key, tariff in self.tariffs.items():
            sim = SimulationEngine(self.load, self.pv, tariff)
            out[key] = sim.simulate_no_battery()
        return out

    # -------------------------------------------
    # C1 – toekomst MET batterij
    # -------------------------------------------
    def scenario_C1_all(self):
        out = {}
        for key, tariff in self.tariffs.items():
            sim = SimulationEngine(self.load, self.pv, tariff, self.battery)
            out[key] = sim.simulate_with_battery()
        return out


# ============================================================
# PUBLIC API FUNCTION
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
        "dynamisch": TariffModel("dynamisch", 0, p_export_dyn, dynamic_prices=prices_dyn),
    }

    battery = BatteryModel(E, P, DoD, eta_rt)
    SE = ScenarioEngine(load_kwh, pv_kwh, tariffs, battery)

    A1 = SE.scenario_A1(current_tariff)
    B1 = SE.scenario_B1_all()
    C1 = SE.scenario_C1_all()

    return {
        "A1_current": A1 + vastrecht,
        "A1_per_tariff": {
            "enkel": SE.scenario_A1("enkel") + vastrecht,
            "dag_nacht": SE.scenario_A1("dag_nacht") + vastrecht,
            "dynamisch": SE.scenario_A1("dynamisch") + vastrecht
        },

        "B1_future_no_batt": B1[current_tariff]["total_cost"] + vastrecht,
        "C1_future_with_batt": C1[current_tariff]["total_cost"] + vastrecht,

        "S2_enkel": {**B1["enkel"], "total_cost": B1["enkel"]["total_cost"] + vastrecht},
        "S2_dn":    {**B1["dag_nacht"], "total_cost": B1["dag_nacht"]["total_cost"] + vastrecht},
        "S2_dyn":   {**B1["dynamisch"], "total_cost": B1["dynamisch"]["total_cost"] + vastrecht},

        "S3_enkel": {**C1["enkel"], "total_cost": C1["enkel"]["total_cost"] + vastrecht},
        "S3_dn":    {**C1["dag_nacht"], "total_cost": C1["dag_nacht"]["total_cost"] + vastrecht},
        "S3_dyn":   {**C1["dynamisch"], "total_cost": C1["dynamisch"]["total_cost"] + vastrecht},

        "vastrecht": vastrecht
    }
