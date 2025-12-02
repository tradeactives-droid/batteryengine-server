from fastapi import FastAPI
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware

from BatteryEngine_Pro2 import compute_scenarios_v2  # <<< nieuwe engine

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # later kun je dit beperken
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --------------------------------------------
# REQUESTMODEL VOOR /compute
# --------------------------------------------
class RequestModel(BaseModel):
    load_kwh: list[float]
    pv_kwh: list[float]
    prices_dyn: list[float]

    p_enkel_imp: float
    p_enkel_exp: float
    p_dag: float
    p_nacht: float
    p_exp_dn: float       # export bij dag/nacht
    # let op: p_export_dyn komt uit frontend maar zit niet in RequestModel;
    # die pakken we zo uit prices_dyn of geven default in de engine

    E: float
    P: float
    DoD: float
    eta_rt: float
    Vastrecht: float


# --------------------------------------------
# /compute ENDPOINT (v2)
# --------------------------------------------
@app.post("/compute")
def compute(req: RequestModel):

    # -----------------------------
    # FALLBACKS TARIEVEN (SAFE MODE)
    # -----------------------------
    def to_float_or_default(value, default):
        if value is None:
            return default
        if value == "":
            return default
        if isinstance(value, str) and value.lower().strip() == "standaardwaarden":
            return default
        try:
            return float(value)
        except:
            return default

    # Enkel tarief
    p_enkel_imp = to_float_or_default(req.p_enkel_imp, 0.40)
    p_enkel_exp = to_float_or_default(req.p_enkel_exp, 0.08)

    # Dag/Nacht tarief
    p_dag = to_float_or_default(req.p_dag, 0.45)
    p_nacht = to_float_or_default(req.p_nacht, 0.23)
    p_exp_dn = to_float_or_default(req.p_exp_dn, 0.08)

    # Dynamisch tarief (export) – default 0.07
    p_export_dyn = 0.07

    # -----------------------------
    # ENGINE AANROEP (v2)
    # -----------------------------
    result = compute_scenarios_v2(
        load_kwh=req.load_kwh,
        pv_kwh=req.pv_kwh,
        prices_dyn=req.prices_dyn,   # uurprijzen import dynamisch

        p_enkel_imp=p_enkel_imp,
        p_enkel_exp=p_enkel_exp,
        p_dag=p_dag,
        p_nacht=p_nacht,
        p_exp_dn=p_exp_dn,
        p_export_dyn=p_export_dyn,

        E=req.E,
        P=req.P,
        DoD=req.DoD,
        eta_rt=req.eta_rt,
        vastrecht=req.Vastrecht,
    )

    # result is al een nette dict met A1_current, B1_future_no_batt, C1..., S2_enkel, S3_enkel etc.
    return result


# ======================================================================
# NIEUWE CSV-PARSER: ONTVANGT RAAKTEKST (STRING) I.P.V. BESTANDEN
# ======================================================================

class ParseCSVRequest(BaseModel):
    load_file: str
    pv_file: str
    prices_file: str


def _process_csv_text(raw: str) -> list[float]:
    """
    Verwerkt de rauwe CSV-tekst (zoals uit een bestand gelezen) tot een lijst floats.
    - accepteert ; of , als scheidingsteken
    - slaat eventuele header over
    """
    if raw is None:
        return []

    # zorg dat we een string hebben
    raw = str(raw)
    lines = [ln for ln in raw.splitlines() if ln.strip() != ""]
    if len(lines) == 0:
        return []

    # delimiter detectie
    if ";" in raw:
        delim = ";"
    elif "," in raw:
        delim = ","
    else:
        delim = None

    rows = []
    for ln in lines:
        if delim is None:
            rows.append([ln.strip()])
        else:
            rows.append([c.strip() for c in ln.split(delim)])

    # header skippen als er letters in de eerste rij zitten
    if any(char.isalpha() for char in rows[0][0]):
        rows = rows[1:]

    floats: list[float] = []
    for r in rows:
        for c in r:
            c = c.replace(",", ".")
            try:
                f = float(c)
                floats.append(f)
                break
            except:
                continue

    # simpele sanity-check
    if len(floats) < 10:
        return []

    return floats


@app.post("/parse_csv")
def parse_csv(req: ParseCSVRequest):
    """
    Ontvangt drie stukken CSV-tekst (strings) en geeft drie lijsten floats terug.
    """
    load_kwh = _process_csv_text(req.load_file)
    pv_kwh = _process_csv_text(req.pv_file)
    prices_dyn = _process_csv_text(req.prices_file)

    if not load_kwh or not pv_kwh or not prices_dyn:
        return {
            "load_kwh": [],
            "pv_kwh": [],
            "prices_dyn": [],
            "error": "INVALID"
        }

    return {
        "load_kwh": load_kwh,
        "pv_kwh": pv_kwh,
        "prices_dyn": prices_dyn
    }
