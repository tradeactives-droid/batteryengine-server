from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import csv
import io

# 👉 jouw engine importeren
from BatteryEngine_Pro import compute_scenarios

app = FastAPI()

# -----------------------------
# CORS INSTELLEN
# -----------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://thuisbatterij-calculator-web.onrender.com",
        "http://localhost:5500",
        "*"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -----------------------------
# HELPERS
# -----------------------------
def parse_csv_to_floats(text: str) -> list[float]:
    """
    Verwerkt een CSV met:
    - meerdere kolommen
    - komma of punt als decimaal
    - ; of , als delimiter
    - headers toegestaan
    - timestamp kolommen worden genegeerd
    """

    # alle niet-lege regels
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if not lines:
        return []

    # delimiter detecteren
    first_line = lines[0]
    if first_line.count(";") >= first_line.count(","):
        delim = ";"
    else:
        delim = ","

    values: list[float] = []

    for ln in lines:
        parts = [p.strip() for p in ln.split(delim)]
        # zoek eerste kolom die als float gelezen kan worden
        picked = False
        for col in parts:
            col2 = col.replace(",", ".")
            try:
                f = float(col2)
                values.append(f)
                picked = True
                break
            except ValueError:
                continue

        # als geen enkele kolom numeriek was → overslaan
        if not picked:
            continue

    return values


# -----------------------------
# API MODELS
# -----------------------------
class ParseCSVRequest(BaseModel):
    load_file: str
    pv_file: str
    prices_file: str


class ComputeRequest(BaseModel):
    load_kwh: list
    pv_kwh: list
    prices_dyn: list
    p_enkel_imp: float
    p_enkel_exp: float
    p_dag: float
    p_nacht: float
    p_exp_dn: float
    E: float
    P: float
    DoD: float
    eta_rt: float
    Vastrecht: float

    # ✅ NIEUW – voor terugverdientijd
    capex: float
    opex: float


# -----------------------------
# ENDPOINT 1 — CSV PARSEN
# -----------------------------
@app.post("/parse_csv")
def parse_csv(req: ParseCSVRequest):

    load = parse_csv_to_floats(req.load_file)
    pv = parse_csv_to_floats(req.pv_file)
    prices = parse_csv_to_floats(req.prices_file)

    # simpele validatie
    if len(load) == 0 or len(pv) == 0 or len(prices) == 0:
        return {"error": "INVALID"}

    if not (len(load) == len(pv) == len(prices)):
        return {"error": "INVALID"}

    return {
        "load_kwh": load,
        "pv_kwh": pv,
        "prices_dyn": prices
    }


# -----------------------------
# ENDPOINT 2 — COMPUTE
# -----------------------------
@app.post("/compute")
def compute(req: ComputeRequest):

    ###########################
    # 1. Basis inputs ophalen
    ###########################
    load = req.load_kwh
    pv = req.pv_kwh
    dyn = req.prices_dyn

    p_enkel_imp = req.p_enkel_imp
    p_enkel_exp = req.p_enkel_exp

    p_dag = req.p_dag
    p_nacht = req.p_nacht
    p_exp_dn = req.p_exp_dn

    E = req.E
    P = req.P
    DoD = req.DoD
    eta = req.eta_rt
    vastrecht = req.Vastrecht

    N = len(load)
    dt = 0.25   # kwartierdata → 15 min

    ###########################
    # 2. A1 — Huidige situatie (MET saldering)
    ###########################
    total_load = sum(load) * dt
    total_pv = sum(pv) * dt

    # saldering = export == waarde van import
    A1_current_cost = (total_load - total_pv) * p_enkel_imp + vastrecht

    ###########################
    # 3. B1 — Toekomst zonder saldering, GEEN batterij
    ###########################
    B1_import = 0.0
    B1_export = 0.0
    B1_cost = 0.0

    for t in range(N):
        surplus = pv[t] - load[t]

        if surplus >= 0:
            # overschot → export voor lage vergoeding
            B1_export += surplus * dt
            B1_cost -= surplus * dt * p_enkel_exp
        else:
            # tekort → import
            B1_import += (-surplus) * dt
            B1_cost += (-surplus) * dt * p_enkel_imp

    B1_cost += vastrecht

    ###########################
    # 4. C1 — Toekomst met batterij (zonder saldering)
    ###########################
    Emax = E * DoD
    SOC = 0.5 * Emax

    C1_import = 0.0
    C1_export = 0.0
    C1_cost = 0.0

    for t in range(N):
        surplus = pv[t] - load[t]

        if surplus > 0:
            # batterij laden
            charge = min(surplus * eta, P)
            energy_added = charge * dt
            available_room = Emax - SOC
            actual = min(energy_added, available_room)

            SOC += actual
            surplus -= actual / eta

            # rest gaat naar export
            C1_export += surplus * dt
            C1_cost -= surplus * dt * p_enkel_exp

        else:
            # tekort → batterij ontladen
            discharge = min(-surplus / eta, P)
            energy_available = SOC
            actual = min(discharge * dt, energy_available)

            SOC -= actual
            covered = actual * eta / dt
            deficit = (-surplus) - covered

            if deficit > 0:
                C1_import += deficit * dt
                C1_cost += deficit * dt * p_enkel_imp

    C1_cost += vastrecht

    ###########################
    # 5. Verschillen
    ###########################
    extra_cost_saldering_stops = B1_cost - A1_current_cost
    saving_by_battery = B1_cost - C1_cost
    future_vs_now_batt = C1_cost - A1_current_cost

    ###########################
    # 6.1 Terugverdientijd batterij
    ###########################
    capex = req.capex
    opex = req.opex

    net_saving = saving_by_battery - opex

    if net_saving > 0:
        payback_years = capex / net_saving
    else:
        payback_years = None
    
    ###########################
    # 6. Resultaat terugsturen
    ###########################
    return {
        "A1_current": A1_current_cost,
        "B1_future_no_batt": B1_cost,
        "C1_future_with_batt": C1_cost,

        "extra_cost_when_saldering_stops": extra_cost_saldering_stops,
        "saving_by_battery": saving_by_battery,
        "future_vs_now_with_battery": future_vs_now_batt,
        "payback_years": payback_years,

        "flows": {
            "B1_import": B1_import,
            "B1_export": B1_export,
            "C1_import": C1_import,
            "C1_export": C1_export
        }
    }

    return result
