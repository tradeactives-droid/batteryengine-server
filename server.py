# ============================================================
# BatteryEngine Pro 2 — Backend API
# SERVER.PY  (definitieve versie)
# ============================================================

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from BatteryEngine_Pro2 import compute_scenarios_v2


# ============================================================
# FASTAPI APP SETUP
# ============================================================
app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # later beperken indien nodig
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)


# ============================================================
# REQUESTMODEL — perfect afgestemd op de frontend
# ============================================================
class ComputeRequest(BaseModel):
    load_kwh: list[float]
    pv_kwh: list[float]
    prices_dyn: list[float]

    p_enkel_imp: float
    p_enkel_exp: float

    p_dag: float
    p_nacht: float
    p_exp_dn: float

    p_export_dyn: float   # frontend stuurt dit

    E: float
    P: float
    DoD: float       # 0–1 → frontend deelt al door 100
    eta_rt: float    # 0–1 → frontend deelt al door 100
    Vastrecht: float

    current_tariff: str   # "enkel" | "dag_nacht" | "dynamisch"


# ============================================================
# /compute (100% compatibel met BatteryEngine Pro 2)
# ============================================================
@app.post("/compute")
def compute(req: ComputeRequest):

    # Engine Pro 2 werkt met losse parameters, dus we geven ze los door
    result = compute_scenarios_v2(
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

    return result


# ============================================================
# CSV PARSER ENDPOINT
# (werkt perfect met jouw frontend)
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

    # header skippen
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
    prices = _process_csv_text(req.prices_file)

    if not load or not pv or not prices:
        return {
            "load_kwh": [],
            "pv_kwh": [],
            "prices_dyn": [],
            "error": "INVALID"
        }

    if not (len(load) == len(pv) == len(prices)):
        return {
            "load_kwh": [],
            "pv_kwh": [],
            "prices_dyn": [],
            "error": "INVALID"
        }

    return {
        "load_kwh": load,
        "pv_kwh": pv,
        "prices_dyn": prices
    }
