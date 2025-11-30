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


# -----------------------------
# ENDPOINT 1 — CSV PARSEN
# -----------------------------
@app.post("/parse_csv")
def parse_csv(req: ParseCSVRequest):

    load = parse_csv_to_floats(req.load_file)
    pv = parse_csv_to_floats(req.pv_file)
    prices = parse_csv_to_floats(req.prices_file)

    if len(load) != len(pv) or len(load) != len(prices):
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

    result = compute_scenarios(
        req.load_kwh,
        req.pv_kwh,
        req.prices_dyn,
        req.p_enkel_imp,
        req.p_enkel_exp,
        req.p_dag,
        req.p_nacht,
        req.p_exp_dn,
        req.E,
        req.P,
        req.DoD / 100,
        req.eta_rt / 100,
        req.Vastrecht
    )

    return result
