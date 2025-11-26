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
async def parse_csv(load: UploadFile = File(...),
                    pv: UploadFile = File(...),
                    prices: UploadFile = File(...)):
    """
    Parse de drie CSV’s EXACT volgens instructieset §2.
    Retourneert:
    - load_kwh
    - pv_kwh
    - prices_dyn
    """

    # -----------------------------------------
    # Hulpfuncties
    # -----------------------------------------

    def detect_delimiter(text):
        if "\t" in text:
            return "\t"
        semicolons = text.count(";")
        commas = text.count(",")
        if semicolons == 0 and commas == 0:
            return None
        return ";" if semicolons >= commas else ","

    def normalize_number(value):
        if value is None:
            return None
        v = value.strip()
        v = re.sub(r"(kWh|Wh|€|EUR)", "", v, flags=re.IGNORECASE).strip()
        if v == "":
            return None
        if "." in v and "," in v:
            if v.rfind(",") > v.rfind("."):
                v = v.replace(".", "").replace(",", ".")
            else:
                v = v.replace(",", "")
        elif "," in v:
            v = v.replace(",", ".")
        v = v.replace(" ", "")
        try:
            return float(v)
        except:
            return None

    async def process_file(upload: UploadFile):
        raw = (await upload.read()).decode("utf-8", errors="ignore")
        lines = [ln for ln in raw.splitlines() if ln.strip() != ""]
        if len(lines) == 0:
            return []

        delim = detect_delimiter(raw)
        rows = []
        for ln in lines:
            if delim is None:
                rows.append([ln.strip()])
            else:
                rows.append([c.strip() for c in ln.split(delim)])

        header = None
        if any(re.search("[A-Za-z]", c) for c in rows[0]):
            header = [c.lower() for c in rows[0]]
            data_rows = rows[1:]
        else:
            data_rows = rows

        def select_column(header, rows, patterns):
            if header:
                for idx, name in enumerate(header):
                    if any(p in name for p in patterns):
                        return idx

            best_idx = 0
            best_count = 0
            for col in range(len(rows[0])):
                cnt = sum(1 for r in rows if normalize_number(r[col]) is not None)
                if cnt > best_count:
                    best_idx = col
                    best_count = cnt
            return best_idx

        filename = upload.filename.lower()
        if "load" in filename:
            col = select_column(header, data_rows, ["load", "verbruik", "consumption", "import"])
        elif "pv" in filename:
            col = select_column(header, data_rows, ["pv", "solar", "opwek", "injectie", "production"])
        else:
            col = select_column(header, data_rows, ["price", "tarief", "prijs", "eur", "€/kwh"])

        floats = []
        for r in data_rows:
            if col < len(r):
                val = normalize_number(r[col])
                if val is not None:
                    floats.append(val)

        if len(floats) == 0:
            return "INVALID"

        total = len(data_rows)
        valid = len(floats)
        if valid < total * 0.5:
            return "INVALID"

        return floats

    # -----------------------------------------
    # Drie bestanden verwerken
    # -----------------------------------------

    load_kwh = await process_file(load)
    pv_kwh = await process_file(pv)
    prices_dyn = await process_file(prices)

    if load_kwh == "INVALID" or pv_kwh == "INVALID" or prices_dyn == "INVALID":
        return {
            "error": "CSV-bestand ongeldig",
            "load_kwh": [],
            "pv_kwh": [],
            "prices_dyn": []
        }

    return {
        "load_kwh": load_kwh,
        "pv_kwh": pv_kwh,
        "prices_dyn": prices_dyn
    }
