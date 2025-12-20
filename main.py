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
from battery_engine_pro3.types import TimeSeries
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

    # 2) Resolutie & timestamps (TimeSeries wordt door andere delen gebruikt)
    n = min(len(req.load_kwh), len(req.pv_kwh))
    dt = detect_resolution(req.load_kwh)

    start = datetime(2025, 1, 1)
    timestamps = [start + timedelta(hours=dt * i) for i in range(n)]

    _load_ts = TimeSeries(timestamps, req.load_kwh[:n], dt)
    _pv_ts = TimeSeries(timestamps, req.pv_kwh[:n], dt)
    # NB: _load_ts/_pv_ts staan hier bewust “unused” zodat je later makkelijk ScenarioRunner kunt her-activeren,
    # maar ze breken niks. Wil je ze weg: kan ook.

    # Omvormerkosten: UI is €/kW/maand, engine verwacht €/kW/jaar
    inverter_cost_per_kw_year = (
        (req.inverter_cost_per_kw_month * 12.0)
        if req.inverter_cost_per_kw_month is not None
        else req.inverter_cost_per_kw
    )    
    
    # 3) Engine input model bouwen
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
        battery_degradation=req.battery_degradation,  # → wordt downstream als degradation_per_year gebruikt
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

    # 4) Engine uitvoeren
    result = BatteryEnginePro3.compute(engine_input)
    return result


# ============================================================
# ADVICE GENERATOR
# ============================================================

class AdviceContext(BaseModel):
    # Land & contract
    country: str
    current_tariff: str

    # Gekozen batterijconfiguratie (zoals ingevoerd)
    battery: dict

    # Volledige tariefmatrix uit de engine
    # (A1, B1, C1 per tarief)
    tariff_matrix: dict

    # ROI-resultaten per tarief
    roi_per_tariff: dict

    # Door backend vastgestelde conclusies
    best_tariff_now: str
    best_tariff_with_battery: str

    # Backend-beoordeling batterij (GEEN AI-logica)
    battery_assessment: dict

class AdviceRequest(BaseModel):
    context: AdviceContext
    draft_text: str


@app.post("/generate_advice")
def generate_advice(req: AdviceRequest):

    # ===============================
    # A4 — CONTEXT OPBOUW (FEITEN)
    # ===============================
    ctx = req.context

    # 1️⃣ Tariefmatrix ophalen (verwacht structuur uit backend)
    tariff_matrix = ctx.tariff_matrix

    # 2️⃣ Goedkoopste tarief ZONDER batterij bepalen
    # (B1 = toekomst zonder batterij)
    costs_without_battery = {
        tariff: vals["B1"]
        for tariff, vals in tariff_matrix.items()
    }
    best_tariff_now = min(costs_without_battery, key=costs_without_battery.get)

    # 3️⃣ Goedkoopste tarief MET batterij bepalen
    # (C1 = toekomst met batterij)
    costs_with_battery = {
        tariff: vals["C1"]
        for tariff, vals in tariff_matrix.items()
    }
    best_tariff_with_battery = min(costs_with_battery, key=costs_with_battery.get)

    # 4️⃣ Context verrijken (AI krijgt dit, niet zelf laten afleiden)
    ctx.best_tariff_now = best_tariff_now
    ctx.best_tariff_with_battery = best_tariff_with_battery

     # 5️⃣ Batterijbeoordeling (FEITELIJK, GEEN AI)
    batt = ctx.battery

    E = batt.get("E", 0)
    P = batt.get("P", 0)

    battery_assessment = {
        "capacity_label": (
            "klein" if E < 5 else
            "middelgroot" if E < 10 else
            "groot"
        ),
        "power_label": (
            "laag" if P < 3 else
            "gemiddeld" if P < 6 else
            "hoog"
        ),
        "notes": []
    }

    if E < 5:
        battery_assessment["notes"].append(
            "De gekozen batterijcapaciteit is relatief klein en dekt vooral kortstondig eigen verbruik."
        )

    if E >= 10:
        battery_assessment["notes"].append(
            "De batterijcapaciteit is ruim en kan meerdere laad- en ontlaadcycli per dag ondersteunen."
        )

    if P < 3:
        battery_assessment["notes"].append(
            "Het laad- en ontlaadvermogen is beperkt, wat de flexibiliteit bij pieken of dynamische prijzen kan verminderen."
        )

    if P >= 6:
        battery_assessment["notes"].append(
            "Het hogere laad- en ontlaadvermogen maakt de batterij geschikt voor snelle respons, zoals bij dynamische tarieven."
        )

    ctx.battery_assessment = battery_assessment    

    if client is None:
        return {
            "error": "NO_OPENAI_KEY",
            "advice": "OpenAI API key ontbreekt — adviesgenerator werkt alleen in productie."
        }

    ctx = req.context

    prompt = f"""
ROL
Je bent een gecertificeerde energieconsultant voor thuisbatterijen.
Je schrijft een professioneel adviesrapport voor een klant.

ZEER BELANGRIJKE REGELS (AFWIJKEN = FOUT):
- Je mag NIET rekenen.
- Je mag GEEN aannames doen.
- Je mag GEEN nieuwe cijfers introduceren.
- Je gebruikt UITSLUITEND de feiten uit het CONTEXT-blok.
- Je vergelijkt en licht toe, je berekent niets zelf.

CONTEXT (FEITEN — LEIDEND):
Land: {ctx.country}
Huidig tarief: {ctx.current_tariff}

Batterij (gekozen configuratie):
{ctx.battery}

Backend-beoordeling batterij:
{ctx.battery_assessment}

Tariefmatrix (jaarlijkse kosten per scenario):
{ctx.tariff_matrix}

ROI per tarief:
{ctx.roi_per_tariff}

Goedkoopste tarief ZONDER batterij: {ctx.best_tariff_now}
Goedkoopste tarief MET batterij: {ctx.best_tariff_with_battery}

TAKEN:
1. Herschrijf de aangeleverde concepttekst tot een helder, professioneel eindadvies.
2. Benoem expliciet:
   - of een ander tarief gunstiger is dan het huidige
   - of dynamisch aantrekkelijker wordt mét batterij
3. Beoordeel of de gekozen batterij (E/P) logisch is:
   - noem wanneer een kleinere of grotere batterij beter past
   - baseer dit uitsluitend op de resultaten (geen nieuwe berekeningen)
4. Schrijf in correct, zakelijk Nederlands.
5. Structuur:
   - Samenvatting
   - Tariefanalyse
   - Batterijbeoordeling
   - Conclusie & advies

CONCEPTTEKST (HERSCHRIJVEN, NIET NEGEREN):
{req.draft_text}
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












