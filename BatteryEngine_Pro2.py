# ============================================================
# BATTERYENGINE PRO 2 — CLEAN & FIXED VERSION (incl. ROI)
# ============================================================

from dataclasses import dataclass
from typing import List, Dict, Optional

# ============================================================
# AUTOMATISCHE RESOLUTIE-DETECTIE (uur / kwartier)
# ============================================================

def detect_resolution(load: List[float]) -> float:
    """
    Detecteert grofweg of de data per uur (dt = 1.0)
    of per kwartier (dt = 0.25) is, op basis van lengte.
    """
    N = len(load)

    # Typische waardes:
    # - Uurdata: 8760 (niet-schrikkeljaar)
    # - Kwartierdata: 35040 (4 * 8760)
    if N >= 30000:
        return 0.25  # bijna zeker kwartierdata
    else:
        return 1.0   # aannemen: uurdata

# ============================================================
# TARIEFMODEL
# ============================================================

@dataclass
class TariffModel:
    name: str
    import_price: float
    export_price: float
    dynamic_prices: Optional[List[float]] = None  # alleen dynamisch: uurprijzen

    def get_import_price(self, i: int) -> float:
        """Voor dynamische tarieven pak uurprijs, anders vaste prijs."""
        if self.dynamic_prices:
            if 0 <= i < len(self.dynamic_prices):
                return self.dynamic_prices[i]
            # als index buiten range valt → laatste bekende prijs
            return self.dynamic_prices[-1]
        return self.import_price

    def get_export_price(self, i: int) -> float:
        """Exportprijs: bij dynamisch meestal vast per kWh."""
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
        # minimale / maximale energie-inhoud
        self.E_min = self.E_cap * (1 - self.dod)
        self.E_max = self.E_cap

        # laad- en ontlaad-efficiëntie (symmetrisch)
        # eta_rt = eta_c * eta_d → neem wortel
        self.eta_c = self.eta ** 0.5
        self.eta_d = self.eta ** 0.5


# ============================================================
# SIMULATION ENGINE
# ============================================================

class SimulationEngine:
    def __init__(
        self,
        load: List[float],
        pv: List[float],
        tariff: TariffModel,
        battery: Optional[BatteryModel] = None,
        dt: Optional[float] = None
    ):
        self.load = load
        self.pv = pv
        self.tariff = tariff
        self.battery = battery
        self.N = len(load)

        # Als dt niet is opgegeven → automatisch bepalen (uur of kwartier)
        if dt is None:
            self.dt = detect_resolution(load)
        else:
            self.dt = dt

    # --------------------------------------------------------
    # Scenario zonder batterij
    # --------------------------------------------------------
    def simulate_no_battery(self):
        total_import = 0.0
        total_export = 0.0
        cost = 0.0

        for i in range(self.N):
            load_i = self.load[i]
            pv_i = self.pv[i]

            imp = max(0.0, load_i - pv_i)
            exp = max(0.0, pv_i - load_i)

            total_import += imp
            total_export += exp

            cost += imp * self.tariff.get_import_price(i)
            cost -= exp * self.tariff.get_export_price(i)

        return {
            "import": total_import,
            "export": total_export,
            "total_cost": cost,
        }

    # --------------------------------------------------------
    # Scenario met batterij (uur-voor-uur, dynamiek inbegrepen)
    # --------------------------------------------------------
    def simulate_with_battery(self):
        if self.battery is None:
            return self.simulate_no_battery()

        E = self.battery.E_min  # start op minimum-SoC
        total_import = 0.0
        total_export = 0.0

        # Profielen nodig voor correcte kosten-berekening per uur
        import_profile = [0.0] * self.N
        export_profile = [0.0] * self.N

        for i in range(self.N):
            load_i = self.load[i]
            pv_i = self.pv[i]
            net = pv_i - load_i  # + = overschot, - = tekort

            if net > 0:
                # -------------------------------
                # Overschot → laad batterij eerst
                # -------------------------------
                max_charge = self.battery.P_max * self.dt
                charge_space = self.battery.E_max - E  # kWh ruimte
                charge = min(net, max_charge, charge_space / self.battery.eta_c)

                if charge > 0:
                    E += charge * self.battery.eta_c
                    net -= charge

                # rest-overschot = export
                export = max(0.0, net)
                total_export += export
                export_profile[i] = export

            else:
                # -------------------------------
                # Tekort → ontlaad batterij eerst
                # -------------------------------
                deficit = -net  # positief getal
                max_discharge = self.battery.P_max * self.dt
                available_discharge = (E - self.battery.E_min) * self.battery.eta_d

                discharge = min(deficit, max_discharge, available_discharge)

                if discharge > 0:
                    E -= discharge / self.battery.eta_d
                    deficit -= discharge

                # rest-tekort = import uit net
                imp = max(0.0, deficit)
                total_import += imp
                import_profile[i] = imp

        # Kosten: per uur, met de juiste dynamische / vaste prijzen
        cost = 0.0
        for i in range(self.N):
            imp = import_profile[i]
            exp = export_profile[i]
            cost += imp * self.tariff.get_import_price(i)
            cost -= exp * self.tariff.get_export_price(i)

        return {
            "import": total_import,
            "export": total_export,
            "total_cost": cost,
        }

    # --------------------------------------------------------
    # Peak shaving – reduceer kwartier/uur piekvermogen
    # --------------------------------------------------------
    def compute_peak_shaving(self):
        if self.battery is None:
            # Zonder batterij: piek = peak_no = peak_with
            peak = max(max(self.load[i] - self.pv[i], 0) for i in range(self.N))
            return peak, peak

        E = self.battery.E_min
        dt = self.dt

        peak_no_batt = 0.0
        peak_with_batt = 0.0

        for i in range(self.N):
            load_i = self.load[i]
            pv_i = self.pv[i]

            net_load = max(load_i - pv_i, 0)
            peak_no_batt = max(peak_no_batt, net_load)

            # Batterij helpt pieken afvlakken
            available_discharge = (E - self.battery.E_min) * self.battery.eta_d
            max_discharge = self.battery.P_max * dt
            discharge = min(net_load, available_discharge, max_discharge)

            # update batterij
            if discharge > 0:
                E -= discharge / self.battery.eta_d
                net_load -= discharge

            peak_with_batt = max(peak_with_batt, net_load)

        return peak_no_batt, peak_with_batt

    # --------------------------------------------------------
    # FLUVIUS 2025 — Peak shaving per MAAND
    # --------------------------------------------------------
    def compute_monthly_peaks(self):
        """
        Retourneert:
        - monthly_peak_no_batt: lijst van 12 maandpieken zonder batterij
        - monthly_peak_with_batt: lijst van 12 maandpieken met batterij
        """

        N = self.N
        dt = self.dt   # 1 uur of 0.25 uur

        # Aantal stappen per maand
        if dt == 1.0:
            steps_per_month = [31*24, 28*24, 31*24, 30*24, 31*24, 30*24,
                               31*24, 31*24, 30*24, 31*24, 30*24, 31*24]
        else:  # kwartierdata
            steps_per_month = [31*96, 28*96, 31*96, 30*96, 31*96, 30*96,
                               31*96, 31*96, 30*96, 31*96, 30*96, 31*96]

        monthly_peak_no_batt = []
        monthly_peak_with_batt = []

        idx = 0
        for m in range(12):
            M = steps_per_month[m]
            end = min(idx + M, N)

            E = self.battery.E_min   # reset per maand

            peak_no = 0.0
            peak_yes = 0.0

            for i in range(idx, end):

                load_i = self.load[i]
                pv_i   = self.pv[i]

                net_load = max(load_i - pv_i, 0)
                peak_no = max(peak_no, net_load)

                # batterij
                available_discharge = (E - self.battery.E_min) * self.battery.eta_d
                max_discharge = self.battery.P_max * dt
                discharge = min(net_load, available_discharge, max_discharge)

                if discharge > 0:
                    E -= discharge / self.battery.eta_d
                    net_load -= discharge

                peak_yes = max(peak_yes, net_load)

            monthly_peak_no_batt.append(peak_no)
            monthly_peak_with_batt.append(peak_yes)

            idx = end
            if idx >= N:
                break

        # Vul maanden aan als dataset korter was
        while len(monthly_peak_no_batt) < 12:
            monthly_peak_no_batt.append(0)
            monthly_peak_with_batt.append(0)

        return monthly_peak_no_batt, monthly_peak_with_batt

# ============================================================
# SCENARIO ENGINE
# ============================================================

class ScenarioEngine:
    def __init__(
        self,
        load: List[float],
        pv: List[float],
        tariffs: Dict[str, TariffModel],
        battery: BatteryModel
    ):
        self.load = load
        self.pv = pv
        self.tariffs = tariffs
        self.battery = battery

    # -------------------------------------------
    # A1 – huidige situatie
    # Enkel / Dag-nacht: MET saldering
    # Dynamisch: GEEN saldering (uur-voor-uur)
    # -------------------------------------------
    def scenario_A1(self, current_tariff: str) -> float:
        tariff = self.tariffs[current_tariff]

        # Dynamisch: geen saldering → direct uur-voor-uur kosten
        if tariff.dynamic_prices:
            sim = SimulationEngine(self.load, self.pv, tariff)
            r = sim.simulate_no_battery()
            return r["total_cost"]

        # Enkel / Dag-nacht: jaarlijkse saldering
        sim = SimulationEngine(self.load, self.pv, tariff)
        r = sim.simulate_no_battery()

        imp = r["import"]
        exp = r["export"]
        net = imp - exp  # kWh netto van net

        if net >= 0:
            return net * tariff.import_price
        else:
            # net < 0 → netto export → negatieve kosten (geld terug)
            return net * tariff.export_price

    # -------------------------------------------
    # B1 – toekomst zonder batterij
    # -------------------------------------------
    def scenario_B1_all(self) -> Dict[str, dict]:
        out: Dict[str, dict] = {}
        for key, tariff in self.tariffs.items():
            sim = SimulationEngine(self.load, self.pv, tariff)
            out[key] = sim.simulate_no_battery()
        return out

    # -------------------------------------------
    # C1 – toekomst MET batterij
    # -------------------------------------------
    def scenario_C1_all(self) -> Dict[str, dict]:
        out: Dict[str, dict] = {}
        for key, tariff in self.tariffs.items():
            sim = SimulationEngine(self.load, self.pv, tariff, self.battery)
            out[key] = sim.simulate_with_battery()
        return out

# ============================================================
# FALLBACK DYNAMISCHE PRIJSREIHE (8760 uur)
# ============================================================

# 24-uurs APX-achtig prijsprofiel (€/kWh)
_DAILY_APX_PROFILE = [
    0.18, 0.17, 0.16, 0.15,
    0.15, 0.16, 0.18, 0.22,
    0.26, 0.29, 0.32, 0.34,
    0.35, 0.33, 0.30, 0.28,
    0.32, 0.36, 0.38, 0.34,
    0.30, 0.26, 0.22, 0.20
]

# 24 uur * 365 → 8760
FALLBACK_DYNAMISCHE_PRIJZEN = _DAILY_APX_PROFILE * 365

# ============================================================
# HOOFDFUNCTIE (API)
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
    battery_cost: float,
    current_tariff: str = "enkel",
    battery_degradation: float = 0.02,
    capacity_tariff_kw: float = 0.0,
    peak_shaving_enabled: bool = True
):
    # Dynamische prijzen
    if prices_dyn and len(prices_dyn) > 0:
        dyn_prices = prices_dyn
    else:
        dyn_prices = FALLBACK_DYNAMISCHE_PRIJZEN

    tariffs = {
        "enkel":      TariffModel("enkel", p_enkel_imp, p_enkel_exp),
        "dag_nacht":  TariffModel("dag_nacht", p_dag, p_exp_dn),
        "dynamisch":  TariffModel("dynamisch", 0.0, p_export_dyn, dynamic_prices=dyn_prices),
    }

    battery = BatteryModel(E, P, DoD, eta_rt)
    SE = ScenarioEngine(load_kwh, pv_kwh, tariffs, battery)

    # A1
    A1 = SE.scenario_A1(current_tariff)

    # Toekomst
    B1 = SE.scenario_B1_all()
    C1 = SE.scenario_C1_all()

    # Peak shaving
    if peak_shaving_enabled:
        sim_for_peaks = SimulationEngine(load_kwh, pv_kwh, tariffs[current_tariff], battery)
        peak_no, peak_yes = sim_for_peaks.compute_peak_shaving()
    else:
        peak_no = max(max(load_kwh[i] - pv_kwh[i], 0) for i in range(len(load_kwh)))
        peak_yes = peak_no

    # Besparing jaar 1
    besparing_year1 = (B1[current_tariff]["total_cost"] + vastrecht) - \
                      (C1[current_tariff]["total_cost"] + vastrecht)

    # Capaciteitstarief-besparing
    peak_saving_year = (peak_no - peak_yes) * capacity_tariff_kw
    besparing_year1 += peak_saving_year

    # Payback & ROI
    if battery_cost <= 0 or besparing_year1 <= 0:
        payback = None
        roi = 0.0
    else:
        years = 15
        degr = battery_degradation
        E0 = E
        total_savings = 0.0
        payback = None

        for year in range(1, years + 1):
            E_cap_year = E0 * (1 - degr) ** (year - 1)
            besparing_year = besparing_year1 * (E_cap_year / E0)

            total_savings += besparing_year

            if payback is None and total_savings >= battery_cost:
                payback = year

        roi = (total_savings / battery_cost) * 100.0

    return {
        "A1_current": A1 + vastrecht,

        "A1_per_tariff": {
            "enkel": SE.scenario_A1("enkel") + vastrecht,
            "dag_nacht": SE.scenario_A1("dag_nacht") + vastrecht,
            "dynamisch": SE.scenario_A1("dynamisch") + vastrecht,
        },

        "B1_future_no_batt": B1[current_tariff]["total_cost"] + vastrecht,
        "C1_future_with_batt": C1[current_tariff]["total_cost"] + vastrecht,

        "S2_enkel": {**B1["enkel"], "total_cost": B1["enkel"]["total_cost"] + vastrecht},
        "S2_dn":    {**B1["dag_nacht"], "total_cost": B1["dag_nacht"]["total_cost"] + vastrecht},
        "S2_dyn":   {**B1["dynamisch"], "total_cost": B1["dynamisch"]["total_cost"] + vastrecht},

        "S3_enkel": {**C1["enkel"], "total_cost": C1["enkel"]["total_cost"] + vastrecht},
        "S3_dn":    {**C1["dag_nacht"], "total_cost": C1["dag_nacht"]["total_cost"] + vastrecht},
        "S3_dyn":   {**C1["dynamisch"], "total_cost": C1["dynamisch"]["total_cost"] + vastrecht},

        "vastrecht": vastrecht,
        "besparing_per_jaar": besparing_year1,
        "battery_cost": battery_cost,
        "payback_years": payback,
        "roi_percent": roi,

        "peak_no_battery_kw": peak_no,
        "peak_with_battery_kw": peak_yes,
        "peak_saving_year_euro": peak_saving_year,
        "capacity_tariff_kw": capacity_tariff_kw,
    }
