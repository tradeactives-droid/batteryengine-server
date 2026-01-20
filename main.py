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

from battery_engine_pro3.profile_generator import (
    generate_load_profile_kwh,
    generate_pv_profile_kwh,
    generate_dynamic_prices_eur_per_kwh,
)


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

class ComputeV3ProfileRequest(BaseModel):
    # NIEUWE INPUT (zonder CSV)
    annual_load_kwh: float
    annual_pv_kwh: float

    household_profile: str  # bijv: "alleenstaand_werkend" | "gezin_kinderen" | "thuiswerker"
    has_heatpump: bool = False
    has_ev: bool = False
    ev_charge_window: str = "evening_night"

    # Batterijstrategie
    battery_strategy: str = "self_consumption"
    # opties: "self_consumption" | "dynamic_arbitrage"

    # Dynamisch tarief — gemiddelde prijzen (consulent-invoer)
    p_dyn_imp: float
    p_export_dyn: float

    # Batterij (zelfde als nu)
    E: float
    P: float
    DoD: float

    # RTE en degradatie: optioneel (None = “niet bekend”)
    eta_rt: Optional[float] = None
    battery_degradation: Optional[float] = None

    battery_cost: float
    battery_lifetime_years: int

    country: str
    current_tariff: str

    # Tarieven (zelfde als nu)
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

@app.post("/compute_v3_profile")
def compute_v3_profile(req: ComputeV3ProfileRequest):
    # -----------------------------
    # 1) Maak synthetische profielen
    # -----------------------------
    dt_hours = 1.0
    ts_load, load_vals = generate_load_profile_kwh(
        annual_load_kwh=req.annual_load_kwh,
        household_profile=req.household_profile,
        has_heatpump=req.has_heatpump,
        has_ev=req.has_ev,
        ev_charge_window=req.ev_charge_window,
        dt_hours=dt_hours,
        year=2025,
    )
    _, pv_vals = generate_pv_profile_kwh(
        annual_pv_kwh=req.annual_pv_kwh,
        dt_hours=dt_hours,
        year=2025,
    )

    n = min(len(load_vals), len(pv_vals))
    load_vals = load_vals[:n]
    pv_vals = pv_vals[:n]

    # -----------------------------
    # 2) “Niet bekend” gedrag
    # -----------------------------
    eta_rt = req.eta_rt if (req.eta_rt is not None and req.eta_rt > 0) else 1.0
    degradation = req.battery_degradation if (req.battery_degradation is not None and req.battery_degradation >= 0) else 0.0

    # --------------------------------------------------
    # Dynamische prijzen — afgeleid uit gemiddelde importprijs
    # --------------------------------------------------
    DYN_AVG_PRICE = req.p_dyn_imp
    DYN_SPREAD = 0.12  # vaste, interne aanname (niet instelbaar)
    DYN_CHEAP_HOURS = 8  # vaste, interne aanname
    
    prices_dyn = generate_dynamic_prices_eur_per_kwh(
        avg_price=DYN_AVG_PRICE,
        spread=DYN_SPREAD,
        cheap_hours_per_day=DYN_CHEAP_HOURS,
        dt_hours=dt_hours,
        year=2025,
    )
    
    prices_dyn = prices_dyn[:n]

    
    engine_input = ComputeV3Input(
        load_kwh=load_vals,
        pv_kwh=pv_vals,
        prices_dyn=prices_dyn,  # <-- nu altijd aanwezig als model, geen CSV meer

        p_enkel_imp=req.p_enkel_imp,
        p_enkel_exp=req.p_enkel_exp,
        p_dag=req.p_dag,
        p_nacht=req.p_nacht,
        p_exp_dn=req.p_exp_dn,
        p_export_dyn=req.p_export_dyn,

        E=req.E,
        P=req.P,
        DoD=req.DoD,
        eta_rt=eta_rt,
        vastrecht=req.vastrecht_year,

        battery_cost=req.battery_cost,
        battery_degradation=degradation,
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

    result = BatteryEnginePro3.compute(engine_input)

    # -----------------------------
    # 6) Transparantie — dynamisch prijsmodel
    # -----------------------------
    result["calculation_method"] = {
        "mode": "profile_based",
        "dt_hours": dt_hours,
        "dynamic_price_model": {
            "source": "model_based",
            "avg_price_eur_per_kwh": req.dyn_avg_import_price,
            "price_spread_eur_per_kwh": req.dyn_spread,
            "cheap_hours_per_day": req.dyn_cheap_hours_per_day,
            "user_controls": [
                "cheap_hours_per_day"
            ],
            "fixed_by_tool": [
                "avg_price_eur_per_kwh",
                "price_spread_eur_per_kwh"
            ]
        },
        "household_profile": req.household_profile,
        "modifiers": {
            "has_heatpump": req.has_heatpump,
            "has_ev": req.has_ev
        }
    }

    # metadata teruggeven voor “transparantie”
    result["calculation_method"] = {
        "mode": "profile_based",
        "dt_hours": dt_hours,
        "household_profile": req.household_profile,
        "modifiers": {
            "has_heatpump": req.has_heatpump,
            "has_ev": req.has_ev,
        },
        "assumptions": {
            "eta_rt_included": req.eta_rt is not None,
            "battery_degradation_included": req.battery_degradation is not None,
            "dynamic_prices_source": "model",
        }
    }

    return result


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

import re

def enforce_max_4_sentences_per_paragraph(text: str) -> str:
    lines = text.split("\n")
    output = []
    buffer = []

    def flush_buffer():
        if not buffer:
            return
        paragraph = " ".join(buffer).strip()
        sentences = re.split(r'(?<=[.!?])\s+', paragraph)

        for i in range(0, len(sentences), 4):
            chunk = " ".join(sentences[i:i+4]).strip()
            if chunk:
                output.append(chunk)
                output.append("")  # <-- witregel NA max 4 zinnen

        buffer.clear()

    for line in lines:
        line = line.strip()

        # Nieuwe sectietitel → buffer eerst flushen
        if re.match(r'^\d+\.\s', line) or line.startswith("Bijlage"):
            flush_buffer()
            output.append(line)
            output.append("")  # witregel NA titel
            continue

        if line == "":
            flush_buffer()
            continue

        buffer.append(line)

    flush_buffer()

    return "\n".join(output).strip()

SYSTEM_PROMPT = """
JE MOET JE EXACT AAN ONDERSTAANDE STRUCTUUR HOUDEN.
AFWIJKING IS NIET TOEGESTAAN.

FORMATREGELS (ABSOLUUT):
- Gebruik GEEN Markdown
- Gebruik GEEN tabellen, kolommen, kopjes of matrix-structuren
- Schrijf GEEN woorden zoals "Tariefmatrix", "Scenario", "Enkel", "Dag/Nacht", "Dynamisch" als losse regels of koppen
- In sectie 5 mag ALLEEN beschrijvende lopende tekst staan
- Schrijf niets vóór sectie 1
STOPREGEL:
- Na "Bijlage D — Beperkingen & scope" mag er niets meer volgen.

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

import re

TITLE_RE = re.compile(r"^\d+\.\s+.+$")
APPENDIX_RE = re.compile(r"^Bijlage\s+[A-D]\s+—\s+.+$")

def _is_title(line: str) -> bool:
    line = line.strip()
    return bool(TITLE_RE.match(line) or APPENDIX_RE.match(line))

def _split_sentences(text: str) -> list[str]:
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return []
    parts = re.split(r"(?<=[.!?])\s+", text)
    return [p.strip() for p in parts if p.strip()]

def _chunk_sentences(sentences: list[str], max_n: int = 4) -> list[str]:
    # hard: 4 zinnen max per alinea (dus 3-4 meestal, laatste mag korter)
    chunks = []
    i = 0
    while i < len(sentences):
        chunk = " ".join(sentences[i:i+max_n]).strip()
        if chunk:
            chunks.append(chunk)
        i += max_n
    return chunks

def format_advice_text(raw: str) -> str:
    """
    GARANTIE:
    - Na elke titel: EXACT 1 lege regel
    - Tussen laatste alinea van sectie en volgende titel: EXACT 2 lege regels
    - Binnen secties: alinea's van max 4 zinnen, gescheiden door 1 lege regel
    """
    if not raw:
        return ""

    raw = raw.replace("\r\n", "\n").replace("\r", "\n")

    # split in regels, trim, haal lege regels weg (we bouwen ze zelf opnieuw op)
    lines = [ln.strip() for ln in raw.split("\n")]
    lines = [ln for ln in lines if ln != ""]

    out = []
    buffer_lines = []

    def flush_text():
        nonlocal buffer_lines
        if not buffer_lines:
            return

        text = " ".join(buffer_lines).strip()
        buffer_lines = []
        if not text:
            return

        sentences = _split_sentences(text)
        paragraphs = _chunk_sentences(sentences, max_n=4)

        for p in paragraphs:
            out.append(p)
            out.append("")  # 1 witregel tussen alinea's

    for ln in lines:
        if _is_title(ln):
            # sluit eerst tekst af
            flush_text()

            # ✅ exact 2 witregels vóór de volgende titel
            if out:
                while out and out[-1] == "":
                    out.pop()
                out.append("")
                out.append("")

            # titel zelf
            out.append(ln)

            # ✅ exact 1 witregel na de titel
            out.append("")
        else:
            buffer_lines.append(ln)

    flush_text()

    # cleanup eind
    while out and out[-1] == "":
        out.pop()

    return "\n".join(out).strip()

@app.post("/generate_advice")
def generate_advice(req: AdviceRequest):
    ctx = req.context
    ctx_dict = ctx.model_dump()

    # ============================
    # BIJLAGE A — DATABRONNEN & UITGANGSPUNTEN
    # ============================

    calc_mode = (ctx_dict.get("calculation_method") or {}).get("mode", "csv_based")

    if calc_mode == "profile_based":
        ctx_dict["appendix_A"] = {
            "verbruiksdata": (
                "Het elektriciteitsverbruik is gebaseerd op het door de gebruiker opgegeven "
                "jaarlijkse verbruik in combinatie met een standaard dagprofiel. Dit profiel "
                "vertaalt het jaarverbruik naar een realistische verdeling over de dag."
            ),
            "opwekdata": (
                "De zonne-energieproductie is gebaseerd op de opgegeven jaarlijkse opwek. "
                "Hiervoor wordt een gestandaardiseerd opwekprofiel gebruikt dat rekening "
                "houdt met seizoensinvloeden en dag-nacht variatie."
            ),
            "profielkeuze": (
                "Het gekozen huishouden- of woningprofiel bepaalt wanneer elektriciteit "
                "wordt verbruikt. Hiermee wordt het tijdsprofiel van de afname benaderd "
                "zonder gebruik te maken van individuele meetdata."
            ),
            "tariefdata": (
                "De energietarieven zijn gebaseerd op door de gebruiker ingevoerde "
                "contractwaarden, zoals vaste tarieven of gemodelleerde dynamische prijzen."
            ),
            "algemene_uitgangspunten": (
                "De berekening is gebaseerd op een modelmatige benadering. De resultaten "
                "geven een indicatie op basis van aannames en standaardprofielen."
            ),
        }
    else:
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
                "Alle berekeningen zijn uitgevoerd op basis van historische meetdata."
            ),
        }

    # ============================
    # BIJLAGE B — REKENMETHODIEK & SCENARIO-OPZET
    # ============================

    if calc_mode == "profile_based":
        ctx_dict["appendix_B"] = {
            "scenario_definitie": (
                "De analyse bestaat uit meerdere scenario’s die onderling worden vergeleken. "
                "Alle scenario’s gebruiken dezelfde gesimuleerde verbruiks- en opwekprofielen."
            ),
            "rekenmethode": (
                "Het jaarverbruik en de jaaropwek worden vertaald naar een uurlijkse verdeling "
                "met behulp van standaardprofielen. Deze profielen benaderen het gemiddelde "
                "gedrag van vergelijkbare huishoudens."
            ),
            "scenario_A1": (
                "Scenario A1 beschrijft de huidige situatie met het bestaande contract en "
                "zonder inzet van een thuisbatterij."
            ),
            "scenario_B1": (
                "Scenario B1 beschrijft een situatie zonder batterij waarbij geen saldering "
                "meer wordt toegepast."
            ),
            "scenario_C1": (
                "Scenario C1 beschrijft een situatie met thuisbatterij zonder saldering, "
                "waarbij de batterij wordt ingezet om het eigen verbruik te verhogen."
            ),
            "prijsmodellering": (
                "Bij dynamische contracten worden geen historische uurprijzen gebruikt. "
                "In plaats daarvan wordt gewerkt met een gemodelleerd prijsprofiel op basis "
                "van gemiddelde prijzen en dagelijkse spreiding."
            ),
        }
    else:
        ctx_dict["appendix_B"] = {
            "scenario_definitie": (
                "Er zijn meerdere scenario’s doorgerekend om de impact van tariefstructuren "
                "en batterij-inzet inzichtelijk te maken."
            ),
            "scenario_A1": (
                "Scenario A1 beschrijft de huidige situatie zonder wijzigingen."
            ),
            "scenario_B1": (
                "Scenario B1 simuleert een toekomstige situatie zonder batterij."
            ),
            "scenario_C1": (
                "Scenario C1 beschrijft een situatie met thuisbatterij."
            ),
            "batterij_dispatch": (
                "De batterij wordt regel-gebaseerd aangestuurd op basis van meetdata."
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
        "- Na elke 3 tot maximaal 4 volledige zinnen MOET je een lege regel invoegen (witregel) zodat korte, leesbare alinea’s ontstaan\n"
        "- Na iedere sectietitel moet EXACT één lege regel volgen\n"
        "- Tussen de laatste alinea van een sectie en de volgende sectietitel MOETEN EXACT twee lege regels staan\n"
        "- Lange alinea’s moeten worden opgesplitst in leesblokken van circa 3 tot 4 zinnen, gescheiden door een lege regel\n"
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
        content = enforce_max_4_sentences_per_paragraph(content)

        content = format_advice_text(content)

        return {
            "advice": content.strip()
        }

    except Exception as e:
        return {
            "error": str(e),
            "advice": ""
        }







































