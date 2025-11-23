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