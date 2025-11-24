from fastapi import FastAPI
from pydantic import BaseModel
from BatteryEngine_Pro import compute_scenarios

app = FastAPI()

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

    # Dynamisch tarief
    p_export_dyn = to_float_or_default(req.p_exp_dn, 0.07)

    # -----------------------------
    # ENGINE AANROEP
    # -----------------------------
    result = compute_scenarios(
        req.load_kwh,
        req.pv_kwh,
        req.prices_dyn,
        p_enkel_imp,     # ← GEEN req.p_enkel_imp meer!
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