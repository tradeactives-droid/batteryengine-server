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

# OpenAI (mag falen als KEY ontbreekt — client blijft dan None)
from openai import OpenAI

# Engine imports
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

# OpenAI client — veilig i.v.m. CI-tests (geen key → client=None)
client = None
try:
    client = OpenAI()
except Exception:
    pass


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
    lines = [ln for ln in raw.splitlines() if ln.strip() != ""]
    if len(lines) == 0:
        return []

    delim = ";"
    if ";" not in raw and "," in raw:
        delim = ","

    rows = []
    for ln in lines:
        rows.append([c.strip() for c in ln.split(delim)])

    # Header verwijderen indien aanwezig
    if any(ch.isalpha() for ch in rows[0][0]):
        rows = rows[1:]

    floats = []
    for r in rows:
        for c in r:
            c = c.replace(",", ".")
            try:
                floats.append(float(c))
                break
            except Exception:
                continue

    if len(floats) < 10:
        return []

    return floats


def detect_resolution(load: list[float]) -> float:
    """>= 30.000 punten → kwartierwaarden (0.25 uur), anders uurwaarden."""
    if len(load) >= 30000:
        return 0.25
    return 1.0


@app.post("/parse_csv")
def parse_csv(req: ParseCSVRequest):
    load = _process_csv_text(req.load_file)
    pv = _process_csv_text(req.pv_file)

    MIN_POINTS = 20000
    if len(load) < MIN_POINTS or len(pv) < MIN_POINTS:
        return {"load_kwh": [], "pv_kwh": [], "prices_dyn": [], "error": "NOT_ENOUGH_DATA_FOR_FLUVIUS"}

    prices_raw = req.prices_file if req.prices_file is not None else ""
    prices = _process_csv_text(prices_raw) if prices_raw.strip() != "" else []

    if not load or not pv:
        return {"load_kwh": [], "pv_kwh": [], "prices_dyn": [], "error": "INVALID_LOAD_PV"}

    n = min(len(load), len(pv))
    load = load[:n]
    pv = pv[:n]

    if prices and len(prices) == n:
        prices_dyn = prices
    else:
        prices_dyn = []

    return {
        "load_kwh": load,
        "pv_kwh": pv,
        "prices_dyn": prices_dyn
    }


# ============================================================
# COMPUTE_V3 ENDPOINT (Pro 3)
# ============================================================

class ComputeV3Request(BaseModel):
    # PROFIELEN
    load_kwh: list[float]
    pv_kwh: list[float]
    prices_dyn: list[float] | None = None

    # BATTERIJ
    E: float
    P: float
    DoD: float
    eta_rt: float
    battery_cost: float
    battery_degradation: float
    battery_lifetime_years: int = 15

    # TARIEF / LAND
    country: str
    current_tariff: str

    # TARIEVEN
    p_enkel_imp: float
    p_enkel_exp: float

    p_dag: float
    p_nacht: float
    p_exp_dn: float

    p_export_dyn: float

    # VASTRECHT
    vastrecht_year: float

    # TERUGLEVERKOSTEN / OMVORMER
    feedin_monthly_cost: float = 0.0
    feedin_cost_per_kwh: float = 0.0
    feedin_free_kwh: float = 0.0
    feedin_price_after_free: float = 0.0

    inverter_power_kw: float = 0.0
    inverter_cost_per_kw: float = 0.0
    inverter_cost_per_kw_month: float | None = None

    # BE — capaciteitstarief
    capacity_tariff_kw: float = 0.0


@app.post("/compute_v3")
def compute_v3(req: ComputeV3Request):

    # 1) Validatie
    if not req.load_kwh or not req.pv_kwh:
        return {"error": "LOAD_OR_PV_EMPTY"}

    # 2) Resolutie & timestamps
    n = min(len(req.load_kwh), len(req.pv_kwh))
    dt = detect_resolution(req.load_kwh)

    start = datetime(2025, 1, 1)
    timestamps = [start + timedelta(hours=dt * i) for i in range(n)]

    _load_ts = TimeSeries(timestamps, req.load_kwh[:n], dt)
    _pv_ts = TimeSeries(timestamps, req.pv_kwh[:n], dt)

    inverter_cost_per_kw_year = (
        (req.inverter_cost_per_kw_month * 12.0)
        if req.inverter_cost_per_kw_month is not None
        else req.inverter_cost_per_kw
    )

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
        inverter_cost_per_kw_year=inverter_cost_per_kw_year,

        capacity_tariff_kw_year=req.capacity_tariff_kw,

        country=req.country,
        current_tariff=req.current_tariff,
    )

    result = BatteryEnginePro3.compute(engine_input)
    return result


# ============================================================
# ADVICE GENERATOR
# ============================================================

class AdviceContext(BaseModel):
    country: str
    current_tariff: str

    battery: dict
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
Je bent een onafhankelijk energieadviesbureau.
Je baseert je uitsluitend op de aangeleverde feiten.
Je doet GEEN aannames en introduceert GEEN nieuwe cijfers.

STRUCTUUR — VERPLICHT:
Gebruik exact deze secties en nummering:

1. Managementsamenvatting
2. Financiële duiding
3. Technische beoordeling & batterijconfiguratie
4. Tariefstrategie & marktcontext
5. Vergelijking van tariefstructuren
[[TARIEFMATRIX]]
6. Conclusie & aanbevolen vervolgstappen
7. Disclaimer

REGELS:
- Gebruik ALLEEN de aangeleverde context
- Verzin GEEN technische of financiële aannames
- Plaats [[TARIEFMATRIX]] exact één keer
- Verplaats of hernoem GEEN secties
- Schrijf professioneel, neutraal en adviserend
"""

@app.post("/generate_advice")
def generate_advice(req: AdviceRequest):

    ctx = req.context
    tariff_matrix = ctx.tariff_matrix

    # Goedkoopste tarief zonder batterij
    costs_without_battery = {
        tariff: vals.get("without_battery")
        for tariff, vals in tariff_matrix.items()
        if isinstance(vals, dict) and vals.get("without_battery") is not None
    }
    ctx.best_tariff_now = (
        min(costs_without_battery, key=costs_without_battery.get)
        if costs_without_battery else None
    )

    # Goedkoopste tarief met batterij
    costs_with_battery = {
        tariff: vals.get("with_battery")
        for tariff, vals in tariff_matrix.items()
        if isinstance(vals, dict) and vals.get("with_battery") is not None
    }
    ctx.best_tariff_with_battery = (
        min(costs_with_battery, key=costs_with_battery.get)
        if costs_with_battery else None
    )

    "notes": []
}

    ctx.saldering_context = {
    "current_situation": (
        "De huidige situatie is gebaseerd op de geldende salderingsregeling, "
        "waarbij teruggeleverde zonnestroom wordt verrekend met afgenomen elektriciteit."
    ),
    "future_scenarios": (
        "De doorgerekende scenario’s zonder batterij en met batterij "
        "representeren een situatie zonder salderingsregeling."
    ),
    "policy_impact": (
        "In een situatie zonder salderingsregeling wordt teruglevering financieel "
        "anders behandeld, waardoor vaste en traditionele tarieven "
        "relatief ongunstiger uitvallen bij hoge teruglevering."
    )
}

    if client is None:
        return {
            "advice": ""
        }

    ctx_dict = ctx.model_dump() if hasattr(ctx, "model_dump") else ctx.dict()

    prompt = (
        "Feiten (JSON):\n"
        + json.dumps(ctx_dict, ensure_ascii=False, indent=2)
        + "\n\nGebruik deze feiten om het adviesrapport te schrijven conform de instructies."
    )

    try:
    response = client.chat.completions.create(
        model="gpt-4.1",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt}
        ],
        max_tokens=1200,
        temperature=0.3,
    )

    content = response.choices[0].message.content

    # === TARIEFMATRIX TOKEN CHECK ===
    token = "[[TARIEFMATRIX]]"
    token_count = content.count(token)

    if token_count != 1:
        return {
            "error": f"TARIEFMATRIX_TOKEN_INVALID(count={token_count})",
            "advice": ""
        }

    # === SECTIE CHECK ===
    required_sections = [
        "1. Managementsamenvatting",
        "2. Financiële duiding",
        "3. Technische beoordeling & batterijconfiguratie",
        "4. Tariefstrategie & marktcontext",
        "5. Vergelijking van tariefstructuren",
        "6. Conclusie & aanbevolen vervolgstappen",
        "7. Disclaimer",
    ]

    missing = [s for s in required_sections if s not in content]

    if missing:
        return {
            "error": f\"ADVICE_SECTIONS_MISSING({', '.join(missing)})\",
            "advice": ""
        }

    return {"advice": content}

except Exception as e:
    return {
        "error": str(e),
        "advice": ""
    }





















