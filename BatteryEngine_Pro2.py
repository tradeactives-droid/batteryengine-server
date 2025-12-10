# ============================================================
# BATTERYENGINE PRO 2 — FLUVIUS 2025 REALISTIC VERSION (CLEAN)
# ============================================================

from dataclasses import dataclass
from typing import List, Dict, Optional


# ============================================================
# RESOLUTION DETECTION (quarter-hour or hourly)
# ============================================================

def detect_resolution(load: List[float]) -> float:
    N = len(load)
    if N >= 30000:
        return 0.25
    return 1.0


# ============================================================
# TARIFF MODEL
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
# BATTERY MODEL
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
    # Scenario: no battery
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
    # Fluvius 2025 — compute monthly peaks without battery
    # --------------------------------------------------------
    def compute_monthly_peak_limits(self):
        dt = self.dt
        N = self.N

        samples_per_day = int(round(24 / dt))
        samples_per_month = [
            31 * samples_per_day, 28 * samples_per_day, 31 * samples_per_day,
            30 * samples_per_day, 31 * samples_per_day, 30 * samples_per_day,
            31 * samples_per_day, 31 * samples_per_day, 30 * samples_per_day,
            31 * samples_per_day, 30 * samples_per_day, 31 * samples_per_day
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
        month_of_index = month_of_index[:N]

        net_no_battery = [max(self.load[i] - self.pv[i], 0) for i in range(N)]

        monthly_peaks = [0.0] * 12
        for i in range(N):
            m = month_of_index[i]
            kw_val = net_no_battery[i] / dt
            if kw_val > monthly_peaks[m]:
                monthly_peaks[m] = kw_val

        return monthly_peaks

    # --------------------------------------------------------
    # Battery simulation with automatic peak shaving
    # --------------------------------------------------------
    def simulate_with_battery(self, monthly_peak_limits=None):
        if self.battery is None:
            return self.simulate_no_battery()

        E = self.battery.E_min
        dt = self.dt
        N = self.N

        if monthly_peak_limits is None:
            monthly_peak_limits = [9999] * 12

        samples_per_day = int(round(24 / dt))
        samples_per_month = [
            31 * samples_per_day, 28 * samples_per_day, 31 * samples_per_day,
            30 * samples_per_day, 31 * samples_per_day, 30 * samples_per_day,
            31 * samples_per_day, 31 * samples_per_day, 30 * samples_per_day,
            31 * samples_per_day, 30 * samples_per_day, 31 * samples_per_day
        ]

        month_of_index = []
        idx = 0
        for m, cnt in enumerate(samples_per_month):
            for _ in range(cnt):
                if idx < N:
                    month_of_index.append(m)
                    idx += 1

        while len(month_of_index) < N:
            month_of_index.append(11)
        month_of_index = month_of_index[:N]

        import_profile = [0.0] * N
        export_profile = [0.0] * N
        total_import = 0.0
        total_export = 0.0

        for i in range(N):
            load_i = self.load[i]
            pv_i = self.pv[i]
            net = pv_i - load_i
            m = month_of_index[i]

            limit_kw = monthly_peak_limits[m]
            limit_kwh = limit_kw * dt

            # PV overschot
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

            # tekort → peak shaving
            deficit = -net

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
    # SIMPLE BATTERY SIMULATION (NL mode, no peak limits)
    # --------------------------------------------------------
    def simulate_with_battery_simple(self):
        """
        NL-modus: batterij laadt bij overschot, ontlaadt bij tekort.
        Geen maandpieken, geen Fluvius-limieten, geen capaciteitstarief.
        """
        if self.battery is None:
            return self.simulate_no_battery()

        E = self.battery.E_min
        dt = self.dt
        N = self.N

        total_import = 0.0
        total_export = 0.0

        for i in range(N):
            load_i = self.load[i]
            pv_i = self.pv[i]
            net = pv_i - load_i  # + = overschot, - = tekort

            # PV-overschot → eerst batterij laden, rest exporteren
            if net >= 0:
                max_charge = self.battery.P_max * dt
                space = self.battery.E_max - E

                charge = min(net, max_charge, space / self.battery.eta_c)

                if charge > 0:
                    E += charge * self.battery.eta_c
                    net -= charge

                export = max(0, net)
                total_export += export

            else:
                # Tekort → eerst batterij ontladen, rest importeren
                deficit = -net

                max_discharge = self.battery.P_max * dt
                available = (E - self.battery.E_min) * self.battery.eta_d

                discharge = min(deficit, max_discharge, available)

                if discharge > 0:
                    E -= discharge / self.battery.eta_d
                    deficit -= discharge

                imp = max(0, deficit)
                total_import += imp

        # Kosten berekenen met import/export-profielen uit totalen
        cost = 0.0
        # Let op: hier geen profiellogging, alleen totale kWh
        # Voor NL is dit voldoende.
        # Voor dynamisch NL kun je later uitbreiden naar timestep-based.

        # Eenvoud: gemiddelde prijs benaderen via simulate_no_battery
        # (voor nu laten we kostensimulatie consistent via timestep)
        # → daarom herhalen we de loop met expliciete profils:

        total_import = 0.0
        total_export = 0.0
        E = self.battery.E_min

        for i in range(N):
            load_i = self.load[i]
            pv_i = self.pv[i]
            net = pv_i - load_i

            if net >= 0:
                max_charge = self.battery.P_max * dt
                space = self.battery.E_max - E

                charge = min(net, max_charge, space / self.battery.eta_c)

                if charge > 0:
                    E += charge * self.battery.eta_c
                    net -= charge

                export = max(0, net)
                total_export += export
                imp = 0.0

            else:
                deficit = -net
                max_discharge = self.battery.P_max * dt
                available = (E - self.battery.E_min) * self.battery.eta_d

                discharge = min(deficit, max_discharge, available)

                if discharge > 0:
                    E -= discharge / self.battery.eta_d
                    deficit -= discharge

                imp = max(0, deficit)
                total_import += imp
                export = 0.0

            cost += imp * self.tariff.get_import_price(i)
            cost -= export * self.tariff.get_export_price(i)

        return {
            "import": total_import,
            "export": total_export,
            "total_cost": cost
        }    

    # --------------------------------------------------------
    # Compute monthly peaks for UI (baseline vs battery)
    # --------------------------------------------------------
    def compute_monthly_peaks_after_sim(self, monthly_peak_limits):
        dt = self.dt
        N = self.N

        # baseline peaks
        base_net = [max(self.load[i] - self.pv[i], 0) for i in range(N)]

        samples_per_day = int(round(24 / dt))
        samples_per_month = [
            31 * samples_per_day, 28 * samples_per_day, 31 * samples_per_day,
            30 * samples_per_day, 31 * samples_per_day, 30 * samples_per_day,
            31 * samples_per_day, 31 * samples_per_day, 30 * samples_per_day,
            31 * samples_per_day, 30 * samples_per_day, 31 * samples_per_day
        ]

        month_of_index = []
        idx = 0
        for m, cnt in enumerate(samples_per_month):
            for _ in range(cnt):
                if idx < N:
                    month_of_index.append(m)
                    idx += 1

        while len(month_of_index) < N:
            month_of_index.append(11)
        month_of_index = month_of_index[:N]

        monthly_no = [0.0] * 12
        for i in range(N):
            kw_val = base_net[i] / dt
            m = month_of_index[i]
            if kw_val > monthly_no[m]:
                monthly_no[m] = kw_val

        # peaks with battery: approximated by used limit
        monthly_yes = monthly_peak_limits.copy()

        return monthly_no, monthly_yes


# ============================================================
# SCENARIO ENGINE
# ============================================================

class ScenarioEngine:
    def __init__(self, load, pv, tariffs, battery):
        self.load = load
        self.pv = pv
        self.tariffs = tariffs
        self.battery = battery

    def scenario_A1(self, current_tariff: str) -> float:
        tariff = self.tariffs[current_tariff]

        sim = SimulationEngine(self.load, self.pv, tariff)
        result = sim.simulate_no_battery()

        if tariff.dynamic_prices:
            return result["total_cost"]

        imp = result["import"]
        exp = result["export"]
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
# FALLBACK DYNAMIC PRICES
# ============================================================

_DAILY = [
    0.18, 0.17, 0.16, 0.15,
    0.15, 0.16, 0.18, 0.22,
    0.26, 0.29, 0.32, 0.34,
    0.35, 0.33, 0.30, 0.28,
    0.32, 0.36, 0.38, 0.34,
    0.30, 0.26, 0.22, 0.20
]

FALLBACK_DYNAMISCHE_PRIJZEN = _DAILY * 365


# ============================================================
# MASTER — compute_scenarios_v2
# ============================================================

def compute_scenarios_v2(
    load_kwh, pv_kwh, prices_dyn,

    p_enkel_imp, p_enkel_exp,
    p_dag, p_nacht, p_exp_dn,
    p_export_dyn,

    E, P, DoD, eta_rt, vastrecht,

    battery_cost,
    current_tariff="enkel",
    battery_degradation=0.02,
    capacity_tariff_kw=0.0,
    peak_shaving_enabled=True,
    country="BE"
):
    # -----------------------------
    # 1) Tarieven & batterij
    # -----------------------------
    dyn_prices = prices_dyn if prices_dyn else FALLBACK_DYNAMISCHE_PRIJZEN

    tariffs = {
        "enkel": TariffModel("enkel", p_enkel_imp, p_enkel_exp),
        "dag_nacht": TariffModel("dag_nacht", p_dag, p_exp_dn),
        "dynamisch": TariffModel("dynamisch", 0.0, p_export_dyn, dynamic_prices=dyn_prices),
    }

    battery = BatteryModel(E, P, DoD, eta_rt)
    SE = ScenarioEngine(load_kwh, pv_kwh, tariffs, battery)

    country = (country or "BE").upper()

    # --------------------------------------
    # 2) Scenario's per land
    # --------------------------------------
    if country == "BE":
        # A1 — huidige situatie
        A1 = SE.scenario_A1(current_tariff)

        # Maandpieklimieten (Fluvius)
        sim_for_limits = SimulationEngine(load_kwh, pv_kwh, tariffs[current_tariff])
        monthly_peak_limits = sim_for_limits.compute_monthly_peak_limits()

        # B1 & C1
        B1 = SE.scenario_B1_all()
        C1 = SE.scenario_C1_all(monthly_peak_limits)

        # Maandpieken voor UI
        sim_for_peaks = SimulationEngine(load_kwh, pv_kwh, tariffs[current_tariff], battery)
        monthly_no, monthly_yes = sim_for_peaks.compute_monthly_peaks_after_sim(monthly_peak_limits)

        # Jaarlijkse kosten basis vs batterij
        baseline = B1[current_tariff]["total_cost"]
        with_batt = C1[current_tariff]["total_cost"]
        besparing = baseline - with_batt

        # Capaciteitstarief-besparing
        cap_save = sum(
            (monthly_no[i] - monthly_yes[i]) * capacity_tariff_kw
            for i in range(12)
        )
        besparing += cap_save

    else:
        # -----------------------------
        # NL-modus: GEEN peak-shaving,
        # GEEN capaciteitstarief,
        # GEEN Fluvius-maandpieken.
        # -----------------------------
        A1 = SE.scenario_A1(current_tariff)

        # B1 — zonder batterij
        B1 = {}
        for key, tariff in tariffs.items():
            sim = SimulationEngine(load_kwh, pv_kwh, tariff)
            B1[key] = sim.simulate_no_battery()

        # C1 — met eenvoudige batterij (geen peaken)
        C1 = {}
        for key, tariff in tariffs.items():
            sim = SimulationEngine(load_kwh, pv_kwh, tariff, battery)
            C1[key] = sim.simulate_with_battery_simple()

        # Geen capaciteitstarief en geen maandpieken in NL
        monthly_no = [0.0] * 12
        monthly_yes = [0.0] * 12
        cap_save = 0.0
        capacity_tariff_kw = 0.0  # negeren in NL

        baseline = B1[current_tariff]["total_cost"]
        with_batt = C1[current_tariff]["total_cost"]
        besparing = baseline - with_batt

    # --------------------------------------
    # 3) ROI / Payback (gedeeld voor NL & BE)
    # --------------------------------------
    if battery_cost <= 0 or besparing <= 0:
        payback = None
        roi = 0.0
    else:
        years = 15
        degr = battery_degradation
        E0 = E

        total_savings = 0.0
        payback = None

        for year in range(1, years + 1):
            cap_eff = E0 * (1 - degr) ** (year - 1)
            year_save = besparing * (cap_eff / E0)
            total_savings += year_save
            if payback is None and total_savings >= battery_cost:
                payback = year

        roi = (total_savings / battery_cost) * 100

    # --------------------------------------
    # 4) S2 / S3 per tarief voor UI & PDF
    # --------------------------------------
    S2_enkel = B1.get("enkel", {"import": 0.0, "export": 0.0, "total_cost": 0.0})
    S2_dn    = B1.get("dag_nacht", {"import": 0.0, "export": 0.0, "total_cost": 0.0})
    S2_dyn   = B1.get("dynamisch", {"import": 0.0, "export": 0.0, "total_cost": 0.0})

    S3_enkel = C1.get("enkel", {"import": 0.0, "export": 0.0, "total_cost": 0.0})
    S3_dn    = C1.get("dag_nacht", {"import": 0.0, "export": 0.0, "total_cost": 0.0})
    S3_dyn   = C1.get("dynamisch", {"import": 0.0, "export": 0.0, "total_cost": 0.0})

    # --------------------------------------
    # Tiles moeten overeenkomen met gekozen tarief
    # --------------------------------------

    # Maak kopieën zodat we ze kunnen aanpassen
    S2_enkel_out = S2_enkel.copy()
    S2_dn_out    = S2_dn.copy()
    S2_dyn_out   = S2_dyn.copy()

    S3_enkel_out = S3_enkel.copy()
    S3_dn_out    = S3_dn.copy()
    S3_dyn_out   = S3_dyn.copy()

    # Vul de juiste kolom met baseline / with_batt
    if current_tariff == "enkel":
        S2_enkel_out["total_cost"] = baseline
        S3_enkel_out["total_cost"] = with_batt

    elif current_tariff == "dag_nacht":
        S2_dn_out["total_cost"] = baseline
        S3_dn_out["total_cost"] = with_batt

    elif current_tariff == "dynamisch":
        S2_dyn_out["total_cost"] = baseline
        S3_dyn_out["total_cost"] = with_batt

    # --------------------------------------
    # 5) Resultaat terug naar frontend
    # --------------------------------------
    return {
        "A1_current": A1 + vastrecht,

        "A1_per_tariff": {
            "enkel": SE.scenario_A1("enkel") + vastrecht,
            "dag_nacht": SE.scenario_A1("dag_nacht") + vastrecht,
            "dynamisch": SE.scenario_A1("dynamisch") + vastrecht,
        },

        "B1_future_no_batt": baseline + vastrecht,
        "C1_future_with_batt": with_batt + vastrecht,

        # S2 / S3 per tarief (voor tabellen & PDF)
        "S2_enkel": S2_enkel_out,
"S2_dn":    S2_dn_out,
"S2_dyn":   S2_dyn_out,

"S3_enkel": S3_enkel_out,
"S3_dn":    S3_dn_out,
"S3_dyn":   S3_dyn_out,

        "monthly_peak_no": monthly_no,
        "monthly_peak_yes": monthly_yes,

        "capacity_saving_year_eur": cap_save,
        "peak_no_battery_kw": max(monthly_no) if monthly_no else 0.0,
        "peak_with_battery_kw": max(monthly_yes) if monthly_yes else 0.0,
        "peak_saving_year_euro": cap_save,

        "besparing_per_jaar": besparing,
        "battery_cost": battery_cost,
        "payback_years": payback,
        "roi_percent": roi,
        "capacity_tariff_kw": capacity_tariff_kw,
    }
