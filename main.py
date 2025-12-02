# ============================================================
# BatteryEngine Pro 2 — Backend API v2
# ============================================================

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List

from BatteryEngine_Pro2 import compute_scenarios_v2


app = FastAPI()

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)


# ============================================================
# CSV PARSER
# ============================================================

class ParseCSVRequest(BaseModel):
    load_file: str
    pv_file: str
    prices_file: str | None = ""


def _process_csv_text(raw: str) -> List[float]:
    if not raw:
        return []

    raw = str(raw)
    lines = [ln for ln in raw.splitlines() if ln.strip() != ""]
    if not lines:
        return []

    delim = ";" if ";" in raw else ","

    rows = []
    for ln in lines:
        rows.append([c.strip() for c in ln.split(delim)])

    # header automatisch verwijderen
    if any(ch.isalpha() for ch in rows[0][0]):
        rows = rows[1:]

    floats = []
    for r in rows:
        for c in r:
            c = c.replace(",", ".")
            try:
                floats.append(float(c))
                break
            except:
                continue

    return floats


@app.post("/parse_csv")
def parse_csv(req: ParseCSVRequest):

    load = _process_csv_text(req.load_file)
    pv = _process_csv_text(req.pv_file)
    prices = _process_csv_text(req.prices_file or "")

    # dynamische prijzen mogen leeg zijn — afhankelijk van tarief
    if not load or not pv:
        return {"error": "INVALID", "load_kwh": [], "pv_kwh": [], "prices_dyn": []}

    if len(load) != len(pv):
        return {"error": "INVALID", "load_kwh": [], "pv_kwh": [], "prices_dyn": []}

    # dynamisch mag verschillen in lengte
    return {
        "load_kwh": load,
        "pv_kwh": pv,
        "prices_dyn": prices
    }


# ============================================================
# COMPUTE ENDPOINT
# ============================================================

class ComputeRequest(BaseModel):
    load_kwh: List[float]
    pv_kwh: List[float]
    prices_dyn: List[float]

    p_enkel_imp: float
    p_enkel_exp: float
    p_dag: float
    p_nacht: float
    p_exp_dn: float
    p_export_dyn: float

    E: float
    P: float
    DoD: float
    eta_rt: float
    Vastrecht: float

    current_tariff: str


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
        vastrecht=req.Vastrecht,
        current_tariff=req.current_tariff
    )
