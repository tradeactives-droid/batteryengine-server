# ============================================================
# BatteryEngine Pro 2 — Backend API
# SERVER.PY  (definitieve versie)
# ============================================================

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from BatteryEngine_Pro2 import compute_scenarios_v2

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)

class ComputeRequest(BaseModel):
    load_kwh: list[float]
    pv_kwh: list[float]
    prices_dyn: list[float]

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

