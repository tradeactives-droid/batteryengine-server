from fastapi import FastAPI, UploadFile, File
from pydantic import BaseModel
from BatteryEngine_Pro import compute_scenarios

app = FastAPI()


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
    p_exp_dn: float
    E: float
    P: float
    DoD: float
    eta_rt: float
    Vastrecht: float


# --------------------------------------------
# /compute ENDPOINT
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

    # Dynamisch tarief (export)
    p_export_dyn = to_float_or_default(req.p_exp_dn, 0.07)

    # -----------------------------
    # ENGINE AANROEP
    # -----------------------------
    result = compute_scenarios(
        req.load_kwh,
        req.pv_kwh,
        req.prices_dyn,
        p_enkel_imp,
        p_enkel_exp,
        p_dag,
        p_nacht,
        p_exp_dn,
        req.E,
        req.P,
        req.DoD,
        req.eta_rt,
        req.Vastrecht
    )

    return {
        "S1": result[0],
        "S2_enkel": result[1],
        "S2_dn": result[2],
        "S2_dyn": result[3],
        "S3_enkel": result[4],
        "S3_dn": result[5],
        "S3_dyn": result[6]
    }


from fastapi import File, UploadFile
import csv
import io
import re

@app.post("/parse_csv")
async def parse_csv(
    load_file: UploadFile = File(...),
    pv_file: UploadFile = File(...),
    prices_file: UploadFile = File(...)
):
    """
    Correcte parameter-namen volgens OpenAPI:
    - load_file
    - pv_file
    - prices_file
    """

    async def process_file(upload: UploadFile):
        raw = (await upload.read()).decode("utf-8", errors="ignore")
        lines = [ln for ln in raw.splitlines() if ln.strip() != ""]
        if len(lines) == 0:
            return []

        # detect delimiter
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

        # skip header if alpha in row
        if any(char.isalpha() for char in rows[0][0]):
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

    load_kwh = await process_file(load_file)
    pv_kwh = await process_file(pv_file)
    prices_dyn = await process_file(prices_file)

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



