# ============================================================
# BatteryEngine Pro — Backend API
# COMPLETE MAIN.PY (parse_csv + compute_v3 + advice)
# ============================================================

import asyncio
from typing import Annotated, List, Optional

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exception_handlers import http_exception_handler
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import json
import logging
import os
from datetime import datetime, timezone
from uuid import UUID

try:
    import stripe
except ImportError:  # pragma: no cover
    stripe = None  # type: ignore[misc, assignment]

try:
    import resend
except ImportError:  # pragma: no cover
    resend = None  # type: ignore[misc, assignment]

import httpx
from openai import OpenAI

from battery_engine_pro3.auth.session_guard import (
    AuthenticatedUser,
    get_current_user,
    register_active_session,
)
from battery_engine_pro3.device_tracking_deps import track_user_device
from battery_engine_pro3.engine import BatteryEnginePro3, ComputeV3Input

from battery_engine_pro3.dynamic_prices import build_dynamic_prices_hybrid
from battery_engine_pro3.profile_generator import (
    generate_load_profile_kwh,
    generate_pv_profile_kwh,
)

logger = logging.getLogger(__name__)


# ============================================================
# FASTAPI INIT
# ============================================================

app = FastAPI()


@app.exception_handler(HTTPException)
async def _http_exception_flat_error_code(request: Request, exc: HTTPException):
    """Return flat JSON { error_code, message, ... } for API errors (matches frontend expectations)."""
    if isinstance(exc.detail, dict) and exc.detail.get("error_code") is not None:
        return JSONResponse(status_code=exc.status_code, content=exc.detail)
    return await http_exception_handler(request, exc)


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

if stripe is not None:
    stripe.api_key = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET = os.getenv(
    "STRIPE_WEBHOOK_SECRET",
    "",
)
STRIPE_PRICE_ID = os.getenv(
    "STRIPE_PRICE_ID",
    "price_1SjT5x2Y2l8Uvp2bS1UTY7nC",
)

RESEND_API_KEY = os.getenv("RESEND_API_KEY", "")
if resend is not None:
    resend.api_key = RESEND_API_KEY


REQUIRED_COMPUTE_RESULT_KEYS = ("A1", "B1", "C1", "roi", "peaks")


def _raise_http_error(status_code: int, error_code: str, message: str, details: Optional[dict] = None):
    payload = {
        "error_code": error_code,
        "message": message,
    }
    if details:
        payload["details"] = details
    raise HTTPException(status_code=status_code, detail=payload)


def _validate_compute_result_format(result: object):
    if not isinstance(result, dict):
        _raise_http_error(
            status_code=500,
            error_code="INVALID_RESPONSE_FORMAT",
            message="De berekening gaf een ongeldig antwoordformaat terug.",
            details={"expected_type": "dict", "actual_type": type(result).__name__},
        )
    missing = [k for k in REQUIRED_COMPUTE_RESULT_KEYS if k not in result]
    if missing:
        _raise_http_error(
            status_code=500,
            error_code="INVALID_RESPONSE_FORMAT",
            message="De berekening mist verplichte velden in de response.",
            details={"missing_keys": missing},
        )


def _attach_device_tracking(request: Request, payload: dict) -> dict:
    """Merge multi-device flags when device telemetry ran this request (session + x-device-id)."""
    if not getattr(request.state, "device_tracking_applied", False):
        return payload
    out = dict(payload)
    out["device_warning"] = bool(getattr(request.state, "device_warning", False))
    out["device_count"] = getattr(request.state, "device_count", None)
    return out


# ============================================================
# CSV PARSER
# ============================================================

class ParseCSVRequest(BaseModel):
    load_file: str
    pv_file: str
    prices_file: str


class RegisterSessionRequest(BaseModel):
    session_token: str


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
def parse_csv(
    req: ParseCSVRequest,
    request: Request,
    _device_track: Annotated[None, Depends(track_user_device)],
):
    load = _process_csv_text(req.load_file)
    pv = _process_csv_text(req.pv_file)

    if len(load) < 20000 or len(pv) < 20000:
        return _attach_device_tracking(request, {"error": "NOT_ENOUGH_DATA"})

    prices = _process_csv_text(req.prices_file)
    n = min(len(load), len(pv))

    return _attach_device_tracking(
        request,
        {
            "load_kwh": load[:n],
            "pv_kwh": pv[:n],
            "prices_dyn": prices[:n] if len(prices) == n else [],
        },
    )


@app.get("/validate-session")
def validate_session(
    request: Request,
    _device_track: Annotated[None, Depends(track_user_device)],
):
    """
    Lightweight endpoint for proactive frontend session checks.
    If session is invalid, dependency raises 401 SESSION_INVALID.
    """
    return _attach_device_tracking(request, {"ok": True})


@app.post("/register-session")
def register_session(
    req: RegisterSessionRequest,
    current_user: Annotated[Optional[AuthenticatedUser], Depends(get_current_user)],
):
    token = (req.session_token or "").strip()
    if not token:
        _raise_http_error(
            status_code=400,
            error_code="CALCULATION_VALIDATION_ERROR",
            message="session_token is verplicht.",
        )
    try:
        UUID(token)
    except ValueError:
        _raise_http_error(
            status_code=400,
            error_code="CALCULATION_VALIDATION_ERROR",
            message="session_token moet een geldige UUID zijn.",
        )

    if current_user is None:
        _raise_http_error(
            status_code=401,
            error_code="SESSION_INVALID",
            message="Session invalid or superseded by another device.",
        )

    if not register_active_session(current_user.id, token):
        _raise_http_error(
            status_code=500,
            error_code="CALCULATION_SERVER_ERROR",
            message="Kon actieve sessie niet registreren.",
        )
    return {"ok": True}


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

    allow_grid_charge: bool = False

class ComputeV3ProfileRequest(BaseModel):
    # NIEUWE INPUT (zonder CSV)
    annual_load_kwh: float
    annual_pv_kwh: float
    daytime_fraction: Optional[float] = None
    # Aandeel jaarverbruik overdag (07:00–23:00), bijv. 0.65
    # Komt van dag/nacht-split op de jaarafrekening of netbeheerder-portaal
    # None = niet opgegeven, profiel bepaalt de verdeling
    monthly_load_kwh: Optional[List[float]] = None
    # 12 maandwaarden (jan t/m dec) in kWh
    # Beschikbaar via netbeheerder-portaal
    # None = synthetisch seizoensprofiel wordt gebruikt
    home_during_day: Optional[str] = None
    # "never"   = niemand overdag thuis
    # "partial" = wisselend / deels thuiswerk
    # "always"  = altijd iemand thuis overdag
    # None      = niet opgegeven, profiel bepaalt verdeling

    household_profile: str  # bijv: "alleenstaand_werkend" | "gezin_kinderen" | "gepensioneerd"
    has_heatpump: bool = False
    heatpump_type: Optional[str] = None
    # "air_water" = lucht/water zonder buffervat;
    # "air_water_buffer" = lucht/water met buffervat;
    # None = onbekend, air_water wordt aangenomen
    heatpump_schedule: Optional[str] = None
    # "night" = voornamelijk 's nachts;
    # "day" = voornamelijk overdag;
    # "day_night" = ochtend + avond (default);
    # None = onbekend, day_night wordt aangenomen
    has_ev: bool = False
    ev_charge_window: str = "evening_night"

    allow_grid_charge: bool = False

    # Batterijstrategie
    battery_strategy: str = "self_consumption"
    # opties: "self_consumption" | "dynamic_arbitrage"

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
    p_dyn_imp: float

    vastrecht_year: float

    feedin_monthly_cost: float = 0.0
    feedin_cost_per_kwh: float = 0.0
    feedin_free_kwh: float = 0.0
    feedin_price_after_free: float = 0.0

    inverter_power_kw: float = 0.0
    inverter_cost_per_kw: float = 0.0
    inverter_cost_per_kw_month: Optional[float] = None

    capacity_tariff_kw: float = 0.0

    annual_feedin_kwh: Optional[float] = None
    # Werkelijke jaarlijkse teruglevering in kWh
    # Staat op de jaarafrekening van de energieleverancier
    # Wordt gebruikt als validatie/calibratie van het profiel
    # None = niet opgegeven, geen calibratie


@app.post("/compute_v3")
def compute_v3(
    req: ComputeV3Request,
    request: Request,
    _device_track: Annotated[None, Depends(track_user_device)],
):
    if not req.load_kwh or not req.pv_kwh:
        _raise_http_error(
            status_code=400,
            error_code="CALCULATION_VALIDATION_ERROR",
            message="Verbruiks- en PV-profiel zijn verplicht en mogen niet leeg zijn.",
            details={"field_errors": ["load_kwh", "pv_kwh"]},
        )

    n = min(len(req.load_kwh), len(req.pv_kwh))

    engine_input = ComputeV3Input(
        load_kwh=req.load_kwh[:n],
        pv_kwh=req.pv_kwh[:n],
        prices_dyn=req.prices_dyn,
        allow_grid_charge=req.allow_grid_charge,

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

    try:
        result = BatteryEnginePro3.compute(engine_input)
        _validate_compute_result_format(result)
        return _attach_device_tracking(request, result)
    except HTTPException:
        raise
    except ValueError as e:
        _raise_http_error(
            status_code=422,
            error_code="CALCULATION_VALIDATION_ERROR",
            message="Ongeldige invoer voor berekening.",
            details={"reason": str(e)},
        )
    except Exception as e:
        _raise_http_error(
            status_code=500,
            error_code="CALCULATION_SERVER_ERROR",
            message="Er is een interne fout opgetreden tijdens de berekening.",
            details={"reason": str(e)},
        )

@app.post("/compute_v3_profile")
def compute_v3_profile(
    req: ComputeV3ProfileRequest,
    request: Request,
    _device_track: Annotated[None, Depends(track_user_device)],
):
    try:
        home_during_day = req.home_during_day
        if home_during_day is not None:
            normalized = str(home_during_day).strip().lower()
            if normalized not in {"never", "partial", "always"}:
                logger.warning(
                    "Ongeldige home_during_day '%s'; fallback naar None.",
                    home_during_day,
                )
                home_during_day = None
            else:
                home_during_day = normalized

        heatpump_type = req.heatpump_type
        if heatpump_type is not None:
            hp_t = str(heatpump_type).strip().lower()
            if hp_t not in {"air_water", "air_water_buffer"}:
                logger.warning(
                    "Ongeldige heatpump_type '%s'; fallback naar None (generator: air_water).",
                    heatpump_type,
                )
                heatpump_type = None
            else:
                heatpump_type = hp_t

        heatpump_schedule = req.heatpump_schedule
        if heatpump_schedule is not None:
            hp_s = str(heatpump_schedule).strip().lower()
            if hp_s not in {"night", "day", "day_night"}:
                logger.warning(
                    "Ongeldige heatpump_schedule '%s'; fallback naar None (generator: day_night).",
                    heatpump_schedule,
                )
                heatpump_schedule = None
            else:
                heatpump_schedule = hp_s

        # -----------------------------
        # 1) Maak synthetische profielen (eerst PV, daarna load + calibratie)
        # -----------------------------
        dt_hours = 1.0
        _, pv_vals = generate_pv_profile_kwh(
            annual_pv_kwh=req.annual_pv_kwh,
            dt_hours=dt_hours,
            year=2025,
        )
        ts_load, load_vals = generate_load_profile_kwh(
            annual_load_kwh=req.annual_load_kwh,
            household_profile=req.household_profile,
            has_heatpump=req.has_heatpump,
            has_ev=req.has_ev,
            daytime_fraction=req.daytime_fraction,
            home_during_day=home_during_day,
            monthly_kwh=req.monthly_load_kwh,
            ev_charge_window=req.ev_charge_window,
            dt_hours=dt_hours,
            year=2025,
            heatpump_type=heatpump_type,
            heatpump_schedule=heatpump_schedule,
            annual_feedin_kwh=req.annual_feedin_kwh,
            pv_values_for_calibration=pv_vals,
        )

        n = min(len(load_vals), len(pv_vals))
        load_vals = load_vals[:n]
        pv_vals = pv_vals[:n]

        simulated_feedin = 0.0
        deviation_pct = 0.0
        profile_warning_set = False
        profile_warning_payload = None

        if req.annual_feedin_kwh is not None and req.annual_feedin_kwh > 0:
            simulated_feedin = sum(
                max(0.0, pv_vals[i] - load_vals[i])
                for i in range(n)
            )
            deviation = abs(simulated_feedin - req.annual_feedin_kwh)
            deviation_pct = (deviation / req.annual_feedin_kwh) * 100.0
            profile_warning_set = True
            if deviation_pct > 25.0:
                profile_warning_payload = {
                    "type": "feedin_mismatch",
                    "simulated_feedin_kwh": round(simulated_feedin, 0),
                    "provided_feedin_kwh": req.annual_feedin_kwh,
                    "deviation_pct": round(deviation_pct, 1),
                    "message": (
                        f"De berekende teruglevering ({simulated_feedin:.0f} kWh) "
                        f"wijkt {deviation_pct:.0f}% af van de opgegeven "
                        f"teruglevering ({req.annual_feedin_kwh:.0f} kWh). "
                        f"Controleer het verbruiksprofiel en de jaaropwek."
                    ),
                }
                logger.warning(
                    "feedin_mismatch: simulated_feedin_kwh=%s provided=%s deviation_pct=%s",
                    round(simulated_feedin, 0),
                    req.annual_feedin_kwh,
                    round(deviation_pct, 1),
                )
            else:
                profile_warning_payload = None

        # -----------------------------
        # 2) Niet-bekend gedrag
        # -----------------------------
        eta_rt = req.eta_rt if (req.eta_rt is not None and req.eta_rt > 0) else 1.0
        # Standaard 2% degradatie/jaar (realistisch voor Li-ion) als niet opgegeven
        DEFAULT_DEGRADATION_PER_YEAR = 0.02
        degradation = (
            req.battery_degradation
            if (req.battery_degradation is not None and req.battery_degradation >= 0)
            else DEFAULT_DEGRADATION_PER_YEAR
        )

        # -----------------------------
        # 3) Dynamische prijzen (NL 2024 day-ahead geschaald naar p_dyn_imp)
        # -----------------------------
        prices_dyn, dynamic_price_source = build_dynamic_prices_hybrid(
            n_steps=n,
            dt_hours=dt_hours,
            avg_import_price=req.p_dyn_imp,
            historic_prices=None,
        )

        # -----------------------------
        # 4) Engine input
        # -----------------------------
        engine_input = ComputeV3Input(
            load_kwh=load_vals,
            pv_kwh=pv_vals,
            prices_dyn=prices_dyn,
            allow_grid_charge=req.allow_grid_charge,

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
            annual_load_kwh=req.annual_load_kwh,
            annual_pv_kwh=req.annual_pv_kwh,
            annual_feedin_kwh=req.annual_feedin_kwh,
            daytime_fraction=req.daytime_fraction,
            p_dyn_imp=req.p_dyn_imp,
        )

        result = BatteryEnginePro3.compute(engine_input)
        _validate_compute_result_format(result)
        if profile_warning_set:
            result["profile_warning"] = profile_warning_payload

        calc_method = dict((result.get("calculation_method") or {}))
        calc_method["mode"] = "profile_based"
        calc_method["daytime_fraction_used"] = req.daytime_fraction
        calc_method["home_during_day_used"] = home_during_day
        calc_method["monthly_load_provided"] = req.monthly_load_kwh is not None
        calc_method["heatpump_type_used"] = heatpump_type
        calc_method["heatpump_schedule_used"] = heatpump_schedule
        calc_method["dynamic_price_source"] = dynamic_price_source
        calc_method["feedin_calibration_applied"] = (
            req.annual_feedin_kwh is not None and req.annual_feedin_kwh > 0
        )
        calc_method["feedin_validation"] = {
            "provided_kwh": req.annual_feedin_kwh,
            "simulated_kwh": round(simulated_feedin, 0)
            if req.annual_feedin_kwh
            else None,
            "deviation_pct": round(deviation_pct, 1)
            if req.annual_feedin_kwh
            else None,
        }
        result["calculation_method"] = calc_method

        # Saldering impact context voor adviesrapport
        current_tariff = req.current_tariff or "enkel"

        try:
            # Haal B1 en A1 kosten op — probeer meerdere
            # structuren want het formaat kan variëren
            def _get_cost(d, tariff):
                if not isinstance(d, dict):
                    return None
                entry = d.get(tariff) or d.get("enkel")
                if entry is None:
                    return None
                if isinstance(entry, dict):
                    v = entry.get("total_cost_eur")
                else:
                    v = getattr(entry, "total_cost_eur", None)
                try:
                    return float(v) if v is not None else None
                except (TypeError, ValueError):
                    return None

            b1_cost_num = _get_cost(result.get("B1"), current_tariff)
            a1_cost_num = _get_cost(result.get("A1_per_tariff"), current_tariff)

            # Fallback: gebruik de direct berekende waarden
            # als de result-structuur leeg is
            if b1_cost_num is None or b1_cost_num == 0.0:
                if req.annual_load_kwh and req.annual_feedin_kwh is not None:
                    pv = float(req.annual_pv_kwh or 0)
                    feedin = float(req.annual_feedin_kwh)
                    load = float(req.annual_load_kwh)
                    directe_zc = max(0.0, pv - feedin)
                    netto_import = max(0.0, load - directe_zc)
                    p_imp = float(req.p_enkel_imp or 0.29)
                    p_exp = float(req.p_enkel_exp or 0.07)
                    fixed = float(req.vastrecht_year or 0)
                    b1_cost_num = round(
                        netto_import * p_imp - feedin * p_exp + fixed,
                        2,
                    )

            if a1_cost_num is None or a1_cost_num == 0.0:
                if req.annual_load_kwh and req.annual_feedin_kwh is not None:
                    pv = float(req.annual_pv_kwh or 0)
                    feedin = float(req.annual_feedin_kwh)
                    load = float(req.annual_load_kwh)
                    directe_zc = max(0.0, pv - feedin)
                    netto_import = max(0.0, load - directe_zc)
                    p_imp = float(req.p_enkel_imp or 0.29)
                    p_exp = float(req.p_enkel_exp or 0.07)
                    fixed = float(req.vastrecht_year or 0)
                    gesaldeerde_kwh = min(netto_import, feedin)
                    overschot = max(0.0, feedin - netto_import)
                    e_a1 = (
                        netto_import * p_imp
                        - gesaldeerde_kwh * p_imp
                        - overschot * p_exp
                    )
                    a1_cost_num = round(e_a1 + fixed, 2)

            if (
                b1_cost_num is not None
                and a1_cost_num is not None
            ):
                saldering_impact_eur = round(
                    b1_cost_num - a1_cost_num, 2
                )

                if saldering_impact_eur > 50:
                    saldering_narrative = "pain"
                elif saldering_impact_eur < -50:
                    saldering_narrative = "neutral_or_positive"
                else:
                    saldering_narrative = "minimal"

                saldering_ctx_payload = {
                    "saldering_impact_eur": saldering_impact_eur,
                    "narrative": saldering_narrative,
                    "b1_cost_eur": b1_cost_num,
                    "a1_cost_eur": a1_cost_num,
                    "current_tariff": current_tariff,
                }
                if req.annual_load_kwh and req.annual_feedin_kwh is not None:
                    pv = float(req.annual_pv_kwh or 0)
                    feedin = float(req.annual_feedin_kwh)
                    load = float(req.annual_load_kwh)
                    directe_zc = max(0.0, pv - feedin)
                    netto_import = max(0.0, load - directe_zc)
                    p_imp = float(req.p_enkel_imp or 0.29)
                    p_exp = float(req.p_enkel_exp or 0.07)
                    saldering_ctx_payload.update(
                        {
                            "netto_import_kwh": round(netto_import, 1),
                            "feedin_kwh": round(feedin, 1),
                            "directe_zelfconsumptie_kwh": round(directe_zc, 1),
                            "gesaldeerde_kwh": round(min(netto_import, feedin), 1),
                            "import_tarief_enkel": round(p_imp, 4),
                            "export_tarief_enkel": round(p_exp, 4),
                            "tariefverschil_enkel": round(p_imp - p_exp, 4),
                            "a1_cost_eur": round(a1_cost_num, 2),
                            "b1_cost_eur": round(b1_cost_num, 2),
                        }
                    )
                result["saldering_context"] = saldering_ctx_payload
            else:
                result["saldering_context"] = None

        except Exception as e:
            logger.warning(
                "saldering_context berekening mislukt: %s", e
            )
            result["saldering_context"] = None

        result["profile_inputs"] = {
            "annual_load_kwh": req.annual_load_kwh,
            "annual_pv_kwh": req.annual_pv_kwh,
            "annual_feedin_kwh": req.annual_feedin_kwh,
        }

        return _attach_device_tracking(request, result)

    except HTTPException:
        raise
    except ValueError as e:
        _raise_http_error(
            status_code=422,
            error_code="CALCULATION_VALIDATION_ERROR",
            message="Ongeldige invoer voor profielberekening.",
            details={"reason": str(e)},
        )
    except Exception as e:
        _raise_http_error(
            status_code=500,
            error_code="CALCULATION_SERVER_ERROR",
            message="Er is een interne fout opgetreden tijdens de profielberekening.",
            details={"reason": str(e)},
        )


# ============================================================
# ADVICE GENERATOR
# ============================================================


class ProfileInputsContext(BaseModel):
    """Door de klant opgegeven jaargetallen (profielmodus); niet verwarren met energy_profile."""

    annual_load_kwh: Optional[float] = None
    annual_pv_kwh: Optional[float] = None
    annual_feedin_kwh: Optional[float] = None


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
    profile_inputs: Optional[ProfileInputsContext] = None

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
Je bent een energie-rapportgenerator. Je taak is om
het onderstaande sjabloon in te vullen met de exacte
waarden uit de JSON-feiten. Je mag de structuur en
volgorde NIET wijzigen. Je mag ALLEEN de waarden
tussen [HAAKJES] vervangen door de juiste getallen
uit kernfeiten of de JSON.

SJABLOON:

1. Managementsamenvatting
Dit rapport analyseert de haalbaarheid van een 
thuisbatterij voor uw huishouden. De huidige 
energiesituatie, de impact van het wegvallen van 
saldering en de financiële implicaties worden 
besproken. De conclusie biedt een concrete 
aanbeveling op basis van de berekende terugverdientijd 
en het verwachte rendement.

2. Uw huidige energiesituatie
Uw jaarlijkse elektriciteitsverbruik bedraagt 
[kernfeiten.jaarverbruik_kwh] kWh, terwijl u jaarlijks 
[kernfeiten.jaaropwek_kwh] kWh aan zonne-energie opwekt. 
U levert jaarlijks [kernfeiten.teruglevering_kwh] kWh 
terug aan het net. U heeft momenteel een 
[current_tariff] tariefcontract. Het verschil tussen 
wat u exporteert (exportprijs) en importeert 
(importprijs) bepaalt de waarde van een batterij 
voor uw situatie.

3. Impact van het wegvallen van saldering
[kernfeiten.saldering_verhaal]
[Voeg hier één zin toe over wat dit betekent voor 
de klant, gebaseerd op saldering_context.narrative:
- "pain": De batterij kan het grootste deel van 
  deze extra kosten compenseren.
- "neutral_or_positive": Voor uw situatie is 
  zelfconsumptie vergroten de primaire reden voor 
  een batterij.
- "minimal": De salderingsafbouw heeft beperkte 
  directe impact voor uw situatie.]

4. Wat een batterij voor u doet
Een thuisbatterij slaat uw PV-overschot op overdag 
en levert dit 's avonds wanneer uw verbruik hoog is. 
Elke kWh die de batterij opslaat in plaats van 
exporteert bespaart u het verschil tussen de 
importprijs en de exportprijs. Op jaarbasis 
verschuift de batterij een deel van uw 
teruggeleverde energie naar eigen verbruik, 
wat uw afhankelijkheid van het net verlaagt.

5. Financiële analyse
De jaarlijkse besparing bedraagt [kernfeiten.batterij_besparing_eur] 
euro bij het huidige tarief. De terugverdientijd is 
meer dan 10 jaar, wat langer is dan de levensduur 
van de batterij. De ROI bedraagt [roi_percent]% over 
de volledige levensduur. Bij een batterijprijs van 
[kernfeiten.break_even_prijs] euro zou de ROI net 
positief zijn. Het voordeligste tarief met batterij 
is [kernfeiten.beste_tarief_met_batterij].

6. Aanbeveling
[Als ROI negatief: "Op basis van de huidige 
financiële analyse is de aanschaf van een 
thuisbatterij momenteel niet zinvol. De 
terugverdientijd overschrijdt de levensduur van 
de batterij." Als ROI positief: "Op basis van de 
financiële analyse is de aanschaf van een 
thuisbatterij zinvol. De investering verdient 
zichzelf terug binnen de levensduur."]
Het is raadzaam om de ontwikkelingen op de 
energiemarkt en batterijprijzen te volgen.

Bijlage A — Databronnen en invoer
De berekeningen zijn gebaseerd op het opgegeven 
jaarlijkse verbruik van [kernfeiten.jaarverbruik_kwh] 
kWh en een jaarlijkse zonne-energieproductie van 
[kernfeiten.jaaropwek_kwh] kWh. De verdeling van 
het verbruik over de dag is gebaseerd op een 
standaard verbruiksprofiel. De energietarieven 
zijn gebaseerd op de door u ingevoerde 
contractwaarden.

Bijlage B — Rekenmethodiek
De analyse bestaat uit drie scenario's. Scenario A1 
beschrijft de huidige situatie met saldering. 
Scenario B1 beschrijft de toekomst zonder saldering 
en zonder batterij. Scenario C1 beschrijft de 
toekomst zonder saldering maar met een batterij. 
De batterijbesparing is berekend op basis van het 
PV-overschot dat de batterij jaarlijks kan opslaan.

Bijlage C — Kostencomponenten
De energiekosten bestaan uit importkosten minus 
exportvergoeding plus vaste kosten zoals vastrecht. 
Bij saldering (A1) wordt import weggestreept tegen 
export tegen importprijs. Bij geen saldering (B1/C1) 
worden import en export apart verrekend tegen hun 
eigen tarieven.

Bijlage D — Beperkingen en aannames
Dit advies is gebaseerd op een modelmatige 
benadering. Werkelijke resultaten kunnen afwijken 
door gedragsveranderingen, weersinvloeden en 
technische beperkingen. De uitkomsten zijn 
indicatief en geven geen garantie voor toekomstige 
besparingen. Energieprijzen en regelgeving kunnen 
wijzigen.

REGELS:
- Gebruik GEEN markdown headers (geen ##)
- Gebruik genummerde secties zoals hierboven
- Vul ALLEEN de [HAAKJES] in met waarden uit JSON
- Wijzig GEEN andere tekst
- kernfeiten.beste_tarief_met_batterij "dag_nacht" 
  schrijf je als "dag/nacht tarief"
- kernfeiten.break_even_prijs = 
  kernfeiten.batterij_besparing_eur × battery.lifetime_years
  bereken dit zelf
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


def _build_advice_request_context_dict(ctx: AdviceContext) -> dict:
    ctx_dict = ctx.model_dump()
    ctx_dict["saldering_context"] = ctx.saldering_context
    ctx_dict["profile_inputs"] = (
        ctx.profile_inputs.model_dump()
        if ctx.profile_inputs is not None
        else None
    )

    # Verwijder energy_profile uit AI-context om foutieve (gesimuleerde) keuzes te voorkomen.
    ctx_dict.pop("energy_profile", None)

    saldering_impact_eur = (
        ctx.saldering_context.get("saldering_impact_eur")
        if ctx.saldering_context
        else None
    )
    batterij_besparing_eur = (
        (ctx.roi_per_tariff or {})
        .get(ctx.current_tariff or "enkel", {})
        .get("yearly_saving_eur")
        if ctx.roi_per_tariff
        else None
    )
    b1_cost_num = (
        (ctx.saldering_context or {}).get("b1_cost_eur")
        if ctx.saldering_context
        else None
    )
    c1_cost_num = None
    if b1_cost_num is not None and batterij_besparing_eur is not None:
        c1_cost_num = round(float(b1_cost_num) - float(batterij_besparing_eur), 2)

    # Pre-berekende kernfeiten: de AI hoeft niet te gokken of te kiezen.
    ctx_dict["kernfeiten"] = {
        "jaarverbruik_kwh": (
            ctx.profile_inputs.annual_load_kwh if ctx.profile_inputs else None
        ),
        "jaaropwek_kwh": (
            ctx.profile_inputs.annual_pv_kwh if ctx.profile_inputs else None
        ),
        "teruglevering_kwh": (
            ctx.profile_inputs.annual_feedin_kwh if ctx.profile_inputs else None
        ),
        "saldering_impact_eur": saldering_impact_eur,
        "batterij_besparing_eur": batterij_besparing_eur,
        "c1_cost_eur": c1_cost_num,
        "saldering_verhaal": (
            f"Het wegvallen van saldering kost u "
            f"{round(saldering_impact_eur)} euro per jaar "
            f"extra. Een batterij compenseert daarvan "
            f"{round(batterij_besparing_eur)} euro per jaar."
            if (
                saldering_impact_eur is not None
                and batterij_besparing_eur is not None
            )
            else None
        ),
        "beste_tarief_met_batterij": (
            min(
                ["enkel", "dag_nacht", "dynamisch"],
                key=lambda t: (
                    (ctx_dict.get("tariff_matrix") or {})
                    .get("C1", {})
                    .get(t, {})
                    .get("total_cost_eur", float("inf"))
                ),
            )
            if (ctx_dict.get("tariff_matrix") or {}).get("C1")
            else None
        ),
        # Energiestromen (voor Blok 1 en Blok 2 berekeningsuitleg)
        "netto_import_kwh": round(
            float((ctx_dict.get("saldering_context") or {}).get("netto_import_kwh", 0)),
            1,
        ),
        "feedin_kwh": round(
            float((ctx_dict.get("saldering_context") or {}).get("feedin_kwh", 0)),
            1,
        ),
        "directe_zelfconsumptie_kwh": round(
            float(
                (ctx_dict.get("saldering_context") or {}).get(
                    "directe_zelfconsumptie_kwh",
                    (ctx_dict.get("saldering_context") or {}).get("directe_zc_kwh", 0),
                )
            ),
            1,
        ),
        "gesaldeerde_kwh": round(
            float((ctx_dict.get("saldering_context") or {}).get("gesaldeerde_kwh", 0)),
            1,
        ),
        "a1_cost_eur": (ctx_dict.get("saldering_context") or {}).get("a1_cost_eur"),
        "b1_cost_eur": (ctx_dict.get("saldering_context") or {}).get("b1_cost_eur"),
        # Tarieven (voor berekeningsuitleg)
        "import_tarief_enkel": (
            (ctx_dict.get("saldering_context") or {}).get("import_tarief_enkel")
            if (ctx_dict.get("saldering_context") or {}).get("import_tarief_enkel")
            is not None
            else (ctx_dict.get("cost_components") or {}).get("p_enkel_imp", None)
        ),
        "export_tarief_enkel": (
            (ctx_dict.get("saldering_context") or {}).get("export_tarief_enkel")
            if (ctx_dict.get("saldering_context") or {}).get("export_tarief_enkel")
            is not None
            else (ctx_dict.get("cost_components") or {}).get("p_enkel_exp", None)
        ),
        "tariefverschil_enkel": (
            round(
                float(
                    (ctx_dict.get("saldering_context") or {}).get("tariefverschil_enkel")
                ),
                4,
            )
            if (ctx_dict.get("saldering_context") or {}).get("tariefverschil_enkel")
            is not None
            else round(
                (
                    (ctx_dict.get("cost_components") or {}).get("p_enkel_imp", 0) or 0
                )
                - (
                    (ctx_dict.get("cost_components") or {}).get("p_enkel_exp", 0) or 0
                ),
                3,
            )
        ),
        # A1 / B1 / C1 totalen per tarief (voor Blok 2 en Blok 3)
        "A1_per_tariff": {
            t: round(v.get("total_cost_eur", 0), 2)
            for t, v in (ctx_dict.get("tariff_matrix") or {}).items()
        },
        "B1_per_tariff": {
            t: round(v.get("total_cost_eur", 0), 2)
            for t, v in (ctx_dict.get("roi_per_tariff") or {}).items()
            if isinstance(v, dict) and "b1_cost_eur" in v
        },
        "C1_per_tariff": {
            t: round(v.get("c1_cost_eur", 0), 2)
            for t, v in (ctx_dict.get("roi_per_tariff") or {}).items()
            if isinstance(v, dict) and "c1_cost_eur" in v
        },
        # ROI details per tarief (voor Blok 3 berekeningsuitleg)
        "roi_details": {
            t: {
                "jaarlijkse_besparing_eur": round(v.get("yearly_saving_eur", 0), 2),
                "terugverdientijd": v.get("payback_years", None),
                "roi_percent": round(v.get("roi_percent", 0), 1),
                "verschoven_kwh": round(v.get("shifted_kwh", 0), 1)
                if "shifted_kwh" in v
                else None,
            }
            for t, v in (ctx_dict.get("roi_per_tariff") or {}).items()
            if isinstance(v, dict)
        },
        # Batterijgegevens (voor Blok 3 berekeningsuitleg)
        "batterij_capaciteit_kwh": (ctx_dict.get("battery") or {}).get("E", None),
        "batterij_vermogen_kw": (ctx_dict.get("battery") or {}).get("P", None),
        "degradatie_per_jaar_pct": (ctx_dict.get("battery") or {}).get(
            "degradation_pct", 2.0
        ),
        "levensduur_jaren": (ctx_dict.get("battery") or {}).get(
            "lifetime_years", 15
        ),
        "heeft_warmtepomp": bool(
            (ctx_dict.get("extra_consumers") or {}).get("heat_pump", False)
        ),
        "heeft_ev": bool((ctx_dict.get("extra_consumers") or {}).get("ev", False)),
    }

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

    return ctx_dict


@app.post("/generate_advice")
def generate_advice(
    req: AdviceRequest,
    request: Request,
    _device_track: Annotated[None, Depends(track_user_device)],
):
    ctx_dict = _build_advice_request_context_dict(req.context)

    prompt = (
        "Schrijf het volledige energieadviesrapport.\n\n"
        "JE MOET JE STRIKT HOUDEN AAN DE STRUCTUUR EN REGELS UIT DE SYSTEM PROMPT.\n\n"

        "VERBODEN:\n"
        "- Tabellen, matrixen, schema’s of kolomindelingen in welke vorm dan ook\n"
        "- Opsommingen met streepjes, bullets of genummerde lijsten\n"
        "- Markdown of pseudo-Markdown\n"
        "- Zelf bedachte of afgeleide cijfers, BEHALVE break_even_prijs in sectie 5 "
        "zoals in de INSTRUCTIE hieronder beschreven\n"
        "- Aanbevelingen die niet expliciet uit de feiten volgen\n\n"

        "VERPLICHT:\n"
        "- Iedere sectie (1 t/m 6) moet bestaan uit lopende tekst in volledige alinea’s\n"
        "- Na elke 3 tot maximaal 4 volledige zinnen MOET je een lege regel invoegen (witregel) zodat korte, leesbare alinea’s ontstaan\n"
        "- Na iedere sectietitel moet EXACT één lege regel volgen\n"
        "- Tussen de laatste alinea van een sectie en de volgende sectietitel MOETEN EXACT twee lege regels staan\n"
        "- Lange alinea’s moeten worden opgesplitst in leesblokken van circa 3 tot 4 zinnen, gescheiden door een lege regel\n"
        "- In de financiële analyse (sectie 5) gebruik je uitsluitend cijfers die in de JSON staan; verzin geen eigen cijfers\n"
        "- Een eventuele tariefmatrix wordt uitsluitend door de backend ingevoegd; verwerk die niet als eigen tabel in de hoofdtekst\n"
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

        "INSTRUCTIE — LEES DIT ZORGVULDIG VOOR JE BEGINT:\n"
        "1. JAARVERBRUIK: gebruik profile_inputs.annual_load_kwh\n"
        "   (NIET energy_profile.annual_load_kwh)\n"
        "2. TERUGLEVERING: gebruik kernfeiten.teruglevering_kwh\n"
        "   (NIET energy_profile of pv_export_kwh)\n"
        "3. SALDERING-IMPACT: gebruik in sectie 3 UITSLUITEND\n"
        "   de tekst uit kernfeiten.saldering_verhaal.\n"
        "   Kopieer deze zin letterlijk — verander geen getallen.\n"
        "   Voeg daarna een eigen zin toe over de narrative.\n"
        "4. NARRATIVE: saldering_context.narrative bepaalt\n"
        "   het verhaal in sectie 3:\n"
        "   - \"pain\": \"Het wegvallen van saldering kost u\n"
        "     [saldering_impact_eur] euro per jaar extra.\"\n"
        "   - \"neutral_or_positive\": \"Saldering levert u\n"
        "     weinig op omdat u meer exporteert dan importeert.\"\n"
        "   - \"minimal\": \"De salderingsafbouw heeft beperkte\n"
        "     impact voor uw situatie.\"\n"
        "5. EXPORTPRIJS en IMPORTPRIJS staan in \n"
        "   tariff_matrix als tarieven in euro per kWh.\n"
        "   Gebruik GEEN getallen uit kernfeiten als prijs.\n"
        "6. BESTE TARIEF MET BATTERIJ:\n"
        "   gebruik kernfeiten.beste_tarief_met_batterij\n"
        "   Dit is al voor u berekend. Gebruik dit direct.\n"
        "   \"dag_nacht\" vertaal je naar \"dag/nacht tarief\".\n"
        "7. BREAK-EVEN PRIJS: bereken als\n"
        "   roi_per_tariff.[huidig_tarief].yearly_saving_eur\n"
        "   × battery.lifetime_years\n"
        "   Dit is de maximale investeringsprijs waarbij de\n"
        "   ROI nog net nul is.\n"
        "   Bereken dit zelf op basis van de JSON-feiten.\n"
        "8. VERBODEN: gebruik nooit energy_profile getallen\n"
        "   als jaarverbruik of teruglevering in de hoofdtekst.\n"
        "   energy_profile is alleen voor intern gebruik.\n\n"
        "9. TERUGLEVERING: vermeld in sectie 2 expliciet\n"
        "   profile_inputs.annual_feedin_kwh als de\n"
        "   hoeveelheid die de klant jaarlijks teruglevert.\n\n"
        "Alle overige instructies blijven ongewijzigd.\n\n"

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

        return _attach_device_tracking(request, {"advice": content.strip()})

    except Exception as e:
        return _attach_device_tracking(
            request,
            {
                "error": str(e),
                "advice": "",
            },
        )


ANALYSE_SYSTEM_PROMPT = (
    "U schrijft een technische uitleg in het Nederlands. "
    "Volg de instructies van de gebruiker exact. Gebruik consequent de beleefdheidsvorm \"u\". "
    "Cijfers en bedragen uitsluitend uit het kernfeiten-JSON-blok in het gebruikersbericht; "
    "verzin niets."
)


@app.post("/generate_analyse")
def generate_analyse(
    req: AdviceRequest,
    request: Request,
    _device_track: Annotated[None, Depends(track_user_device)],
):
    ctx_dict = _build_advice_request_context_dict(req.context)
    kernfeiten_tekst = json.dumps(
        ctx_dict["kernfeiten"],
        ensure_ascii=False,
        indent=2,
    )
    pythonprompt = f"""
Je schrijft een uitgebreide analyse voor een klant over zijn thuisbatterij-situatie.
Gebruik altijd "u" als aanspreekvorm. Schrijf in het Nederlands. Geen inleiding, geen samenvatting, geen bijlagen, geen aanbeveling. Alleen de drie blokken hieronder.

KERNFEITEN (gebruik uitsluitend deze cijfers, verzin niets):
{kernfeiten_tekst}

KRITIEKE DEFINITIES — nooit verwarren:
- a1_cost_eur = huidige jaarkostentotaal MET saldering
- b1_cost_eur = toekomstig jaarkostentotaal ZONDER saldering, ZONDER batterij
- c1_cost_eur = toekomstig jaarkostentotaal ZONDER saldering, MET batterij
- import_tarief_enkel, export_tarief_enkel, tariefverschil_enkel = tarieven in €/kWh, GEEN jaarbedragen
- roi_percent en terugverdientijd staan in roi_details in de kernfeiten, gebruik alleen die waarden
- Verzin NOOIT ROI-percentages of terugverdientijden die niet in de kernfeiten staan

Schrijf nu de drie blokken in deze volgorde en exacte structuur.

Voor elk blok (1, 2 en 3) geldt VERPLICHT:
Schrijf voor elk blok VERPLICHT twee delen:
Deel A: de persoonlijke uitleg in 3-4 zinnen met exacte cijfers.
Deel B: begin ALTIJD met de exacte tekst "Hoe is dit berekend?" op een nieuwe regel, gevolgd door de berekeningsuitleg in 3-4 zinnen.

Sla "Hoe is dit berekend?" NOOIT over, ook niet als een getal ontbreekt. Schrijf in dat geval wat er wel bekend is.

---

Blok 1 — De situatie van uw huishouden

Deel A: schrijf 3-4 zinnen die het energieprofiel van deze klant beschrijven: jaarverbruik in kWh, zonnepanelenopwek in kWh, hoeveel kWh er wordt teruggeleverd, welk tarieftype, en of er een warmtepomp of EV aanwezig is. Wees specifiek met de cijfers uit de kernfeiten.

Deel B: begin met de exacte regel "Hoe is dit berekend?" en leg daarna in 3-4 zinnen uit hoe het huidige jaarkostentotaal (A1) tot stand komt. Gebruik deze formule als leidraad: het jaarverbruik min de directe zelfconsumptie geeft de netto-import. Van die netto-import wordt de gesaldeerde hoeveelheid verrekend tegen het importtarief. Het overschot boven de netto-import wordt vergoed tegen het lage exporttarief. Tel daar de vaste kosten bij op. Noem de exacte kWh-waarden en tarieven uit de kernfeiten voor zover ze daar staan.

---

Blok 2 — Wat het wegvallen van de saldering betekent

Deel A: schrijf 3-4 zinnen die uitleggen wat de overgang van A1 naar B1 financieel betekent voor deze klant. Noem A1, B1 en het verschil in euro's. Benoem dat de saldering verdwijnt en wat dat concreet voor het maandbedrag betekent.

Deel B: begin met de exacte regel "Hoe is dit berekend?" en leg daarna in 3-4 zinnen uit hoe B1 berekend is: bij het wegvallen van saldering wordt dezelfde hoeveelheid teruggeleverde kWh niet meer verrekend tegen het importtarief, maar vergoed tegen het lagere exporttarief. Het tariefverschil per kWh maal de teruggeleverde kWh verklaart het verschil. Noem import_tarief_enkel als het importtarief per kWh (in €/kWh), export_tarief_enkel als het exporttarief per kWh (in €/kWh), en tariefverschil_enkel als het verschil daartussen. Noem a1_cost_eur als het huidige jaarkostentotaal en b1_cost_eur als het toekomstige jaarkostentotaal. Verwar tarieven (€/kWh) nooit met kostentotalen (€/jaar). Noem ook feedin_kwh en saldering_impact_eur uit de kernfeiten voor zover ze daar staan.

---

Blok 3 — Wat de batterij voor u doet

Deel A: schrijf 3-4 zinnen over wat de batterij concreet verandert voor dit profiel: C1 versus B1, de jaarlijkse besparing, en de terugverdientijd en ROI in context. Zet de terugverdientijd in perspectief: is dit lang of normaal voor dit type investering en profiel.

Deel B: begin met de exacte regel "Hoe is dit berekend?" en leg daarna in 3-4 zinnen uit hoe C1 berekend is: de batterij absorbeert teruggeleverde zonnestroom en zet die om in zelfverbruik. Daardoor daalt de netto-import en stijgt de zelfconsumptie. De jaarlijkse besparing is het tariefverschil maal de verschoven kWh. De ROI is berekend over de volledige levensduur inclusief jaarlijkse degradatie. Noem batterij_capaciteit_kwh, de jaarlijkse besparing, c1_cost_eur, b1_cost_eur, roi_percent, terugverdientijd en degradatie_per_jaar_pct uit de kernfeiten voor zover ze daar staan.

---

Gebruik geen markdown, geen bulletpoints, geen vetgedrukte tekst. Gebruik wel de bloktitels en de verplichte regel "Hoe is dit berekend?" exact zoals hierboven; daarbij alleen lopende tekst.
"""
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": ANALYSE_SYSTEM_PROMPT},
                {"role": "user", "content": pythonprompt},
            ],
            max_tokens=4000,
            temperature=0.3,
        )

        content = response.choices[0].message.content
        return _attach_device_tracking(request, {"advice": content.strip()})

    except Exception as e:
        return _attach_device_tracking(
            request,
            {
                "error": str(e),
                "advice": "",
            },
        )


# SUPABASE MIGRATION REQUIRED:
# CREATE TABLE subscriptions (
#   id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
#   user_id uuid REFERENCES auth.users(id),
#   stripe_customer_id text,
#   stripe_subscription_id text UNIQUE,
#   status text DEFAULT 'active',
#   created_at timestamptz DEFAULT now(),
#   updated_at timestamptz DEFAULT now()
# );
# CREATE UNIQUE INDEX ON subscriptions(user_id);
# ALTER TABLE subscriptions ENABLE ROW LEVEL SECURITY;
# CREATE POLICY "Users can read own subscription"
#   ON subscriptions FOR SELECT
#   USING (auth.uid() = user_id);


def _subscriptions_supabase_config() -> tuple[str, str]:
    base = os.getenv("SUPABASE_URL", "").strip().rstrip("/")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    return base, key


def _subscriptions_rest_headers(prefer: Optional[str] = None) -> dict[str, str]:
    _, key = _subscriptions_supabase_config()
    h: dict[str, str] = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    if prefer:
        h["Prefer"] = prefer
    return h


def _upsert_subscription_impl(
    user_id: str,
    customer_id: Optional[str],
    subscription_id: str,
    status: str,
) -> None:
    base, key = _subscriptions_supabase_config()
    if not base or not key:
        logger.warning("subscriptions upsert: Supabase niet geconfigureerd")
        return
    if not user_id or not subscription_id:
        logger.warning(
            "subscriptions upsert: ontbrekende velden user_id=%s customer=%s sub=%s",
            user_id,
            customer_id,
            subscription_id,
        )
        return
    now_iso = datetime.now(timezone.utc).isoformat()
    url = f"{base}/rest/v1/subscriptions"
    headers = _subscriptions_rest_headers(
        "resolution=merge-duplicates,return=minimal"
    )
    params = {"on_conflict": "user_id"}
    body = {
        "user_id": user_id,
        "stripe_customer_id": customer_id,
        "stripe_subscription_id": subscription_id,
        "status": status,
        "created_at": now_iso,
        "updated_at": now_iso,
    }
    with httpx.Client(timeout=20.0) as client:
        r = client.post(url, headers=headers, params=params, json=body)
        r.raise_for_status()


async def _upsert_subscription(
    *,
    user_id: str,
    customer_id: Optional[str],
    subscription_id: str,
    status: str = "active",
) -> None:
    await asyncio.to_thread(
        _upsert_subscription_impl,
        user_id,
        customer_id,
        subscription_id,
        status,
    )


def _subscription_patch_by_stripe_subscription_id(
    subscription_id: str,
    fields: dict,
) -> None:
    base, key = _subscriptions_supabase_config()
    if not base or not key:
        logger.warning("subscriptions patch: Supabase niet geconfigureerd")
        return
    if not subscription_id:
        return
    url = f"{base}/rest/v1/subscriptions"
    headers = _subscriptions_rest_headers("return=minimal")
    params = {"stripe_subscription_id": f"eq.{subscription_id}"}
    fields = {**fields, "updated_at": datetime.now(timezone.utc).isoformat()}
    with httpx.Client(timeout=20.0) as client:
        r = client.patch(url, headers=headers, params=params, json=fields)
        r.raise_for_status()


class StripeCheckoutSessionRequest(BaseModel):
    user_id: str
    email: str
    success_url: str
    cancel_url: str


@app.post("/stripe/create-checkout-session")
def stripe_create_checkout_session(req: StripeCheckoutSessionRequest):
    if stripe is None:
        _raise_http_error(
            status_code=400,
            error_code="STRIPE_UNAVAILABLE",
            message="Stripe-bibliotheek is niet geïnstalleerd.",
        )
    if not (os.getenv("STRIPE_SECRET_KEY") or "").strip():
        _raise_http_error(
            status_code=400,
            error_code="STRIPE_NOT_CONFIGURED",
            message="STRIPE_SECRET_KEY ontbreekt in environment.",
        )
    uid = (req.user_id or "").strip()
    email = (req.email or "").strip()
    ok = (req.success_url or "").strip()
    cancel = (req.cancel_url or "").strip()
    if not uid or not email or not ok or not cancel:
        _raise_http_error(
            status_code=400,
            error_code="VALIDATION_ERROR",
            message="user_id, email, success_url en cancel_url zijn verplicht.",
        )
    try:
        session = stripe.checkout.Session.create(
            payment_method_types=[
                "card",
                "ideal",
                "bancontact",
                "sepa_debit",
            ],
            billing_address_collection="auto",
            mode="subscription",
            line_items=[
                {
                    "price": STRIPE_PRICE_ID,
                    "quantity": 1,
                }
            ],
            customer_email=email,
            client_reference_id=uid,
            success_url=ok,
            cancel_url=cancel,
            subscription_data={
                "metadata": {
                    "user_id": uid,
                }
            },
            metadata={
                "user_id": uid,
            },
        )
    except Exception as e:
        _raise_http_error(
            status_code=400,
            error_code="STRIPE_ERROR",
            message=str(e) or "Stripe Checkout Session aanmaken mislukt.",
        )
    if not session or not getattr(session, "url", None):
        _raise_http_error(
            status_code=400,
            error_code="STRIPE_ERROR",
            message="Geen checkout-URL ontvangen van Stripe.",
        )
    return {"checkout_url": session.url}


async def _send_welcome_email_resend(
    email: str, first_name: str = ""
):
    """Stuur welkomstmail via Resend."""
    try:
        if resend is None:
            logger.warning("resend-bibliotheek niet geïnstalleerd")
            return
        if not RESEND_API_KEY:
            logger.warning(
                "RESEND_API_KEY niet ingesteld"
            )
            return

        naam = first_name if first_name else "je"

        params = {
            "from": "Eco Metric <noreply@ecometric.nl>",
            "to": [email],
            "subject": "Welkom bij Eco Metric",
            "html": f"""
<div style="font-family:sans-serif;max-width:560px;
            margin:0 auto;padding:32px 24px;
            background:#f4f1eb;border-radius:12px;">

  <h2 style="font-family:sans-serif;color:#0a0f1a;
             font-size:1.4rem;margin-bottom:8px;">
    Welkom bij Eco Metric
  </h2>

  <p style="color:#4b5563;font-size:0.95rem;
            line-height:1.6;margin-bottom:16px;">
    Gefeliciteerd! Je abonnement is actief en 
    je account staat klaar!
  </p>

  <p style="color:#4b5563;font-size:0.95rem;
            line-height:1.6;margin-bottom:24px;">
    Klik op de knop hieronder om je e-mailadres 
    te bevestigen en direct in te loggen:
  </p>

  <a href="https://app.ecometric.nl"
     style="display:inline-block;
            background:#e8622a;color:#ffffff;
            font-size:1rem;font-weight:600;
            padding:14px 28px;border-radius:100px;
            text-decoration:none;
            margin-bottom:16px;">
    Account bevestigen en inloggen
  </a>

  <p style="color:#4b5563;font-size:0.95rem;
            line-height:1.6;margin-top:16px;">
    Succes!
  </p>

  <hr style="border:none;border-top:1px solid 
             #e5e0d8;margin:24px 0;">

  <p style="color:#9ca3af;font-size:0.8rem;
            line-height:1.5;">
    Je ontvangt deze mail omdat je je hebt 
    aangemeld bij Eco Metric.<br>
    Vragen? Mail naar 
    <a href="mailto:info@ecometric.nl" 
       style="color:#e8622a;">
      info@ecometric.nl
    </a>
  </p>

</div>
""",
        }

        resend.Emails.send(params)
        logger.info(
            "Welkomstmail verstuurd naar %s", email
        )

    except Exception as e:
        logger.warning(
            "Welkomstmail mislukt: %s", e
        )


@app.post("/stripe/webhook")
async def stripe_webhook(request: Request):
    if stripe is None:
        raise HTTPException(status_code=400, detail="Stripe niet beschikbaar.")
    if not (STRIPE_WEBHOOK_SECRET or "").strip():
        raise HTTPException(
            status_code=400,
            detail="STRIPE_WEBHOOK_SECRET ontbreekt.",
        )
    payload = await request.body()
    sig = request.headers.get("stripe-signature")
    try:
        event = stripe.Webhook.construct_event(
            payload,
            sig,
            STRIPE_WEBHOOK_SECRET,
        )
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid payload")
    except stripe.error.SignatureVerificationError:
        raise HTTPException(status_code=400, detail="Invalid signature")

    try:
        etype = event.type
        session = event.data.object
        if etype == "checkout.session.completed":
            user_id = getattr(session, "client_reference_id", None)
            customer_id = getattr(session, "customer", None)
            subscription_id = getattr(session, "subscription", None)
            if user_id and customer_id and subscription_id:
                await _upsert_subscription(
                    user_id=str(user_id),
                    customer_id=str(customer_id),
                    subscription_id=str(subscription_id),
                    status="active",
                )
                # Haal email en naam op en stuur welkomstmail
                first_name = ""
                try:
                    user_email = getattr(
                        session, "customer_email", None
                    )
                    if not user_email and user_id:
                        # Haal email op via Supabase Admin API
                        supabase_url = os.getenv(
                            "SUPABASE_URL", ""
                        ).strip().rstrip("/")
                        service_key = os.getenv(
                            "SUPABASE_SERVICE_ROLE_KEY", ""
                        )
                        if supabase_url and service_key:
                            async with httpx.AsyncClient() as client:
                                resp = await client.get(
                                    f"{supabase_url}/auth/v1/admin"
                                    f"/users/{user_id}",
                                    headers={
                                        "apikey": service_key,
                                        "Authorization":
                                            f"Bearer {service_key}",
                                    },
                                )
                                if resp.status_code == 200:
                                    user_data = resp.json()
                                    user_email = user_data.get(
                                        "email"
                                    )
                                    first_name = (
                                        user_data
                                        .get("user_metadata", {})
                                        .get("first_name", "")
                                    )

                    if user_email:
                        await _send_welcome_email_resend(
                            str(user_email), first_name
                        )
                except Exception as e:
                    logger.warning(
                        "Welkomstmail flow mislukt: %s", e
                    )
        elif etype == "checkout.session.async_payment_succeeded":
            user_id = getattr(session, "client_reference_id", None)
            customer_id = getattr(session, "customer", None)
            subscription_id = getattr(session, "subscription", None)
            if user_id and subscription_id:
                await _upsert_subscription(
                    user_id=str(user_id),
                    customer_id=str(customer_id) if customer_id else None,
                    subscription_id=str(subscription_id),
                    status="active",
                )
        elif etype == "customer.subscription.deleted":
            subscription_id = getattr(
                event.data.object, "id", None
            )
            if subscription_id:
                _subscription_patch_by_stripe_subscription_id(
                    str(subscription_id),
                    {"status": "cancelled"},
                )
        elif etype == "customer.subscription.updated":
            subscription_id = getattr(
                event.data.object, "id", None
            )
            status = getattr(
                event.data.object, "status", None
            )
            if subscription_id and status is not None:
                _subscription_patch_by_stripe_subscription_id(
                    str(subscription_id),
                    {"status": str(status)},
                )
    except Exception as e:
        logger.warning("stripe webhook verwerking mislukt: %s", e, exc_info=True)

    return {"received": True}


@app.get("/subscription/status")
def subscription_status(
    request: Request,
    current_user: Annotated[Optional[AuthenticatedUser], Depends(get_current_user)],
    _device_track: Annotated[None, Depends(track_user_device)],
):
    if current_user is None:
        _raise_http_error(
            status_code=401,
            error_code="UNAUTHORIZED",
            message="Authenticatie vereist.",
        )
    base, key = _subscriptions_supabase_config()
    if not base or not key:
        return _attach_device_tracking(
            request,
            {"active": False, "status": None},
        )
    url = f"{base}/rest/v1/subscriptions"
    headers = _subscriptions_rest_headers()
    params = {
        "user_id": f"eq.{current_user.id}",
        "select": "status",
        "limit": "1",
    }
    try:
        with httpx.Client(timeout=15.0) as client:
            r = client.get(url, headers=headers, params=params)
            r.raise_for_status()
            rows = r.json()
    except Exception as e:
        logger.warning("subscription status query mislukt: %s", e)
        return _attach_device_tracking(
            request,
            {"active": False, "status": None},
        )
    if not isinstance(rows, list) or not rows:
        return _attach_device_tracking(
            request,
            {"active": False, "status": None},
        )
    status = rows[0].get("status")
    if status is not None:
        status = str(status)
    active = status == "active"
    return _attach_device_tracking(
        request,
        {"active": active, "status": status},
    )


# RENDER ENVIRONMENT VARIABLES REQUIRED:
# STRIPE_SECRET_KEY=sk_live_...
# STRIPE_WEBHOOK_SECRET=whsec_Xtd16NCWE0glcn3MeF69dly9NqebTIiQ
# STRIPE_PRICE_ID=price_1SjT5x2Y2l8Uvp2bS1UTY7nC
# RESEND_API_KEY=re_anGxKmTn_6s2ofBmqsdu7cmuuTXhp3JNZ









































