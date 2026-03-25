# battery_engine_pro3/profile_generator.py

from __future__ import annotations
from dataclasses import dataclass
from typing import List, Tuple, Dict, Optional
from datetime import datetime, timedelta
import math
import logging

logger = logging.getLogger(__name__)


# ------------------------------------------------------------
# PROFIELEN (24u verdeling) — simpel maar verdedigbaar
# Percentages moeten optellen naar 1.0
# ------------------------------------------------------------

HOUSEHOLD_PROFILES: Dict[str, List[float]] = {
    # relatief vlak + avondpiek
    "alleenstaand_werkend": [
        0.020, 0.015, 0.012, 0.012, 0.014, 0.020,
        0.030, 0.035, 0.030, 0.025, 0.025, 0.030,
        0.035, 0.035, 0.030, 0.030, 0.035, 0.050,
        0.070, 0.080, 0.075, 0.055, 0.035, 0.025
    ],
    "samenwonend_werkend": [
        0.020, 0.015, 0.012, 0.012, 0.015, 0.024,
        0.040, 0.040, 0.032, 0.028, 0.027, 0.030,
        0.033, 0.033, 0.030, 0.031, 0.038, 0.055,
        0.072, 0.078, 0.072, 0.052, 0.033, 0.023
    ],
    # ochtend + avond meer
    "gezin_kinderen": [
        0.020, 0.015, 0.012, 0.012, 0.015, 0.030,
        0.050, 0.045, 0.035, 0.030, 0.028, 0.030,
        0.032, 0.032, 0.030, 0.032, 0.040, 0.060,
        0.075, 0.080, 0.070, 0.050, 0.032, 0.022
    ],
    # verspreid overdag, vlakker dan gezin_kinderen; relatief hoog 09–17
    "gepensioneerd": [
        0.018, 0.014, 0.011, 0.011, 0.013, 0.022,
        0.032, 0.038, 0.042, 0.048, 0.052, 0.055,
        0.055, 0.054, 0.052, 0.050, 0.048, 0.050,
        0.058, 0.062, 0.058, 0.044, 0.030, 0.021
    ],
}

# simpele maandfactoren (winter hoger, zomer lager) — som ≈ 12
MONTH_LOAD_FACTORS = [1.10, 1.08, 1.02, 0.98, 0.95, 0.92, 0.90, 0.90, 0.94, 1.00, 1.05, 1.06]

# PV maandfactoren (zomer hoger) — som ≈ 12
MONTH_PV_FACTORS = [0.35, 0.45, 0.75, 1.05, 1.25, 1.35, 1.35, 1.20, 0.95, 0.65, 0.40, 0.30]


def _normalize(vec: List[float]) -> List[float]:
    s = sum(vec)
    if s <= 0:
        return vec
    return [v / s for v in vec]


def _pv_shape_hour(hour: int) -> float:
    # simpele “bel-curve” rond 13:00, nul in nacht
    if hour < 6 or hour > 20:
        return 0.0
    x = (hour - 13) / 4.2
    return math.exp(-0.5 * x * x)


def generate_year_timestamps(year: int = 2025, dt_hours: float = 1.0) -> List[datetime]:
    start = datetime(year, 1, 1)
    steps = int(round(8760 / dt_hours))
    return [start + timedelta(hours=i * dt_hours) for i in range(steps)]


def _calibrate_profile_to_feedin(
    load_values: List[float],
    pv_values: List[float],
    target_feedin_kwh: float,
    timestamps: List[datetime],
    max_iterations: int = 20,
    tolerance_frac: float = 0.05,
) -> List[float]:
    """
    Calibreert het verbruiksprofiel zodat de gesimuleerde
    teruglevering overeenkomt met de opgegeven teruglevering.

    Werking:
    - Bereken gesimuleerde teruglevering (som van PV-overschot)
    - Als afwijking > tolerance_frac: verhoog verbruik op
      PV-productie-uren (uur 8-16) iteratief
    - Maximaal max_iterations iteraties
    - Behoudt de totale jaarlijkse energie (herscaling)

    Returns: gecalibreerde load_values lijst
    """
    if target_feedin_kwh <= 0:
        return load_values

    values = load_values[:]
    n = len(values)

    for iteration in range(max_iterations):
        # Bereken huidige gesimuleerde teruglevering
        simulated_feedin = sum(
            max(0.0, pv_values[i] - values[i])
            for i in range(min(n, len(pv_values)))
        )

        if simulated_feedin <= 0:
            break

        deviation_frac = (
            simulated_feedin - target_feedin_kwh
        ) / max(target_feedin_kwh, 1e-9)

        # Binnen tolerantie: stop
        if abs(deviation_frac) <= tolerance_frac:
            break

        if deviation_frac > 0:
            # Gesimuleerde teruglevering te hoog:
            # verhoog verbruik op PV-uren (08:00-16:00)
            # Correctiefactor: hoe ver zijn we af?
            correction = min(1.0 + deviation_frac * 0.5, 1.30)

            annual_before = sum(values)
            for i in range(n):
                hour = timestamps[i].hour if i < len(timestamps) else (i % 24)
                if 8 <= hour <= 16:
                    values[i] *= correction

            # Herscale zodat totaal jaarverbruik gelijk blijft
            annual_after = sum(values)
            if annual_after > 0 and annual_before > 0:
                scale = annual_before / annual_after
                values = [v * scale for v in values]

        else:
            # Gesimuleerde teruglevering te laag:
            # verlaag verbruik op PV-uren
            correction = max(1.0 + deviation_frac * 0.5, 0.70)

            annual_before = sum(values)
            for i in range(n):
                hour = timestamps[i].hour if i < len(timestamps) else (i % 24)
                if 8 <= hour <= 16:
                    values[i] *= correction

            annual_after = sum(values)
            if annual_after > 0 and annual_before > 0:
                scale = annual_before / annual_after
                values = [v * scale for v in values]

    return values


def generate_load_profile_kwh(
    annual_load_kwh: float,
    household_profile: str,
    has_heatpump: bool,
    has_ev: bool,
    daytime_fraction: Optional[float] = None,
    home_during_day: Optional[str] = None,
    monthly_kwh: Optional[List[float]] = None,
    ev_charge_window: str = "evening_night",
    dt_hours: float = 1.0,
    year: int = 2025,
    heatpump_type: Optional[str] = None,
    heatpump_schedule: Optional[str] = None,
    annual_feedin_kwh: Optional[float] = None,
    pv_values_for_calibration: Optional[List[float]] = None,
) -> Tuple[List[datetime], List[float]]:
    """
    Genereert een synthetisch jaarprofiel (kWh per timestep).
    - household_profile bepaalt 24u verdeling
    - daytime_fraction (optioneel) forceert dag/nacht-split in uurweights
    - home_during_day (optioneel): 'never', 'partial' of 'always'.
      Bepaalt de dag/nacht-verdeling als daytime_fraction niet bekend is.
    - monthly_kwh (optioneel): 12 maandwaarden in kWh vervangen
      de synthetische seizoensverdeling. Meest nauwkeurig als beschikbaar.
    - maandfactoren geven seizoensvorm
    - warmtepomp/EV zijn modifiers op vorm (niet op 'eerlijke' data)
    - heatpump_type: type warmtepomp ('air_water' of 'air_water_buffer')
    - heatpump_schedule: wanneer de warmtepomp voornamelijk draait
      ('night', 'day', 'day_night')
    - annual_feedin_kwh (optioneel): opgegeven jaarlijkse
      teruglevering in kWh. Wordt gebruikt om het profiel
      te calibreren zodat de gesimuleerde teruglevering
      overeenkomt met de werkelijkheid.
    - pv_values_for_calibration: het gegenereerde PV-profiel
      (8760 waarden) nodig voor calibratie.
    """
    profile = HOUSEHOLD_PROFILES.get(household_profile, HOUSEHOLD_PROFILES["gezin_kinderen"])
    profile = _normalize(profile)

    if daytime_fraction is None and home_during_day is not None:
        mode = str(home_during_day).strip().lower()
        if mode in {"never", "partial", "always"}:
            if mode == "never":
                dag_boost = 0.75
                nacht_boost = 1.35
            elif mode == "always":
                dag_boost = 1.30
                nacht_boost = 0.80
            else:
                dag_boost = 1.0
                nacht_boost = 1.0

            dag_hours = list(range(7, 23))  # 07:00 t/m 22:00
            nacht_hours = [23] + list(range(0, 7))
            adjusted = profile[:]
            for h in dag_hours:
                adjusted[h] *= dag_boost
            for h in nacht_hours:
                adjusted[h] *= nacht_boost
            profile = _normalize(adjusted)

    ts = generate_year_timestamps(year=year, dt_hours=dt_hours)
    values = [0.0] * len(ts)

    # Modifier templates (simpel, verdedigbaar)
    # Warmtepomp: uurpatroon + winter zwaarder (maandfactor, zie hieronder)
    hp_hour_boost = [1.0] * 24
    if has_heatpump:
        hp_type = (heatpump_type or "air_water").strip().lower()
        if hp_type not in ("air_water", "air_water_buffer"):
            hp_type = "air_water"
        hp_schedule = (heatpump_schedule or "day_night").strip().lower()
        if hp_schedule not in ("night", "day", "day_night"):
            hp_schedule = "day_night"

        if hp_type == "air_water_buffer":
            # Warmtepomp met buffervat: vlakker profiel;
            # laadt buffer voornamelijk 's nachts en vroeg ochtend
            if hp_schedule == "night":
                for h in range(0, 6):
                    hp_hour_boost[h] = 1.25
                for h in range(6, 9):
                    hp_hour_boost[h] = 1.10
            elif hp_schedule == "day":
                for h in range(8, 17):
                    hp_hour_boost[h] = 1.18
            else:  # day_night (default)
                for h in range(0, 6):
                    hp_hour_boost[h] = 1.15
                for h in range(6, 9):
                    hp_hour_boost[h] = 1.10
                for h in range(14, 17):
                    hp_hour_boost[h] = 1.08

        else:  # air_water (geen buffervat, meest voorkomend)
            if hp_schedule == "night":
                for h in range(0, 6):
                    hp_hour_boost[h] = 1.20
                for h in range(6, 9):
                    hp_hour_boost[h] = 1.15
            elif hp_schedule == "day":
                for h in range(8, 18):
                    hp_hour_boost[h] = 1.20
            else:  # day_night (default)
                for h in range(6, 9):
                    hp_hour_boost[h] = 1.18
                for h in range(17, 22):
                    hp_hour_boost[h] = 1.20

        # Seizoensmodifier: warmtepomp maakt winter zwaarder
        # (alleen als monthly_kwh niet opgegeven is — zie month_f-blok hieronder)

    # EV: extra verbruik op basis van laadmoment
    ev_hour_boost = [1.0] * 24

    if has_ev:
        mode = (ev_charge_window or "evening_night").strip().lower()

        if mode == "night":
            # vooral 00:00–06:00
            for h in range(0, 6):
                ev_hour_boost[h] = 1.14

        elif mode == "midday":
            # vooral overdag (bijv. thuis / PV-laden)
            for h in range(10, 16):
                ev_hour_boost[h] = 1.14

        elif mode == "spread":
            # licht verhoogd over veel uren
            for h in range(7, 23):
                ev_hour_boost[h] = 1.06
            for h in range(0, 2):
                ev_hour_boost[h] = 1.04

        else:
            # default: evening_night
            for h in range(18, 24):
                ev_hour_boost[h] = 1.14
            for h in range(0, 2):
                ev_hour_boost[h] = 1.10

    use_monthly_kwh = False
    if monthly_kwh is not None:
        if len(monthly_kwh) != 12:
            logger.warning(
                "monthly_kwh verwacht exact 12 waarden; fallback naar MONTH_LOAD_FACTORS."
            )
        elif any((v is None or float(v) < 0) for v in monthly_kwh) or sum(float(v) for v in monthly_kwh) <= 0:
            logger.warning(
                "monthly_kwh bevat ongeldige waarden (<0 of som<=0); fallback naar MONTH_LOAD_FACTORS."
            )
        else:
            provided_sum = sum(float(v) for v in monthly_kwh)
            if annual_load_kwh > 0:
                rel_dev = abs(provided_sum - annual_load_kwh) / annual_load_kwh
                if rel_dev > 0.20:
                    logger.warning(
                        "Som monthly_kwh wijkt >20%% af van annual_load_kwh (monthly=%s, annual=%s).",
                        provided_sum,
                        annual_load_kwh,
                    )
            use_monthly_kwh = True

    # per maand eerst normaliseren zodat elk maandblok netjes verdeeld is
    # alleen van toepassing als monthly_kwh niet is opgegeven/geldig
    month_f = None
    if not use_monthly_kwh:
        month_f = MONTH_LOAD_FACTORS[:]
        if has_heatpump:
            # warmtepomp maakt winter sterker
            month_f = month_f[:]
            for m in [0, 1, 10, 11]:  # jan, feb, nov, dec
                month_f[m] *= 1.10
        month_f = _normalize(month_f)

    # dagen per maand (geen schrikkeljaar)
    days_per_month = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]

    # totale kWh verdelen over maanden → dagen → uren
    idx = 0
    for month_idx, days in enumerate(days_per_month):
        if use_monthly_kwh:
            month_kwh = float(monthly_kwh[month_idx])
        else:
            month_kwh = annual_load_kwh * month_f[month_idx]
        day_kwh = month_kwh / days

        # uurshape incl modifiers
        hour_shape = [profile[h] * hp_hour_boost[h] * ev_hour_boost[h] for h in range(24)]
        if daytime_fraction is not None:
            target = float(daytime_fraction)
            if target < 0.05 or target > 0.95:
                logger.warning(
                    "daytime_fraction buiten bereik [0.05, 0.95]; "
                    "clipping toegepast: %s", target,
                )
                target = min(0.95, max(0.05, target))

            # Bereken de PV-overlap fractie:
            # daytime_fraction van netbeheerder = dag (07-23) / totaal
            # Wij willen weten hoeveel verbruik tijdens PV-uren (07-17) valt
            #
            # Aanname: avondverbruik (17-23) is relatief stabiel.
            # Als dag/totaal = target, dan is PV-uur verbruik = target minus
            # het aandeel dat in de avond (17-23) valt.
            #
            # We schalen ALLEEN de PV-uren (07-17) zodat de verhouding
            # verbruik-tijdens-PV correct is. Avond en nacht blijven
            # proportioneel.

            pv_uren = list(range(7, 17))  # 07:00-16:00
            avond_uren = list(range(17, 23))  # 17:00-22:00
            nacht_uren = [23] + list(range(0, 7))

            totaal = max(sum(hour_shape), 1e-9)

            huidig_pv_frac = sum(hour_shape[h] for h in pv_uren) / totaal
            huidig_avond_frac = sum(hour_shape[h] for h in avond_uren) / totaal
            huidig_nacht_frac = sum(hour_shape[h] for h in nacht_uren) / totaal

            # target = dag (07-23) fractie van netbeheerder
            # avond_frac blijft ongewijzigd (avondverbruik is stabiel)
            # nacht_frac wordt aangepast zodat dag+nacht=1
            # pv_frac krijgt het resterende dagverbruik

            # Gewenste pv_frac = target - huidig_avond_frac
            # (maar minimaal 0.05 om negatieve waarden te voorkomen)
            gewenste_pv_frac = max(0.05, target - huidig_avond_frac)
            gewenste_nacht_frac = 1.0 - huidig_avond_frac - gewenste_pv_frac

            # Schaalfactoren
            pv_scale = (
                gewenste_pv_frac / huidig_pv_frac
                if huidig_pv_frac > 1e-9 else 1.0
            )
            nacht_scale = (
                gewenste_nacht_frac / huidig_nacht_frac
                if huidig_nacht_frac > 1e-9 else 1.0
            )
            # avond_scale = 1.0 (ongewijzigd)

            adjusted = hour_shape[:]
            for h in pv_uren:
                adjusted[h] *= pv_scale
            for h in nacht_uren:
                adjusted[h] *= nacht_scale
            hour_shape = adjusted
        hour_shape = _normalize(hour_shape)

        for _ in range(days):
            for hour in range(24):
                # dt_hours is 1.0 in onze default; als je later kwartier wil: opsplitsen
                values[idx] = day_kwh * hour_shape[hour]
                idx += 1

    # Calibratie op basis van opgegeven teruglevering
    if (
        annual_feedin_kwh is not None
        and annual_feedin_kwh > 0
        and pv_values_for_calibration is not None
        and len(pv_values_for_calibration) >= len(values)
    ):
        simulated_before = sum(
            max(0.0, pv_values_for_calibration[i] - values[i])
            for i in range(len(values))
        )
        deviation_pct = abs(
            simulated_before - annual_feedin_kwh
        ) / max(annual_feedin_kwh, 1e-9) * 100

        if deviation_pct > 5.0:
            logger.info(
                "Profiel calibratie gestart: gesimuleerde "
                "teruglevering %.0f kWh, opgegeven %.0f kWh "
                "(afwijking %.0f%%)",
                simulated_before,
                annual_feedin_kwh,
                deviation_pct,
            )
            values = _calibrate_profile_to_feedin(
                load_values=values,
                pv_values=pv_values_for_calibration[: len(values)],
                target_feedin_kwh=annual_feedin_kwh,
                timestamps=ts,
            )
            simulated_after = sum(
                max(0.0, pv_values_for_calibration[i] - values[i])
                for i in range(len(values))
            )
            logger.info(
                "Profiel calibratie klaar: teruglevering "
                "na calibratie %.0f kWh",
                simulated_after,
            )

    # guard
    values = values[:len(ts)]
    return ts, values


def generate_pv_profile_kwh(
    annual_pv_kwh: float,
    dt_hours: float = 1.0,
    year: int = 2025
) -> Tuple[List[datetime], List[float]]:
    """
    Synthetisch PV-profiel per uur:
    - maandfactoren
    - dagcurve (belvorm)
    """
    ts = generate_year_timestamps(year=year, dt_hours=dt_hours)
    values = [0.0] * len(ts)

    month_f = _normalize(MONTH_PV_FACTORS[:])

    days_per_month = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]

    idx = 0
    for month_idx, days in enumerate(days_per_month):
        month_kwh = annual_pv_kwh * month_f[month_idx]

        # eerst dagcurve normaliseren zodat per dag sum=1 (alleen over 24 uren)
        day_shape = [_pv_shape_hour(h) for h in range(24)]
        day_shape = _normalize(day_shape)

        day_kwh = month_kwh / days

        for _ in range(days):
            for hour in range(24):
                values[idx] = day_kwh * day_shape[hour]
                idx += 1

    values = values[:len(ts)]
    return ts, values


def generate_dynamic_prices_eur_per_kwh(
    avg_price: float,
    spread: float,
    cheap_hours_per_day: int,
    dt_hours: float = 1.0,
    year: int = 2025
) -> List[float]:
    """
    Maakt synthetische uurprijzen voor een jaar.
    - avg_price: gemiddelde importprijs
    - spread: +/-
    - cheap_hours_per_day: aantal goedkope uren (laag), rest duurder
    """
    ts = generate_year_timestamps(year=year, dt_hours=dt_hours)
    n = len(ts)
    prices = [avg_price] * n

    cheap = max(1, min(12, int(cheap_hours_per_day)))
    expensive = 24 - cheap

    low = max(0.01, avg_price - spread)
    high = max(0.01, avg_price + spread)

    # per dag pattern: goedkoop in nacht + middag, duurder ochtend/avond
    idx = 0
    days = int(round(365))
    for _ in range(days):
        # cheap hours: 0-5 + 12-? (simpel)
        cheap_hours = set(list(range(0, min(6, cheap))) + list(range(12, 12 + max(0, cheap - 6))))
        for h in range(24):
            prices[idx] = low if h in cheap_hours else high
            idx += 1

    return prices[:n]
