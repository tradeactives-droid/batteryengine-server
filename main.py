# ============================================================
# BatteryEngine Pro 2 — Backend API
# COMPLETE MAIN.PY (parse_csv + compute)
# ============================================================

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from openai import OpenAI

from BatteryEngine_Pro2 import compute_scenarios_v2


# ============================================================
# FASTAPI INIT
# ============================================================

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)

client = OpenAI()

@app.options("/{rest_of_path:path}")
async def preflight_handler():
    return {}


# ============================================================
# CSV PARSER
# ============================================================

class ParseCSVRequest(BaseModel):
    load_file: str
    pv_file: str
    prices_file: str


def _process_csv_text(raw: str) -> list[float]:
    if raw is None:
        return []

    raw = str(raw)
    lines = [ln for ln in raw.splitlines() if ln.strip() != ""]
    if len(lines) == 0:
        return []

    delim = ";"
    if ";" not in raw and "," in raw:
        delim = ","

    rows = []
    for ln in lines:
        rows.append([c.strip() for c in ln.split(delim)])

    if any(ch.isalpha() for ch in rows[0][0]):
        rows = rows[1:]

    floats = []
    for r in rows:
        for c in r:
            c = c.replace(",", ".")
            try:
                f = float(c)
                floats.append(f)
                break
            except:
                continue

    if len(floats) < 10:
        return []

    return floats


@app.post("/parse_csv")
def parse_csv(req: ParseCSVRequest):
    load = _process_csv_text(req.load_file)
    pv = _process_csv_text(req.pv_file)

    # --- FLUVIUS-CHECK: voldoende datapunten (minimaal ~half jaar) ---
    MIN_POINTS = 20000  # hard minimum; jaarprofiel is ~35.000 punten

    if len(load) < MIN_POINTS or len(pv) < MIN_POINTS:
        return {
            "load_kwh": [],
            "pv_kwh": [],
            "prices_dyn": [],
            "error": "NOT_ENOUGH_DATA_FOR_FLUVIUS"
        }

    # prices.csv mag optioneel zijn → lege string opleveren
    prices_raw = req.prices_file if req.prices_file is not None else ""
    prices = _process_csv_text(prices_raw) if prices_raw.strip() != "" else []

    # load en pv zijn verplicht
    if not load or not pv:
        return {
            "load_kwh": [],
            "pv_kwh": [],
            "prices_dyn": [],
            "error": "INVALID_LOAD_PV"
        }

    # Zorg dat load en pv even lang zijn
    n = min(len(load), len(pv))
    load = load[:n]
    pv = pv[:n]

    # prices (dynamisch) is optioneel
    # Alleen gebruiken als:
    # - er wél iets staat
    # - en lengte exact matcht met load/pv
    if prices and len(prices) == n:
        prices_dyn = prices
    else:
        prices_dyn = []  # => fallback in backend

    return {
        "load_kwh": load,
        "pv_kwh": pv,
        "prices_dyn": prices_dyn
    }

    # prices alleen controleren als ze er zijn
    if prices and len(prices) != len(load):
        return {
            "load_kwh": [],
            "pv_kwh": [],
            "prices_dyn": [],
            "error": "INVALID"
        }

    return {
        "load_kwh": load,
        "pv_kwh": pv,
        "prices_dyn": prices  # kan leeg zijn
    }


# ============================================================
# COMPUTE ENDPOINT
# ============================================================

class ComputeRequest(BaseModel):
    # PROFIELEN
    load_kwh: list[float]
    pv_kwh: list[float]
    prices_dyn: list[float]

    # TARIEVEN
    p_enkel_imp: float
    p_enkel_exp: float

    p_dag: float
    p_nacht: float
    p_exp_dn: float

    p_export_dyn: float

    # BATTERIJ
    E: float
    P: float
    DoD: float
    eta_rt: float
    vastrecht: float

    battery_cost: float
    battery_degradation: float

    # PEAK SHAVING / CAPACITEIT
    capacity_tariff_kw: float
    peak_shaving_enabled: bool

    # HUIDIG TARIEF
    current_tariff: str

class AdviceRequest(BaseModel):
    country: str          # "NL" of "BE"
    battery: dict         # batterijconfig en eventueel extra metadata
    results: dict         # alle scenario-resultaten (A1, B1, C1, ROI, etc.)

class ComputeRequest(BaseModel):
    # PROFIELEN
    load_kwh: list[float]
    pv_kwh: list[float]
    prices_dyn: list[float]

    # TARIEVEN
    p_enkel_imp: float
    p_enkel_exp: float

    p_dag: float
    p_nacht: float
    p_exp_dn: float

    p_export_dyn: float

    # BATTERIJ
    E: float
    P: float
    DoD: float
    eta_rt: float
    vastrecht: float

    battery_cost: float
    battery_degradation: float

    # PEAK SHAVING / CAPACITEIT
    capacity_tariff_kw: float
    peak_shaving_enabled: bool

    # HUIDIG TARIEF
    current_tariff: str

    # LAND (NL of BE)
    country: str


@app.post("/compute")
def compute(req: ComputeRequest):
    return compute_scenarios_v2(
        load_kwh=req.load_kwh,
        pv_kwh=req.pv_kwh,
        prices_dyn=req.prices_dyn,

        p_enkel_imp=req.p_enkel_imp,
        p_enkel_exp=req.p_enkel_exp,
        p_dag=req.p_dag,
        p_nacht=req.p_nacht,
        p_exp_dn=req.p_exp_dn,
        p_export_dyn=req.p_export_dyn,

        E=req.E,
        P=req.P,
        DoD=req.DoD,
        eta_rt=req.eta_rt,

        vastrecht=req.vastrecht,
        battery_cost=req.battery_cost,
        battery_degradation=req.battery_degradation,

        capacity_tariff_kw=req.capacity_tariff_kw,
        peak_shaving_enabled=req.peak_shaving_enabled,

        current_tariff=req.current_tariff,
        country=req.country
    )

















