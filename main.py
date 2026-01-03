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

    data_sources: Optional[dict] = None
    calculation_method: Optional[dict] = None
    cost_components: Optional[dict] = None

class AdviceRequest(BaseModel):
    context: AdviceContext
    draft_text: str

# ============================================================
# TARIEFMATRIX — BACKEND TEKSTGENERATOR
# ============================================================

def build_tariff_matrix_text(ctx_dict):
    tariff_matrix = ctx_dict.get("tariff_matrix", {})

    if not tariff_matrix:
        return "Er zijn geen tariefresultaten beschikbaar om te vergelijken."

    lines = []
    lines.append("Overzicht van de jaarlijkse energiekosten per tariefstructuur:")
    lines.append("")

    for tariff_name, values in tariff_matrix.items():
        total_cost = values.get("total_cost_eur")

        if total_cost is None:
            continue

        # Netjes leesbaar voor consument
        if tariff_name == "enkel":
            label = "Enkel tarief"
        elif tariff_name == "dag_nacht":
            label = "Dag- en nachttarief"
        elif tariff_name == "dynamisch":
            label = "Dynamisch tarief"
        else:
            label = tariff_name

        lines.append(f"- {label}: jaarlijkse kosten circa € {round(total_cost, 2)}")

    return "\n".join(lines)


SYSTEM_PROMPT = """
JE MOET JE EXACT AAN ONDERSTAANDE STRUCTUUR HOUDEN.
AFWIJKING IS NIET TOEGESTAAN.

FORMATREGELS (ABSOLUUT):
- Gebruik GEEN Markdown (#, ##, ###)
- Gebruik GEEN eigen koppen
- Gebruik GEEN inleiding, samenvatting of aanbevelingen buiten de structuur
- Schrijf niets vóór sectie 1
- Na sectie 7 MOET je de bijlagen toevoegen (zie hieronder). Schrijf daarna niets meer.

VERPLICHTE STRUCTUUR (LETTERLIJK OVERNEMEN, ZONDER WIJZIGING):

1. Managementsamenvatting
2. Financiële duiding
3. Technische beoordeling & batterijconfiguratie
4. Tariefstrategie & marktcontext
5. Vergelijking van tariefstructuren
[[TARIEFMATRIX]]
6. Conclusie & aanbevolen vervolgstappen
7. Disclaimer

BIJLAGEN — VERPLICHT (NA SECTIE 7, IN DEZE VOLGORDE, ZONDER MARKDOWN):

Bijlage A — Databronnen & uitgangspunten
Bijlage B — Rekenmethodiek & scenario-opzet
Bijlage C — Kostencomponenten & tariefverwerking
Bijlage D — Beperkingen & scope

INHOUDSREGELS:
- Baseer je UITSLUITEND op de aangeleverde JSON-feiten
- Introduceer GEEN aannames
- Introduceer GEEN nieuwe cijfers
- Plaats [[TARIEFMATRIX]] EXACT één keer en op een eigen regel
- Verplaats of hernoem GEEN secties
- Schrijf professioneel, neutraal en adviserend
"""

def _fmt_eur(value):
    try:
        return f"€ {float(value):.2f}".replace(".", ",")
    except Exception:
        return "–"


def build_tariff_matrix_text(ctx: dict) -> str:
    """
    Bouwt de tariefmatrix als leesbare tekst voor de consument,
    uitsluitend op basis van backend-feiten (JSON).
    """

    # Verwachte structuur:
    # ctx["tariff_matrix"] of ctx["A1_per_tariff"]
    matrix = ctx.get("tariff_matrix", {})

    lines = []
    lines.append("Tariefmatrix — jaarlijkse kosten")
    lines.append("")
    lines.append("Scenario                    Enkel        Dag/Nacht     Dynamisch")

    def row(label, data):
        return (
            f"{label:<27}"
            f"{_fmt_eur(data.get('enkel', {}).get('total_cost_eur')):<13}"
            f"{_fmt_eur(data.get('dag_nacht', {}).get('total_cost_eur')):<13}"
            f"{_fmt_eur(data.get('dynamisch', {}).get('total_cost_eur'))}"
        )

    if "A1_per_tariff" in ctx:
        lines.append(row("Huidige situatie", ctx["A1_per_tariff"]))

    if "B1" in ctx:
        lines.append(row("Zonder batterij", ctx["B1"]))

    if "C1" in ctx:
        lines.append(row("Met batterij", ctx["C1"]))

    return "\n".join(lines)

@app.post("/generate_advice")
def generate_advice(req: AdviceRequest):
    ctx = req.context

    if ctx.battery is None:
        ctx.battery = {}

    # ============================
    # ✅ BIJLAGEN-FACTS (backend)
    # ============================

    # Bijlage A — Databronnen & uitgangspunten
    ctx.data_sources = {
        "profiles": {
            "load_kwh": "CSV (meetreeks)",
            "pv_kwh": "CSV (meetreeks)",
            "prices_dyn": "CSV (uurprijzen) of leeg indien niet bruikbaar",
        },
        "country": ctx.country,
        "current_tariff": ctx.current_tariff,
        "battery_input": ctx.battery or {},
        "resolution_rule": ">= 30000 punten → kwartier (0.25u), anders uur (1.0u)",
    }

    # Bijlage B — Rekenmethodiek & scenario-opzet
    ctx.calculation_method = {
        "scenarios": {
            "A1": "Huidige situatie (met saldering in engine)",
            "B1": "Toekomst zonder batterij (zonder saldering in engine)",
            "C1": "Toekomst met batterij (zonder saldering in engine)",
        },
        "battery_dispatch": "regel-gebaseerd (zie battery_simulator.py)",
        "dynamic_pricing": "uurprijzen indien aanwezig; anders niet toegepast",
        "saldering_handling": "saldering True in A1; False in B1/C1",
    }

    # Bijlage C — Kostencomponenten & tariefverwerking
    ctx.cost_components = {
        "energy_costs": "import * tarief - export * vergoeding (afhankelijk van saldering)",
        "fixed_costs": "vastrecht_year",
        "feed_in_costs": "feedin_monthly_cost + staffel (boven feedin_free_kwh)",
        "inverter_costs": "inverter_power_kw * inverter_cost_per_kw(jaar)",
        "capacity_tariff_BE": "alleen BE: verschil piek * capaciteitstarief",
        "roi_method": "ROIEngine: jaarlijkse besparing met degradatie over horizon",
    }
    
    if client is None:
        return {"advice": "OpenAI client niet beschikbaar."}

    ctx_dict = ctx.model_dump()

    prompt = (
        "Schrijf het volledige energieadviesrapport.\n\n"
        "JE MOET JE STRIKT HOUDEN AAN DE STRUCTUUR EN REGELS UIT DE SYSTEM PROMPT.\n\n"
        "VERBODEN:\n"
        "- Markdown, opsommingen of opmaak\n"
        "- Nieuwe cijfers, bedragen of percentages die NIET expliciet in de JSON-feiten staan"
        "- Zelf berekende of afgeleide waarden die niet letterlijk in de JSON aanwezig zijn"
        "- Aannames, garanties of aanbevelingen die niet expliciet uit de feiten volgen\n"
        "- Inleidingen, samenvattingen of teksten buiten de 7 secties\n\n"
        "VERPLICHT:\n"
        "- Begin exact met '1. Managementsamenvatting'\n"
        "- IEDERE SECTIE (1 t/m 7) MOET INHOUDELIJK WORDEN UITGEWERKT IN VOLLEDIGE ALINEA’S"
        "- Sectie 5 mag GEEN tabellen of cijfers bevatten en moet uitsluitend de door de backend aangeleverde tariefmatrix duiden"
        "- HET IS NIET TOEGESTAAN OM ALLEEN TITELS OF KOPPEN TE GEVEN"
        "- IEDERE BIJLAGE (A t/m D) MOET WORDEN UITGEWERKT MET UITLEG"
        "- Na '7. Disclaimer' MOET je direct de bijlagen A t/m D toevoegen\n"
        "- Gebruik voor bijlagen alleen uitleg op basis van de JSON-feiten\n"
        "- Schrijf geen tekst meer na Bijlage D\n"
        "- Gebruik uitsluitend beschrijvende en duidende taal\n"
        "- Baseer je uitsluitend op de aangeleverde JSON-feiten\n\n"
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

        # ============================
        # ✅ GUARDRAIL — TARIEFMATRIX MOET VERVANGEN ZIJN
        # ============================

        if "[[TARIEFMATRIX]]" in content:
            return {
                "error": "TARIEFMATRIX_NOT_REPLACED",
                "advice": content
            }

        # ============================
        # 🛑 GUARDRAIL — TARIEFMATRIX TOKEN AANWEZIGHEID
        # (controle vóór backend-vervanging)
        # ============================

        if content.count("[[TARIEFMATRIX]]") != 1:
            return {
                "error": "TARIEFMATRIX_TOKEN_INVALID_BEFORE_REPLACEMENT",
                "advice": content
            }

        # ============================
        # 🔁 TARIEFMATRIX INJECTIE (BACKEND-LEIDEND)
        # ============================

        try:
            if "[[TARIEFMATRIX]]" in content:
                tariff_text = build_tariff_matrix_text(ctx_dict)

                content = content.replace(
                    "[[TARIEFMATRIX]]",
                    tariff_text,
                    1
                )
        except Exception as e:
            return {
                "error": f"TARIEFMATRIX_REPLACEMENT_FAILED({str(e)})",
                "advice": content
            }

        # ============================
        # 🛑 GUARDRAIL — TARIEFMATRIX TOKEN VERWIJDERD
        # (controle na backend-vervanging)
        # ============================

        if "[[TARIEFMATRIX]]" in content:
            return {
                "error": "TARIEFMATRIX_TOKEN_STILL_PRESENT_AFTER_REPLACEMENT",
                "advice": content
            }

        except Exception as e:
            return {
                "error": f"TARIEFMATRIX_REPLACEMENT_FAILED({str(e)})",
                "advice": content
            }

        # === GUARDRAIL 2: SECTIESTRUCTUUR (NIET BLOKKEREND) ===
        required_sections = [
            "1. Managementsamenvatting",
            "2. Financiële duiding",
            "3. Technische beoordeling & batterijconfiguratie",
            "4. Tariefstrategie & marktcontext",
            "5. Vergelijking van tariefstructuren",
            "6. Conclusie & aanbevolen vervolgstappen",
            "7. Disclaimer",
        ]

        missing_sections = [s for s in required_sections if s not in content]

        if missing_sections:
            return {
                "error": f"SECTIONS_MISSING({', '.join(missing_sections)})",
                "advice": content
            }

        # === GUARDRAIL 3: BIJLAGEN (NIET BLOKKEREND) ===
        required_attachments = [
            "Bijlage A — Databronnen & uitgangspunten",
            "Bijlage B — Rekenmethodiek & scenario-opzet",
            "Bijlage C — Kostencomponenten & tariefverwerking",
            "Bijlage D — Beperkingen & scope",
        ]

        missing_attachments = [a for a in required_attachments if a not in content]

        if missing_attachments:
            return {
                "warning": f"ATTACHMENTS_MISSING({', '.join(missing_attachments)})",
                "advice": content
            }
        
        # ============================
        # OUTPUT — ÉÉN VELD (FRONTEND-LEIDEND)
        # ============================

        return {
            "advice": content.strip()
        }

    except Exception as e:
        return {
            "error": str(e),
            "advice": ""
        }





















