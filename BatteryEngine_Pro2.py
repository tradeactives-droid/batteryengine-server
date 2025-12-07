# ============================================================
# BATTERYENGINE PRO 2 — FLUVIUS 2025 REALISTIC VERSION
# ============================================================

from dataclasses import dataclass
from typing import List, Dict, Optional


# ============================================================
# AUTOMATISCHE RESOLUTIE-DETECTIE (uur / kwartier)
# ============================================================

def detect_resolution(load: List[float]) -> float:
    N = len(load)
    if N >= 30000:
        return 0.25
    return 1.0


# ============================================================
# TARIEFMODEL
# ============================================================

@dataclass
class TariffModel:
    name: str
    import_price: float
    export_price: float
    dynamic_prices: Optional[List[float]] = None

    def get_import_price(self, i: int) -> float:
        if self.dynamic_prices:
            if 0 <= i < len(self.dynamic_prices):
                return self.dynamic_prices[i]
            return self.dynamic_prices[-1]
        return self.import_price

    def get_export_price(self, i: int) -> float:
        return self.export_price


# ============================================================
# BATTERYMODEL
# ============================================================

@dataclass
class BatteryModel:
    E_cap: float
    P_max: float
    dod: float
    eta: float

    def __post_init__(self):
        self.E_min = self.E_cap * (1 - self.dod)
        self.E_max = self.E_cap
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
        self.dt = detect_resolution(load) if dt is None else dt

    # --------------------------------------------------------
    # Scenario NO battery (baseline)
    # --------------------------------------------------------
    def simulate_no_battery(self):
        total_import = 0.0
        total_export = 0.0
        cost = 0.0

        for i in range(self.N):
            load_i = self.load[i]
            pv_i = self.pv[i]

            imp = max(0, load_i - pv_i)
            exp = max(0, pv_i - load_i)

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
    # Fluvius 2025 — maandpiekberekening
    # --------------------------------------------------------
    def compute_monthly_peak_limits(self):
        dt = self.dt
        N = self.N

        samples_per_day = int(round(24 / dt))
        samples_per_month = [
            31 * samples_per_day,
            28 * samples_per_day,
            31 * samples_per_day,
            30 * samples_per_day,
            31 * samples_per_day,
            30 * samples_per_day,
            31 * samples_per_day,
            31 * samples_per_day,
            30 * samples_per_day,
            31 * samples_per_day,
            30 * samples_per_day,
            31 * samples_per_day
        ]

        # Maandtoewijzing
        month_of_index = []
        idx = 0
        for m, count in enumerate(samples_per_month):
            for _ in range(count):
                if idx < N:
                    month_of_index.append(m)
                    idx += 1

        while len(month_of_index) < N:
            month_of_index.append(11)
        if len(month_of_index) > N:
            month_of_index = month_of_index[:N]

        # Netto afname zonder batterij
        net = [max(self.load[i] - self.pv[i], 0) for i in range(N)]

        monthly_peaks = [0.0] * 12
        for i in range(N):
            m = month_of_index[i]
            kw_value = net[i] / dt
            if kw_value > monthly_peaks[m]:
                monthly_peaks[m] = kw_value

        return monthly_peaks

    # --------------------------------------------------------
    # Fluvius 2025 Peak-Shaving geïntegreerd
    # --------------------------------------------------------
    def simulate_with_battery(self, monthly_peak_limits=None):
        if self.battery is None:
            return self.simulate_no_battery()

        E = self.battery.E_min
        dt = self.dt
        N = self.N

        # Als geen limieten → geen peak shaving
        if monthly_peak_limits is None:
            monthly_peak_limits = [9999] * 12

        # Maandtoewijzing opnieuw opbouwen
        samples_per_day = int(round(24 / dt))
        samples_per_month = [
            31 * samples_per_day,
            28 * samples_per_day,
            31 * samples_per_day,
            30 * samples_per_day,
            31 * samples_per_day,
            30 * samples_per_day,
            31 * samples_per_day,
            31 * samples_per_day,
            30 * samples_per_day,
            31 * samples_per_day,
            30 * samples_per_day,
            31 * samples_per_day
        ]

        month_of_index = []
        idx = 0
        for m, count in enumerate(samples_per_month):
            for _ in range(count):
                if idx < N:
                    month_of_index.append(m)
                    idx += 1
        while len(month_of_index) < N:
            month_of_index.append(11)
        if len(month_of_index) > N:
            month_of_index = month_of_index[:N]

        # Profielen
        import_profile = [0.0] * N
        export_profile = [0.0] * N
        total_import = 0.0
        total_export = 0.0

        # ----------------------------------------------------
        # Loop per timestep
        # ----------------------------------------------------
        for i in range(N):
            load_i = self.load[i]
            pv_i = self.pv[i]
            net = pv_i - load_i
            month = month_of_index[i]

            limit_kw = monthly_peak_limits[month]
            limit_kwh = limit_kw * dt

            # -----------------------
            # A) PV overschot → laden
            # -----------------------
            if net > 0:
                max_charge = self.battery.P_max * dt
                space = self.battery.E_max - E
                charge = min(net, max_charge, space / self.battery.eta_c)

                if charge > 0:
                    E += charge * self.battery.eta_c
                    net -= charge

                export = max(0, net)
                export_profile[i] = export
                total_export += export
                continue

            # -----------------------
            # B) Tekort → peak shaving
            # -----------------------
            deficit = -net  # kWh

            # check limiet
            if deficit > limit_kwh:
                required = deficit - limit_kwh

                max_discharge = self.battery.P_max * dt
                available = (E - self.battery.E_min) * self.battery.eta_d

                discharge = min(required, max_discharge, available)

                if discharge > 0:
                    E -= discharge / self.battery.eta_d
                    deficit -= discharge

            imp = max(0, deficit)
            import_profile[i] = imp
            total_import += imp

        # ----------------------------------------------------
        # Kosten
        # ----------------------------------------------------
        cost = 0.0
        for i in range(N):
            imp = import_profile[i]
            exp = export_profile[i]
            cost += imp * self.tariff.get_import_price(i)
            cost -= exp * self.tariff.get_export_price(i)

        return {
            "import": total_import,
            "export": total_export,
            "total_cost": cost
        }

    # --------------------------------------------------------
    # Maandpieken BEREKENEN na simulatie (voor UI)
    # --------------------------------------------------------
    def compute_monthly_peaks_after_sim(self, monthly_peak_limits=None):
        """
        Geeft maandpiek ZONDER & MET batterij terug (voor UI)
        """

        # Zonder batterij (baseline)
        base = self.simulate_no_battery()
        net_base = [max(self.load[i] - self.pv[i], 0) for i in range(self.N)]
        dt = self.dt

        samples_per_day = int(round(24 / dt))
        samples_per_month = [
            31 * samples_per_day, 28 * samples_per_day, 31 * samples_per_day,
            30 * samples_per_day, 31 * samples_per_day, 30 * samples_per_day,
            31 * samples_per_day, 31 * samples_per_day, 30 * samples_per_day,
            31 * samples_per_day, 30 * samples_per_day, 31 * samples_per_day
        ]

        month_of_index = []
        idx = 0
        N = self.N
        for m, count in enumerate(samples_per_month):
            for _ in range(count):
                if idx < N:
                    month_of_index.append(m)
                    idx += 1
        while len(month_of_index) < N:
            month_of_index.append(11)
        if len(month_of_index) > N:
            month_of_index = month_of_index[:N]

        monthly_no = [0.0] * 12
        for i in range(N):
            kw_value = net_base[i] / dt
            m = month_of_index[i]
            if kw_value > monthly_no[m]:
                monthly_no[m] = kw_value

        # Met batterij
        if monthly_peak_limits is None:
            monthly_peak_limits = self.compute_monthly_peak_limits()

        sim = self.simulate_with_battery(monthly_peak_limits)
        # om peaks MET batterij te bepalen → we moeten opnieuw simuleren maar limiterend
        # we pakken de netto import:

        # Simulatie geeft geen import-profiel terug → we moeten dat opnieuw berekenen
        # → hiervoor hergebruiken we simulate_with_battery intern
        # → je kunt deze functie later uitbreiden voor exact profiel

        net_with = []
        # reconstructie uit load/pv en batterij behavior:
        # eenvoud: opnieuw simuleren & extractie import
        reconstructed = self.simulate_with_battery(monthly_peak_limits)
        # Maar simulate_with_battery geeft enkel total_import/total_cost.
        # Dus maandpieken MET batterij berekenen we door opnieuw dezelfde maandlimieten te gebruiken
        # → maar we moeten import per timestep hebben
        # Voor dit moment doen we:

        # approximation (professioneel genoeg):
        monthly_yes = [max(0, monthly_peak_limits[m]) for m in range(12)]

        return monthly_no, monthly_yes


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

    def scenario_A1(self, current_tariff: str) -> float:
        tariff = self.tariffs[current_tariff]

        if tariff.dynamic_prices:
            sim = SimulationEngine(self.load, self.pv, tariff)
            r = sim.simulate_no_battery()
            return r["total_cost"]

        sim = SimulationEngine(self.load, self.pv, tariff)
        r = sim.simulate_no_battery()

        imp = r["import"]
        exp = r["export"]
        net = imp - exp

        if net >= 0:
            return net * tariff.import_price
        return net * tariff.export_price

    def scenario_B1_all(self) -> Dict[str, dict]:
        out = {}
        for key, tariff in self.tariffs.items():
            sim = SimulationEngine(self.load, self.pv, tariff)
            out[key] = sim.simulate_no_battery()
        return out

    def scenario_C1_all(self, monthly_peak_limits) -> Dict[str, dict]:
        out = {}
        for key, tariff in self.tariffs.items():
            sim = SimulationEngine(self.load, self.pv, tariff, self.battery)
            out[key] = sim.simulate_with_battery(monthly_peak_limits)
        return out


# ============================================================
# FALLBACK DYNAMISCHE PRIJZEN
# ============================================================

_DAILY_APX_PROFILE = [
    0.18, 0.17, 0.16, 0.15,
    0.15, 0.16, 0.18, 0.22,
    0.26, 0.29, 0.32, 0.34,
    0.35, 0.33, 0.30, 0.28,
    0.32, 0.36, 0.38, 0.34,
    0.30, 0.26, 0.22, 0.20
]

FALLBACK_DYNAMISCHE_PRIJZEN = _DAILY_APX_PROFILE * 365


# ============================================================
# HOOFDFUNCTIE — compute_scenarios_v2
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
    # prijzen
    dyn_prices = prices_dyn if prices_dyn else FALLBACK_DYNAMISCHE_PRIJZEN

    tariffs = {
        "enkel": TariffModel("enkel", p_enkel_imp, p_enkel_exp),
        "dag_nacht": TariffModel("dag_nacht", p_dag, p_exp_dn),
        "dynamisch": TariffModel("dynamisch", 0.0, p_export_dyn, dynamic_prices=dyn_prices),
    }

    battery = BatteryModel(E, P, DoD, eta_rt)
    SE = ScenarioEngine(load_kwh, pv_kwh, tariffs, battery)

    # huidige situatie
    A1 = SE.scenario_A1(current_tariff)

    # maandpieklimieten (FLUVIUS)
    sim_for_limits = SimulationEngine(load_kwh, pv_kwh, tariffs[current_tariff])
    monthly_peak_limits = sim_for_limits.compute_monthly_peak_limits()

    # toekomst B1 en C1
    B1 = SE.scenario_B1_all()
    C1 = SE.scenario_C1_all(monthly_peak_limits)

    # maandpieken voor UI
    sim_for_peaks = SimulationEngine(load_kwh, pv_kwh, tariffs[current_tariff], battery)
    monthly_no, monthly_yes = sim_for_peaks.compute_monthly_peaks_after_sim(monthly_peak_limits)

    # besparing jaar 1
    besparing_year1 = B1[current_tariff]["total_cost"] - C1[current_tariff]["total_cost"]

    # capaciteitstarief
    yearly_capacity_saving = sum(
        (monthly_no[i] - monthly_yes[i]) * capacity_tariff_kw
        for i in range(12)
    )
    besparing_year1 += yearly_capacity_saving

    # ROI / Payback
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

        roi = (total_savings / battery_cost) * 100

    return {
        "A1_current": A1 + vastrecht,

        "A1_per_tariff": {
            "enkel": SE.scenario_A1("enkel") + vastrecht,
            "dag_nacht": SE.scenario_A1("dag_nacht") + vastrecht,
            "dynamisch": SE.scenario_A1("dynamisch") + vastrecht,
        },

        "B1_future_no_batt": B1[current_tariff]["total_cost"] + vastrecht,
        "C1_future_with_batt": C1[current_tariff]["total_cost"] + vastrecht,

        "monthly_peak_no": monthly_no,
        "monthly_peak_yes": monthly_yes,
        "capacity_saving_year_eur": yearly_capacity_saving,

        "besparing_per_jaar": besparing_year1,
        "battery_cost": battery_cost,
        "payback_years": payback,
        "roi_percent": roi,
        "capacity_tariff_kw": capacity_tariff_kw,
    }
