# ============================================================
# BatteryEngine Pro — Backend API
# COMPLETE MAIN.PY (parse_csv + compute_v3 + advice)
# ============================================================

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from datetime import datetime, timedelta
from typing import Optional
import json

from openai import OpenAI

from battery_engine_pro3.types import TimeSeries
from battery_engine_pro3.engine import BatteryEnginePro3, ComputeV3Input


# ============================================================
# FASTAPI INIT
# ============================================================

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://thuisbatterij-calculator-web.onrender.com"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)

from openai import OpenAI
import os

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

if not OPENAI_API_KEY:
    raise RuntimeError("OPENAI_API_KEY ontbreekt in environment")

client = OpenAI(api_key=OPENAI_API_KEY)


# ============================================================
# CSV PARSER
# ============================================================

class ParseCSVRequest(BaseModel):
    load_file: str
    pv_file: str
    prices_file: str


def _process_csv_text(raw: str) -> list[float]:
    if raw is None:
        return []

    raw = str(raw)
    lines = [ln for ln in raw.splitlines() if ln.strip()]
    if not lines:
        return []

    delim = ";" if ";" in raw else ","
    rows = [[c.strip() for c in ln.split(delim)] for ln in lines]

    if any(ch.isalpha() for ch in rows[0][0]):
        rows = rows[1:]

    values = []
    for r in rows:
        for c in r:
            try:
                values.append(float(c.replace(",", ".")))
                break
            except Exception:
                continue

    return values if len(values) >= 10 else []


def detect_resolution(load: list[float]) -> float:
    return 0.25 if len(load) >= 30000 else 1.0


@app.post("/parse_csv")
def parse_csv(req: ParseCSVRequest):
    load = _process_csv_text(req.load_file)
    pv = _process_csv_text(req.pv_file)

    if len(load) < 20000 or len(pv) < 20000:
        return {"error": "NOT_ENOUGH_DATA"}

    prices = _process_csv_text(req.prices_file)
    n = min(len(load), len(pv))

    return {
        "load_kwh": load[:n],
        "pv_kwh": pv[:n],
        "prices_dyn": prices[:n] if len(prices) == n else []
    }


# ============================================================
# COMPUTE V3
# ============================================================

class ComputeV3Request(BaseModel):
    load_kwh: list[float]
    pv_kwh: list[float]
    prices_dyn: Optional[list[float]] = None

    E: float
    P: float
    DoD: float
    eta_rt: float

    battery_cost: float
    battery_degradation: float
    battery_lifetime_years: int

    country: str
    current_tariff: str

    p_enkel_imp: float
    p_enkel_exp: float
    p_dag: float
    p_nacht: float
    p_exp_dn: float
    p_export_dyn: float

    vastrecht_year: float

    feedin_monthly_cost: float = 0.0
    feedin_cost_per_kwh: float = 0.0
    feedin_free_kwh: float = 0.0
    feedin_price_after_free: float = 0.0

    inverter_power_kw: float = 0.0
    inverter_cost_per_kw: float = 0.0
    inverter_cost_per_kw_month: Optional[float] = None

    capacity_tariff_kw: float = 0.0


@app.post("/compute_v3")
def compute_v3(req: ComputeV3Request):
    if not req.load_kwh or not req.pv_kwh:
        return {"error": "LOAD_OR_PV_EMPTY"}

    n = min(len(req.load_kwh), len(req.pv_kwh))
    dt = detect_resolution(req.load_kwh)

    engine_input = ComputeV3Input(
        load_kwh=req.load_kwh[:n],
        pv_kwh=req.pv_kwh[:n],
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
        vastrecht=req.vastrecht_year,

        battery_cost=req.battery_cost,
        battery_degradation=req.battery_degradation,
        battery_lifetime_years=req.battery_lifetime_years,

        feedin_monthly_cost=req.feedin_monthly_cost,
        feedin_cost_per_kwh=req.feedin_cost_per_kwh,
        feedin_free_kwh=req.feedin_free_kwh,
        feedin_price_after_free=req.feedin_price_after_free,

        inverter_power_kw=req.inverter_power_kw,
        inverter_cost_per_kw_year=(
            req.inverter_cost_per_kw_month * 12
            if req.inverter_cost_per_kw_month
            else req.inverter_cost_per_kw
        ),

        capacity_tariff_kw_year=req.capacity_tariff_kw,
        country=req.country,
        current_tariff=req.current_tariff,
    )

    return BatteryEnginePro3.compute(engine_input)


# ============================================================
# ADVICE GENERATOR
# ============================================================

class AdviceContext(BaseModel):
    country: str
    current_tariff: str

    battery: Optional[dict] = None
    energy_profile: Optional[dict] = None
    extra_consumers: Optional[dict] = None

    tariff_matrix: dict
    roi_per_tariff: dict

    best_tariff_now: Optional[str] = None
    best_tariff_with_battery: Optional[str] = None
    battery_assessment: Optional[dict] = None
    saldering_context: Optional[dict] = None


class AdviceRequest(BaseModel):
    context: AdviceContext
    draft_text: str


SYSTEM_PROMPT = """
JE MOET JE EXACT AAN ONDERSTAANDE STRUCTUUR HOUDEN.
AFWIJKING IS NIET TOEGESTAAN.

FORMATREGELS (ABSOLUUT):
- Gebruik GEEN Markdown (#, ##, ###)
- Gebruik GEEN eigen koppen
- Gebruik GEEN inleiding, samenvatting of aanbevelingen buiten de structuur
- Schrijf niets vóór sectie 1
- Schrijf niets ná sectie 7

VERPLICHTE STRUCTUUR (LETTERLIJK OVERNEMEN, ZONDER WIJZIGING):

1. Managementsamenvatting
2. Financiële duiding
3. Technische beoordeling & batterijconfiguratie
4. Tariefstrategie & marktcontext
5. Vergelijking van tariefstructuren
[[TARIEFMATRIX]]
6. Conclusie & aanbevolen vervolgstappen
7. Disclaimer

INHOUDSREGELS:
- Baseer je UITSLUITEND op de aangeleverde JSON-feiten
- Introduceer GEEN aannames
- Introduceer GEEN nieuwe cijfers
- Plaats [[TARIEFMATRIX]] EXACT één keer en op een eigen regel
- Verplaats of hernoem GEEN secties
- Schrijf professioneel, neutraal en adviserend
"""


@app.post("/generate_advice")
def generate_advice(req: AdviceRequest):
    ctx = req.context

    if ctx.battery is None:
        ctx.battery = {}

    if client is None:
        return {"advice": "OpenAI client niet beschikbaar."}

    ctx_dict = ctx.model_dump()

    prompt = (
        "GENEREER NU HET ADVIESRAPPORT.\n"
        "VOLG DE STRUCTUUR UIT DE SYSTEM INSTRUCTIES LETTERLIJK.\n"
        "SCHRIJF GEEN ANDERE KOPPEN OF TEKST.\n"
        "GEBRUIK GEEN MARKDOWN.\n"
        "BEGIN DIRECT MET '1. Managementsamenvatting'.\n"
        "EINDIG NA '7. Disclaimer'.\n\n"
        "FEITEN (JSON):\n"
        + json.dumps(ctx_dict, ensure_ascii=False, indent=2)
    )

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt}
            ],
            max_tokens=1200,
            temperature=0.3,
        )

        content = response.choices[0].message.content

        # === GUARDRAIL 1: TARIEFMATRIX TOKEN ===
        token = "[[TARIEFMATRIX]]"
        token_count = content.count(token)

        if token_count != 1:
            return {
                "error": f"TARIEFMATRIX_TOKEN_INVALID(count={token_count})",
                "advice": content
            }
        
        return {"advice": content}

    except Exception as e:
        return {
            "error": str(e),
            "advice": ""
        }





