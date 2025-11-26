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


# --------------------------------------------
# CSV NORMALISATIE & PARSING FUNCTIES
# --------------------------------------------
def _normalize_value(raw: str):
    v = raw.strip()

    # Units verwijderen
    for unit in ["kWh", "Wh", "EUR", "€", "/kWh", "€/kWh"]:
        v = v.replace(unit, "")

    # Spaties verwijderen
    v = v.replace(" ", "")

    # Punt+Komma logica
    if "." in v and "," in v:
        if v.rfind(",") > v.rfind("."):
            v = v.replace(".", "").replace(",", ".")
        else:
            v = v.replace(",", "")
    elif "," in v:
        v = v.replace(",", ".")

    try:
        return float(v)
    except:
        return None


def _parse_csv_file(file: UploadFile):
    text = file.file.read().decode("utf-8", errors="ignore")
    lines = [l.strip() for l in text.splitlines() if l.strip()]

    # Delimiter detecteren
    delimiter = None
    for d in ["\t", ";", ","]:
        if any(d in line for line in lines[:5]):
            delimiter = d
            break

    # Rijen parsen
    rows = []
    for line in lines:
        if delimiter:
            rows.append(line.split(delimiter))
        else:
            rows.append([line])

    # Header check
    header = rows[0]
    has_header = any(any(c.isalpha() for c in cell) for cell in header)
    data_rows = rows[1:] if has_header else rows

    # Beste numerieke kolom bepalen
    col_count = max(len(r) for r in data_rows)
    best_col = None
    best_count = -1

    for c in range(col_count):
        count = 0
        for r in data_rows:
            if len(r) > c:
                val = _normalize_value(r[c])
                if val is not None:
                    count += 1
        if count > best_count:
            best_count = count
            best_col = c

    # Parse waarden
    values = []
    for r in data_rows:
        if len(r) > best_col:
            val = _normalize_value(r[best_col])
            if val is not None:
                values.append(val)

    return values


# --------------------------------------------
# /parse_csv ENDPOINT
# --------------------------------------------
@app.post("/parse_csv")
async def parse_csv(
    load_file: UploadFile = File(...),
    pv_file: UploadFile = File(...),
    prices_file: UploadFile = File(...)
):
    load_vals = _parse_csv_file(load_file)
    pv_vals = _parse_csv_file(pv_file)
    prices_vals = _parse_csv_file(prices_file)

    if len(load_vals) == 0 or len(pv_vals) == 0 or len(prices_vals) == 0:
        return {"error": "Parsing failed"}

    return {
        "load_kwh": load_vals,
        "pv_kwh": pv_vals,
        "prices_dyn": prices_vals
    }
