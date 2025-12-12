# ============================================================
# BatteryEngine Pro — Backend API
# COMPLETE MAIN.PY (parse_csv + compute_v3 + advice)
# ============================================================

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from datetime import datetime, timedelta

# OpenAI (mag falen als KEY ontbreekt — client blijft dan None)
from openai import OpenAI

# Engine imports
from battery_engine_pro3.scenario_runner import ScenarioRunner
from battery_engine_pro3.types import TimeSeries, TariffConfig, BatteryConfig
from battery_engine_pro3.engine import BatteryEnginePro3, ComputeV3Input


# ============================================================
# FASTAPI INIT
# ============================================================

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
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


@app.options("/{rest_of_path:path}")
async def preflight_handler():
    return {}


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
            except:
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

    load_ts = TimeSeries(timestamps, req.load_kwh[:n], dt)
    pv_ts = TimeSeries(timestamps, req.pv_kwh[:n], dt)

    # 3) Tariefconfig
    tariff_cfg = TariffConfig(
        country=req.country,
        current_tariff=req.current_tariff,

        p_enkel_imp=req.p_enkel_imp,
        p_enkel_exp=req.p_enkel_exp,

        p_dag=req.p_dag,
        p_nacht=req.p_nacht,
        p_exp_dn=req.p_exp_dn,

        p_export_dyn=req.p_export_dyn,
        dynamic_prices=req.prices_dyn,

        vastrecht_year=req.vastrecht_year,

        feedin_monthly_cost=req.feedin_monthly_cost,
        feedin_cost_per_kwh=req.feedin_cost_per_kwh,
        feedin_free_kwh=req.feedin_free_kwh,
        feedin_price_after_free=req.feedin_price_after_free,

        inverter_power_kw=req.inverter_power_kw,
        inverter_cost_per_kw=req.inverter_cost_per_kw,

        capacity_tariff_kw=req.capacity_tariff_kw
    )

    # 4) Batterijconfig
    batt_cfg = BatteryConfig(
        E=req.E,
        P=req.P,
        DoD=req.DoD,
        eta_rt=req.eta_rt,
        investment_eur=req.battery_cost,
        degradation=req.battery_degradation
    )

    # 5) Engine input model bouwen
    engine_input = ComputeV3Input(
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
        vastrecht=req.vastrecht_year,

        battery_cost=req.battery_cost,
        battery_degradation=req.battery_degradation,

        feedin_monthly_cost=req.feedin_monthly_cost,
        feedin_cost_per_kwh=req.feedin_cost_per_kwh,
        feedin_free_kwh=req.feedin_free_kwh,
        feedin_price_after_free=req.feedin_price_after_free,

        inverter_power_kw=req.inverter_power_kw,
        inverter_cost_per_kw_year=req.inverter_cost_per_kw,

        capacity_tariff_kw_year=req.capacity_tariff_kw,

        country=req.country,
        current_tariff=req.current_tariff,
    )

    # 6) Engine uitvoeren
    result = BatteryEnginePro3.compute(engine_input)
    return result


# ============================================================
# ADVICE GENERATOR
# ============================================================

class AdviceRequest(BaseModel):
    country: str
    battery: dict
    results: dict


@app.post("/generate_advice")
def generate_advice(req: AdviceRequest):

    if client is None:
        return {
            "error": "NO_OPENAI_KEY",
            "advice": "OpenAI API key ontbreekt — adviesgenerator werkt alleen in productie."
        }

    prompt = f"""
Je bent een professionele energieconsultant gespecialiseerd in thuisbatterijen.

Genereer een helder, volledig en zakelijk adviesrapport op basis van:

Land: {req.country}
Batterijconfiguratie:
{req.battery}

Resultaten:
{req.results}

Schrijf een adviesrapport met:
1. Executive summary
2. Financiële analyse
3. Energetische analyse
4. Land-specifiek advies (NL / BE)
5. Aankoopadvies (capaciteit + vermogen)
6. Samenvatting voor offerte
"""

    try:
        response = client.chat.completions.create(
            model="gpt-5.1",
            messages=[
                {"role": "system", "content": "Je bent een gecertificeerde energieconsultant gespecialiseerd in thuisbatterijen."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=1200,
            temperature=0.3,
        )
        return {"advice": response.choices[0].message.content}

    except Exception as e:
        return {
            "error": str(e),
            "advice": "Er is een fout opgetreden bij het genereren van het advies."
        }
