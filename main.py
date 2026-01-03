# ============================================================
# BatteryEngine Pro — Backend API
# COMPLETE MAIN.PY (parse_csv + compute_v3 + advice)
# ============================================================

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
import json
import os

from openai import OpenAI

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
# TARIEFMATRIX — FORMATTEERHULP
# ============================================================

def _fmt_eur(value):
    try:
        return f"€ {float(value):.2f}".replace(".", ",")
    except Exception:
        return "–"


def build_tariff_matrix_text(ctx: dict) -> str:
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


SYSTEM_PROMPT = """
JE MOET JE EXACT AAN ONDERSTAANDE STRUCTUUR HOUDEN.
AFWIJKING IS NIET TOEGESTAAN.

FORMATREGELS (ABSOLUUT):
- Gebruik GEEN Markdown
- Gebruik GEEN tabellen, kolommen, kopjes of matrix-structuren
- Schrijf GEEN woorden zoals "Tariefmatrix", "Scenario", "Enkel", "Dag/Nacht", "Dynamisch" als losse regels of koppen
- In sectie 5 mag ALLEEN beschrijvende lopende tekst staan
- Schrijf niets vóór sectie 1
- Na sectie 7 MOET je de bijlagen toevoegen

VERPLICHTE STRUCTUUR:

1. Managementsamenvatting
2. Financiële duiding
3. Technische beoordeling & batterijconfiguratie
4. Tariefstrategie & marktcontext
5. Vergelijking van tariefstructuren
6. Conclusie & aanbevolen vervolgstappen
7. Disclaimer

Bijlage A — Databronnen & uitgangspunten
Bijlage B — Rekenmethodiek & scenario-opzet
Bijlage C — Kostencomponenten & tariefverwerking
Bijlage D — Beperkingen & scope
"""


@app.post("/generate_advice")
def generate_advice(req: AdviceRequest):
    ctx = req.context
    ctx_dict = ctx.model_dump()

    # ============================
    # BIJLAGE A — DATABRONNEN & UITGANGSPUNTEN
    # ============================

    ctx_dict["appendix_A"] = {
        "verbruiksdata": (
            "Het elektriciteitsverbruik is gebaseerd op door de gebruiker aangeleverde "
            "CSV-meetreeksen. Deze meetreeksen vormen de basis voor het vaststellen van "
            "het jaarlijkse verbruik, piekbelastingen en het tijdsprofiel van de afname."
        ),
        "opwekdata": (
            "De zonne-energieproductie is gebaseerd op aangeleverde CSV-bestanden met "
            "meetwaarden van PV-opwek. Deze data is gebruikt om directe zelfconsumptie, "
            "teruglevering en overschotten te bepalen."
        ),
        "tariefdata": (
            "De energietarieven zijn afkomstig uit de door de gebruiker ingevoerde "
            "tariefinstellingen, inclusief import- en exporttarieven per tariefstructuur."
        ),
        "batterijgegevens": (
            "De batterijconfiguratie is gebaseerd op de opgegeven capaciteit (kWh) en "
            "het maximale laad- en ontlaadvermogen (kW). Deze parameters bepalen de "
            "technische inzet van de batterij in de simulatie."
        ),
        "algemene_uitgangspunten": (
            "Alle berekeningen zijn uitgevoerd op basis van historische meetdata. "
            "Er zijn geen aannames gedaan over toekomstig gedrag, prijsevoluties "
            "of wijzigingen in regelgeving."
        ),
    }

    # ============================
    # BIJLAGE B — REKENMETHODIEK & SCENARIO-OPZET
    # ============================

    ctx_dict["appendix_B"] = {
        "scenario_definitie": (
            "Er zijn meerdere scenario’s doorgerekend om de impact van tariefstructuren "
            "en batterij-inzet inzichtelijk te maken. Elk scenario gebruikt dezelfde "
            "verbruiks- en opwekdata, zodat de uitkomsten onderling vergelijkbaar zijn."
        ),
        "scenario_A1": (
            "Scenario A1 beschrijft de huidige situatie zonder wijzigingen. Hierbij "
            "wordt gerekend met de bestaande tariefstructuur en zonder actieve inzet "
            "van een thuisbatterij."
        ),
        "scenario_B1": (
            "Scenario B1 simuleert een toekomstige situatie zonder batterij, waarbij "
            "saldering niet wordt toegepast. Dit scenario laat zien wat het effect is "
            "van veranderende regelgeving zonder technische compensatie."
        ),
        "scenario_C1": (
            "Scenario C1 beschrijft een situatie met thuisbatterij, eveneens zonder "
            "saldering. De batterij wordt ingezet om zelfconsumptie te verhogen en "
            "netafname te beperken binnen de technische grenzen van het systeem."
        ),
        "batterij_dispatch": (
            "De batterij wordt regel-gebaseerd aangestuurd. Dit betekent dat de batterij "
            "laadt bij overschot aan zonneproductie en ontlaadt bij elektriciteitsvraag, "
            "zonder optimalisatie op basis van prijsvoorspellingen."
        ),
        "tariefverwerking": (
            "Voor elk scenario zijn de relevante tariefstructuren toegepast zoals "
            "aangeleverd in de invoer. Dynamische tarieven worden alleen gebruikt "
            "wanneer uurprijzen beschikbaar zijn."
        ),
    }

    # ============================
    # BIJLAGE C — KOSTENCOMPONENTEN & TARIEFVERWERKING
    # ============================

    ctx_dict["appendix_C"] = {
        "energiekosten": (
            "De energiekosten bestaan uit elektriciteit die uit het net wordt afgenomen "
            "en elektriciteit die wordt teruggeleverd. De kosten worden berekend op basis "
            "van de geldende tarieven per scenario."
        ),
        "import_en_export": (
            "Netafname en teruglevering worden afzonderlijk geregistreerd. Afhankelijk "
            "van de tariefstructuur en het scenario worden deze volumes verrekend volgens "
            "vaste of dynamische tarieven."
        ),
        "vastrecht": (
            "Vaste kosten zoals vastrecht worden meegenomen als jaarlijkse kostenpost, "
            "onafhankelijk van het daadwerkelijke elektriciteitsverbruik."
        ),
        "terugleverkosten": (
            "Indien van toepassing worden kosten voor teruglevering meegenomen, zoals "
            "maandelijkse bijdragen of staffels boven een vrijgestelde hoeveelheid."
        ),
        "inverter_en_vermogen": (
            "Wanneer relevant worden kosten voor omvormervermogen meegenomen op basis "
            "van het opgegeven vermogen en bijbehorende kostengrondslag."
        ),
        "capaciteitstarief": (
            "Voor landen waar een capaciteitstarief geldt, wordt rekening gehouden met "
            "de hoogste gemeten vermogensafname binnen de berekende periode."
        ),
    }

    # ============================
    # BIJLAGE D — BEPERKINGEN & SCOPE
    # ============================

    ctx_dict["appendix_D"] = {
        "modelmatige_benadering": (
            "Dit advies is gebaseerd op een modelmatige berekening van energieverbruik, "
            "opwekking en batterijgedrag. Werkelijke resultaten kunnen afwijken door "
            "gedragsveranderingen, weersinvloeden en technische beperkingen."
        ),
        "geen_garantie": (
            "De gepresenteerde uitkomsten geven een indicatie op basis van ingevoerde "
            "gegevens en vormen geen garantie voor toekomstige besparingen of rendement."
        ),
        "tarief_en_marktveranderingen": (
            "Energieprijzen, contractvoorwaarden en regelgeving kunnen in de toekomst "
            "wijzigen en zijn niet voorspelbaar binnen deze analyse."
        ),
        "technische_implementatie": (
            "De daadwerkelijke prestaties van een batterij zijn afhankelijk van installatie, "
            "aansturing, onderhoud en compatibiliteit met bestaande systemen."
        ),
        "geen_vervangend_advies": (
            "Dit rapport is bedoeld als besluitondersteunend hulpmiddel en vervangt geen "
            "persoonlijk advies van een installateur, leverancier of energieadviseur."
        ),
    }
    
    prompt = (
        "Schrijf het volledige energieadviesrapport.\n\n"
        "JE MOET JE STRIKT HOUDEN AAN DE STRUCTUUR EN REGELS UIT DE SYSTEM PROMPT.\n\n"

        "VERBODEN:\n"
        "- Tabellen, matrixen, schema’s of kolomindelingen in welke vorm dan ook\n"
        "- Opsommingen met streepjes, bullets of genummerde lijsten\n"
        "- Markdown of pseudo-Markdown\n"
        "- Zelf bedachte of afgeleide cijfers\n"
        "- Aanbevelingen die niet expliciet uit de feiten volgen\n\n"

        "VERPLICHT:\n"
        "- Iedere sectie (1 t/m 7) moet bestaan uit lopende tekst in volledige alinea’s\n"
        "- Sectie 5 mag GEEN cijfers of tabellen bevatten en moet alleen duiden wat de tariefmatrix laat zien\n"
        "- De tariefmatrix zelf wordt uitsluitend door de backend ingevoegd\n"
        "- Iedere bijlage (A t/m D) moet inhoudelijk worden uitgewerkt in minimaal één alinea\n"
        "- Schrijf niets meer na Bijlage D\n\n"

        "BIJLAGEN (CONSUMENTGERICHT, MAAR COMPLEET):\n"
        "- Leg in gewone taal uit hoe de berekening werkt en hoe de uitkomsten tot stand komen.\n"
        "- Gebruik géén technische termen zonder uitleg.\n"
        "- Je mag cijfers alleen noemen als ze letterlijk in de JSON staan.\n"
        "- Leg uit wat de scenario’s betekenen (A1/B1/C1) en waarom ze worden vergeleken.\n"
        "- Leg uit welke invoer de gebruiker zelf heeft opgegeven (batterij, tarieven, vastrecht, terugleverkosten).\n"
        "- Leg uit hoe saldering is meegenomen in A1, en waarom B1/C1 zonder saldering zijn.\n"
        "- Leg uit hoe de batterij wordt ingezet op hoofdlijnen (laden bij overschot, ontladen bij verbruik), zonder code of technische details.\n"
        "- Leg uit welke kostencomponenten zijn meegenomen (energie-import/export, vastrecht, terugleverkosten, omvormerkosten, capaciteitstarief indien BE).\n"
        "- In Bijlage D: benoem beperkingen van de berekening (kwaliteit CSV, toekomstprijzen onzeker, gedrag kan wijzigen), zonder nieuwe aannames.\n\n"

        "FEITEN (JSON):\n"
        + json.dumps(ctx_dict, ensure_ascii=False, indent=2)
    )
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            max_tokens=2200,
            temperature=0.3,
        )

        content = response.choices[0].message.content

        return {
            "advice": content.strip()
        }

    except Exception as e:
        return {
            "error": str(e),
            "advice": ""
        }











