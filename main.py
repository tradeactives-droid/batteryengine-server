# ============================================================
# BatteryEngine Pro — Backend API
# COMPLETE MAIN.PY (parse_csv + compute_v3 + advice)
# ============================================================

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from datetime import datetime, timedelta
from typing import Optional

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


class AdviceRequest(BaseModel):
    context: AdviceContext
    draft_text: str


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

    batt = ctx.battery
    E = batt.get("E", 0)
    P = batt.get("P", 0)

    ctx.battery_assessment = {
    "E_assessment": (
        "beperkend ten opzichte van het energieprofiel"
        if E < 5
        else "passend bij het huidige energieprofiel"
        if E < 10
        else "relatief groot ten opzichte van het energieprofiel"
    ),
    "P_assessment": (
        "potentieel limiterend in flexibiliteit"
        if P < 3
        else "voldoende passend voor het gebruiksdoel"
        if P < 6
        else "ruim gedimensioneerd ten opzichte van de toepassing"
    ),
    "notes": []
}

    if client is None:
        return {
            "advice": req.draft_text
        }

    prompt = f"""
ROL
Je bent een onafhankelijk, professioneel energieadviesbureau gespecialiseerd in thuisbatterijen.
Je schrijft een commercieel en besluitondersteunend adviesrapport voor een particuliere klant.

POSITIONERING
- Je verkoopt GEEN batterij.
- Je geeft strategisch en adviserend inzicht.
- Je bent objectief, zorgvuldig en oplossingsgericht.
- Je benoemt zowel beperkingen als kansen.
- Je ondersteunt de klant bij het maken van een onderbouwde keuze.

ABSOLUUT VERPLICHTE REGELS (NIET SCHENDEN)
- Je mag NIET rekenen.
- Je mag GEEN aannames doen.
- Je mag GEEN nieuwe cijfers, bedragen of percentages introduceren.
- Je mag GEEN technische of financiële claims doen die niet expliciet volgen uit het CONTEXT-blok.
- Je gebruikt UITSLUITEND de feiten uit het CONTEXT-blok.

VERPLICHTE INSTRUCTIES OVER HET ENERGIEPROFIEL (CSV-GEBASEERD)
- Je MOET het energieprofiel expliciet benoemen en duiden.
- Het energieprofiel omvat onder andere:
- jaarlijks elektriciteitsverbruik,
- jaarlijkse zonne-opwek,
- mate van direct eigen verbruik (zelfconsumptie),
- en het tijdsverschil tussen piekverbruik en piekopwek.
- Je MOET toelichten wat deze patronen betekenen voor:
- teruglevering,
- netafname,
- en de functionele rol van een thuisbatterij.
- Je mag GEEN nieuwe berekeningen uitvoeren.
- Je mag GEEN percentages of cijfers herinterpreteren.
- Je mag ALLEEN beschrijven en duiden wat expliciet in het energieprofiel aanwezig is.

CRUCIALE INSTRUCTIES OVER TARIEFSTRUCTUREN
- Als vaste of traditionele tarieven financieel beperkt gunstig zijn, moet dit expliciet benoemd worden.
- Dynamische energiecontracten moeten ALTIJD expliciet genoemd worden als potentieel gunstiger scenario,
  mits dit logisch volgt uit:
  - de batterijcapaciteit (E),
  - het laad/ontlaadvermogen (P),
  - en de technische geschiktheid van de batterij.
- Dynamische tarieven mogen NIET als garantie worden gepresenteerd, maar WEL als strategische kans.

VERPLICHTE INSTRUCTIES OVER BATTERIJSIZING (E & P — NIET NEGEREN)

- Je MOET afzonderlijk en expliciet oordelen over:
  - de opslagcapaciteit (E),
  - en het laad/ontlaadvermogen (P).

- Voor OPSLAGCAPACITEIT (E) moet je altijd één van de volgende kwalificaties gebruiken:
  - “passend bij het huidige energieprofiel”,
  - “relatief groot ten opzichte van het energieprofiel”,
  - of “beperkend ten opzichte van het energieprofiel”.

- Voor LAAD/ONTLAADVERMOGEN (P) moet je altijd één van de volgende kwalificaties gebruiken:
  - “voldoende passend voor het gebruiksdoel”,
  - “potentieel limiterend in flexibiliteit”,
  - of “ruim gedimensioneerd ten opzichte van de toepassing”.

- Je oordeel moet uitsluitend gebaseerd zijn op:
  - het energieprofiel,
  - het gekozen tarieftype,
  - en de backend-classificatie van de batterijconfiguratie.

- Indien de huidige configuratie logisch en goed aansluit bij de situatie,
  moet dit expliciet en ondubbelzinnig benoemd worden.

- Indien optimalisatie mogelijk is, mag dit uitsluitend adviserend worden genoemd
  en uitsluitend als overweging, zonder cijfers, aannames of herberekeningen.

TOON & STIJL
- Professioneel
- Commercieel adviserend (adviesbureau / consultancy)
- Rustig, helder en vertrouwenwekkend
- Geen marketingtaal
- Geen verkoopdruk

STRUCTUUR VAN HET ADVIESRAPPORT (ABSOLUUT VERPLICHT)

Je MOET het adviesrapport exact volgens onderstaande structuur opstellen.
Afwijken van volgorde, titels of het samenvoegen van secties is NIET toegestaan.

Gebruik exact deze genummerde koppen:

1. Managementsamenvatting  
- Korte, zakelijke samenvatting van het totale advies.
- Maximaal 2 alinea’s.
- Geen details, geen herhaling, geen nieuwe informatie.
- Benoem expliciet:
  - of het huidige tarief financieel gunstig of beperkt gunstig is,
  - en of dynamische tarieven als strategisch alternatief relevant zijn.
- Positioneer het rapport expliciet als besluitondersteunend.

2. Financiële duiding  
- Verduidelijk waarom de businesscase wel of niet sluit.
- Maak een helder onderscheid tussen:
  - vaste / traditionele tarieven
  - en dynamische tarieven.
- Geen bedragen of nieuwe cijfers toevoegen.
- Gebruik uitsluitend contextuele uitleg.

3. Technische beoordeling & batterijconfiguratie  
- Beschrijf de batterijconfiguratie (E, P, DoD, efficiëntie).
- Geef expliciet oordeel over:
  - opslagcapaciteit (E),
  - laad/ontlaadvermogen (P),
  volgens de verplichte kwalificaties.
- Koppel de technische eigenschappen aan:
  - het energieprofiel,
  - het tarieftype,
  - en de mate van actieve sturing.
- Benoem expliciet of de huidige configuratie logisch en passend is.

4. Tariefstrategie & marktcontext  
- Beschrijf de rol van tariefstructuren in het rendement van thuisbatterijen.
- Benoem expliciet:
  - waarom vaste tarieven vaak beperkt voordeel bieden,
  - en waarom dynamische tarieven strategische kansen kunnen bieden.
- Geen garanties, geen voorspellingen.

5. Conclusie & aanbevolen vervolgstappen  
- Vat het advies samen in relationele vorm:
  - tariefkeuze,
  - batterijconfiguratie,
  - energieprofiel.
- Benoem expliciet:
  - of de huidige configuratie geschikt is,
  - en welke vervolgstappen logisch zijn.
- Formuleer vervolgstappen altijd als overweging, nooit als verplichting.

6. Disclaimer  
- Benoem dat resultaten afhankelijk zijn van:
  - marktontwikkelingen,
  - regelgeving,
  - contractvoorwaarden.
- Geen nieuwe informatie toevoegen.

INHOUDELIJKE RICHTLIJNEN PER SECTIE

1. Managementsamenvatting
- Beschrijf kort de doorgerekende situatie.
- Benoem of het rendement onder het huidige tarief beperkt of gunstig is.
- Introduceer dynamische tarieven expliciet als strategisch alternatief indien relevant.
- Positioneer het rapport als besluitondersteunend.

2. Analyse huidig energieverbruik en opwek (energieprofiel)
- Leg uit waarom de businesscase wel of niet sluit.
- Maak duidelijk onderscheid tussen vaste en dynamische tarieven.
- Vermijd absolute uitspraken; gebruik context en nuance.

3. Technische beoordeling & batterijconfiguratie
- Beschrijf de batterij (E, P, DoD, efficiëntie).
- Beoordeel expliciet of de gekozen opslagcapaciteit (E) passend is bij het gebruiksdoel.
- Beoordeel expliciet of het laad/ontlaadvermogen (P) voldoende flexibiliteit biedt.
- Benoem indien relevant:
  - dat de huidige configuratie goed aansluit bij de situatie, OF
  - dat alternatieve configuraties overwogen kunnen worden voor optimalisatie.
- Koppel technische eigenschappen aan praktische toepasbaarheid en tariefsturing.

4. Tariefstrategie & marktcontext
- Beschrijf de rol van tariefstructuren in het rendement van thuisbatterijen.
- Benoem dat dynamische tarieven in veel gevallen beter aansluiten bij actieve batterijsturing.
- Blijf feitelijk en voorzichtig.

5. Conclusie & aanbevolen vervolgstappen
- Trek een genuanceerde conclusie per tariefcontext.
- Benoem expliciet of de huidige batterijconfiguratie logisch is binnen dit kader.
- Formuleer één of meerdere logische vervolgstappen:
  - herberekening met dynamisch tarief,
  - optimalisatie van batterijconfiguratie,
  - herbeoordeling bij gewijzigde marktcondities.
- Positioneer dit als onderdeel van een breder besluitvormingsproces.

6. Disclaimer
- Benoem dat resultaten afhankelijk zijn van marktontwikkelingen, regelgeving en contractvoorwaarden.

CONTEXT (FEITEN — LEIDEND):
Land: {ctx.country}
Huidig tarief: {ctx.current_tariff}

Energieprofiel (op basis van meetdata uit CSV-bestanden):
{ctx.energy_profile}

Extra energieverbruikers (opgegeven door gebruiker):
{ctx.extra_consumers}

Batterij (ingevoerd):
{ctx.battery}

Backend-beoordeling batterij:
{ctx.battery_assessment}

Tariefmatrix:
{ctx.tariff_matrix}

ROI per tarief:
{ctx.roi_per_tariff}

Goedkoopste tarief zonder batterij:
{ctx.best_tariff_now}

Goedkoopste tarief met batterij:
{ctx.best_tariff_with_battery}

CONCEPTTEKST (MAG WORDEN HERSCHREVEN, VERBETERD EN GESTRUCTUREERD):
{req.draft_text}
"""

    try:
        response = client.chat.completions.create(
            model="gpt-4.1",
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









