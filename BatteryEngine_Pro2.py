from __future__ import annotations

from dataclasses import dataclass
from typing import List, Dict, Any

INTERVAL_HOURS = 0.25  # 15 minuten


@dataclass
class BatteryConfig:
    capacity_kwh: float  # nominale capaciteit
    power_kw: float      # maximaal laad/ontlaadvermogen
    dod: float           # depth-of-discharge (0–1, bv. 0.9)
    eta_rt: float        # round-trip rendement (0–1, bv. 0.9)

    @property
    def usable_capacity(self) -> float:
        # We modelleren usable = E * DoD
        return max(self.capacity_kwh * self.dod, 0.0)


def _ensure_same_length(a: List[float], b: List[float], c: List[float]) -> int:
    """
    Zorgt dat alle lijsten dezelfde lengte gebruiken (neemt het minimum).
    Geeft de effectieve lengte terug.
    """
    n = min(len(a), len(b), len(c)) if c else min(len(a), len(b))
    return n


def _is_day_quarter(idx: int) -> bool:
    """
    Bepaalt voor een kwartier-index of dit dag of nacht is.
    Dag: 07:00–23:00, Nacht: 23:00–07:00.
    idx = 0 is 00:00–00:15.
    """
    minutes_per_slot = 15
    minutes_per_day = 24 * 60
    minute_of_day = (idx * minutes_per_slot) % minutes_per_day
    return 7 * 60 <= minute_of_day < 23 * 60


def _build_import_price_series_enkel(n: int, p_enkel_imp: float) -> List[float]:
    return [float(p_enkel_imp)] * n


def _build_import_price_series_dn(n: int, p_dag: float, p_nacht: float) -> List[float]:
    prices = []
    for i in range(n):
        prices.append(float(p_dag if _is_day_quarter(i) else p_nacht))
    return prices


def _build_import_price_series_dyn(n: int, prices_dyn: List[float], fallback: float) -> List[float]:
    if not prices_dyn:
        return [float(fallback)] * n
    if len(prices_dyn) >= n:
        return [float(prices_dyn[i]) for i in range(n)]
    # als de prijzen korter zijn dan het profiel, herhalen we ze cyclisch
    out = []
    m = len(prices_dyn)
    for i in range(n):
        out.append(float(prices_dyn[i % m]))
    return out


def _simulate_no_battery(
    load_kwh: List[float],
    pv_kwh: List[float],
    import_prices: List[float],
    export_price: float,
    vastrecht: float,
) -> Dict[str, float]:
    """
    Scenario zonder batterij, zonder saldering.
    Op kwartierbasis: eerst PV op verbruik, rest import/export.
    """
    n = min(len(load_kwh), len(pv_kwh), len(import_prices))
    total_import = 0.0
    total_export = 0.0
    cost_import = 0.0
    revenue_export = 0.0

    for i in range(n):
        load = float(load_kwh[i])
        pv = float(pv_kwh[i])
        price_imp = float(import_prices[i])

        # Eerst eigen PV op eigen verbruik
        residual = load - pv
        if residual >= 0:
            # te weinig PV -> import
            imp = residual
            exp = 0.0
        else:
            # overschot PV -> export
            imp = 0.0
            exp = -residual

        total_import += imp
        total_export += exp

        cost_import += imp * price_imp
        revenue_export += exp * export_price

    total_cost = cost_import - revenue_export + float(vastrecht)

    return {
        "import": total_import,
        "export": total_export,
        "cost_import": cost_import,
        "revenue_export": revenue_export,
        "total_cost": total_cost,
    }


def _simulate_with_battery(
    load_kwh: List[float],
    pv_kwh: List[float],
    import_prices: List[float],
    export_price: float,
    vastrecht: float,
    batt: BatteryConfig,
) -> Dict[str, float]:
    """
    Scenario met batterij (alleen PV-optimalisatie, geen arbitrage op dynamische prijzen).
    Strategie:
      - Gebruik eerst PV voor direct verbruik.
      - Overschot PV -> batterij (tot vermogen/capaciteit).
      - Daarna overschot PV -> export.
      - Bij tekort na PV:
          - eerst batterij ontladen (tot vermogen / beschikbare SOC).
          - rest -> import.
    """
    n = min(len(load_kwh), len(pv_kwh), len(import_prices))
    usable_cap = batt.usable_capacity

    # start SOC op 50% van usable capacity
    soc = 0.5 * usable_cap

    total_import = 0.0
    total_export = 0.0
    cost_import = 0.0
    revenue_export = 0.0

    for i in range(n):
        load = float(load_kwh[i])
        pv = float(pv_kwh[i])
        price_imp = float(import_prices[i])

        # Eerst PV-op-eigen-verbruik:
        residual = load - pv  # >0 = tekort, <0 = overschot

        # Limiet per kwartier vanuit batterijvermogen
        max_batt_energy_per_step = batt.power_kw * INTERVAL_HOURS

        if residual >= 0:
            # Tekort na PV -> eerst batterij, dan grid
            # hoeveel energie kunnen we maximaal uit batterij trekken (voor SOC)?
            # We modelleren verlies bij ontladen: uitgangs-energie = eta_rt * energie_uit_batterij
            max_from_batt = min(soc, max_batt_energy_per_step)
            # We hebben residual kWh nodig aan uitgangsenergie
            needed_from_batt = residual / batt.eta_rt if batt.eta_rt > 0 else 0.0
            take_from_batt = min(max_from_batt, needed_from_batt)

            energy_to_load_from_batt = take_from_batt * batt.eta_rt
            soc -= take_from_batt

            remaining_shortage = residual - energy_to_load_from_batt
            if remaining_shortage < 0:
                remaining_shortage = 0.0

            imp = remaining_shortage
            exp = 0.0

        else:
            # Overschot PV -> eerst batterij laden, dan export
            surplus = -residual  # kWh PV over
            # Maximaal wat we in batterij kwijt kunnen (vermogen + resterende ruimte)
            space = usable_cap - soc
            if space < 0:
                space = 0.0
            max_charge = min(max_batt_energy_per_step, space)

            charge = min(surplus, max_charge)
            soc += charge  # verlies bij ontladen gemodelleerd, niet bij laden
            remaining_surplus = surplus - charge
            if remaining_surplus < 0:
                remaining_surplus = 0.0

            imp = 0.0
            exp = remaining_surplus

        total_import += imp
        total_export += exp
        cost_import += imp * price_imp
        revenue_export += exp * export_price

    total_cost = cost_import - revenue_export + float(vastrecht)

    return {
        "import": total_import,
        "export": total_export,
        "cost_import": cost_import,
        "revenue_export": revenue_export,
        "total_cost": total_cost,
    }


def _compute_A1_with_saldering(
    load_kwh: List[float],
    pv_kwh: List[float],
    import_prices: List[float],
    export_price: float,
    vastrecht: float,
) -> Dict[str, float]:
    """
    Huidige situatie met saldering (geen batterij).
    - We nemen JAARLIJKSE saldering:
        net = Σ(load) - Σ(pv)
      Als net >= 0: je betaalt net * gemiddelde importprijs.
      Als net < 0: je krijgt |net| * exportprijs vergoed.
    - Gemiddelde importprijs is verbruiks-gewogen.
    """
    n = min(len(load_kwh), len(pv_kwh), len(import_prices))
    total_load = 0.0
    total_pv = 0.0
    weighted_import_cost = 0.0

    for i in range(n):
        l = float(load_kwh[i])
        p = float(pv_kwh[i])
        price_imp = float(import_prices[i])

        total_load += l
        total_pv += p
        weighted_import_cost += l * price_imp

    if total_load > 0:
        avg_import_price = weighted_import_cost / total_load
    else:
        avg_import_price = 0.0

    net = total_load - total_pv

    if net >= 0:
        # netto import
        imp = net
        exp = 0.0
        cost_import = net * avg_import_price
        revenue_export = 0.0
    else:
        # netto export
        imp = 0.0
        exp = -net
        cost_import = 0.0
        revenue_export = exp * export_price

    total_cost = cost_import - revenue_export + float(vastrecht)

    return {
        "import": imp,
        "export": exp,
        "cost_import": cost_import,
        "revenue_export": revenue_export,
        "total_cost": total_cost,
    }


def compute_scenarios(
    load_kwh: List[float],
    pv_kwh: List[float],
    prices_dyn: List[float],
    p_enkel_imp: float,
    p_enkel_exp: float,
    p_dag: float,
    p_nacht: float,
    p_exp_dn: float,
    p_export_dyn: float,
    E: float,
    P: float,
    DoD: float,
    eta_rt: float,
    Vastrecht: float,
    capex: float = 0.0,
    opex_per_year: float = 0.0,
    horizon_years: float = 0.0,
    interest_rate: float = 0.0,
    current_tariff: str = "enkel",
) -> Dict[str, Any]:
    """
    Hoofdfunctie voor de engine.

    Parameters:
        load_kwh       : verbruiksprofiel in kWh per 15 minuten
        pv_kwh         : PV-profiel in kWh per 15 minuten
        prices_dyn     : dynamische importprijzen (€/kWh) per 15 minuten
        p_enkel_imp    : enkel tarief import
        p_enkel_exp    : enkel tarief export
        p_dag, p_nacht : dag/nacht import
        p_exp_dn       : dag/nacht export
        p_export_dyn   : dynamische exportprijs (vast of contractueel)
        E, P, DoD, eta_rt, Vastrecht : batterij- en vaste kosten-parameters
        capex, opex_per_year, horizon_years, interest_rate :
            gebruikt voor terugverdientijd (nu eenvoudige statische payback)
        current_tariff : "enkel", "dag_nacht" of "dynamisch" voor A1-scenario

    Retour:
        Een dict die direct bruikbaar is in je FastAPI-endpoint / frontend.
    """
    # sanity check lengte
    n = _ensure_same_length(load_kwh, pv_kwh, prices_dyn or load_kwh)
    load = [float(x) for x in load_kwh[:n]]
    pv = [float(x) for x in pv_kwh[:n]]
    dyn_prices = [float(x) for x in (prices_dyn[:n] if prices_dyn else [p_enkel_imp] * n)]

    # price-series per tarief
    prices_enkel = _build_import_price_series_enkel(n, p_enkel_imp)
    prices_dn = _build_import_price_series_dn(n, p_dag, p_nacht)
    prices_dyn_series = _build_import_price_series_dyn(n, dyn_prices, p_enkel_imp)

    # batterijconfig
    batt = BatteryConfig(
        capacity_kwh=float(E),
        power_kw=float(P),
        dod=max(min(float(DoD), 1.0), 0.0),
        eta_rt=max(min(float(eta_rt), 1.0), 0.01),
    )

    vastrecht = float(Vastrecht)

    # -------------------------------
    # 1. A1 – Huidige situatie met saldering
    #    Alleen voor huidig tarief
    # -------------------------------
    current_tariff = (current_tariff or "enkel").lower()
    if current_tariff == "dag_nacht":
        prices_A1 = prices_dn
        export_A1 = p_exp_dn
    elif current_tariff == "dynamisch":
        prices_A1 = prices_dyn_series
        export_A1 = p_export_dyn
    else:
        current_tariff = "enkel"
        prices_A1 = prices_enkel
        export_A1 = p_enkel_exp

    A1_res = _compute_A1_with_saldering(load, pv, prices_A1, export_A1, vastrecht)

    # -------------------------------
    # 2. B1 – Toekomst zonder saldering, GEEN batterij
    #    Voor elk tarief apart
    # -------------------------------
    B1_enkel = _simulate_no_battery(load, pv, prices_enkel, p_enkel_exp, vastrecht)
    B1_dn = _simulate_no_battery(load, pv, prices_dn, p_exp_dn, vastrecht)
    B1_dyn = _simulate_no_battery(load, pv, prices_dyn_series, p_export_dyn, vastrecht)

    # B1 voor huidig tarief (voor je grote tegels + flows)
    if current_tariff == "dag_nacht":
        B1_current = B1_dn
    elif current_tariff == "dynamisch":
        B1_current = B1_dyn
    else:
        B1_current = B1_enkel

    # -------------------------------
    # 3. C1 – Toekomst zonder saldering, MET batterij
    #    Voor elk tarief apart
    # -------------------------------
    C1_enkel = _simulate_with_battery(load, pv, prices_enkel, p_enkel_exp, vastrecht + opex_per_year, batt)
    C1_dn = _simulate_with_battery(load, pv, prices_dn, p_exp_dn, vastrecht + opex_per_year, batt)
    C1_dyn = _simulate_with_battery(load, pv, prices_dyn_series, p_export_dyn, vastrecht + opex_per_year, batt)

    if current_tariff == "dag_nacht":
        C1_current = C1_dn
    elif current_tariff == "dynamisch":
        C1_current = C1_dyn
    else:
        C1_current = C1_enkel

    # -------------------------------
    # 4. Afgeleide financiële metrics
    # -------------------------------
    A1_cost = A1_res["total_cost"]
    B1_cost = B1_current["total_cost"]
    C1_cost = C1_current["total_cost"]

    extra_cost_when_saldering_stops = B1_cost - A1_cost
    saving_by_battery = B1_cost - C1_cost
    future_vs_now_with_battery = C1_cost - A1_cost

    # eenvoudige statische terugverdientijd (zonder rente / horizon)
    payback_years = None
    annual_net_saving = saving_by_battery  # besparing t.o.v. B1 bij huidig tarief
    if capex > 0 and annual_net_saving > 0:
        payback_years = float(capex) / float(annual_net_saving)

    # -------------------------------
    # 5. Outputs in vorm die je frontend al (grotendeels) verwacht
    # -------------------------------
    result: Dict[str, Any] = {
        # grote tegels
        "A1_current": A1_cost,
        "B1_future_no_batt": B1_cost,
        "C1_future_with_batt": C1_cost,
        "extra_cost_when_saldering_stops": extra_cost_when_saldering_stops,
        "saving_by_battery": saving_by_battery,
        "future_vs_now_with_battery": future_vs_now_with_battery,
        "payback_years": payback_years,
        "flows": {
            "B1_import": B1_current["import"],
            "B1_export": B1_current["export"],
            "C1_import": C1_current["import"],
            "C1_export": C1_current["export"],
        },
        # energie-inzicht matrijzen per tarief
        "S2_enkel": {
            "import": B1_enkel["import"],
            "export": B1_enkel["export"],
            "total_cost": B1_enkel["total_cost"],
        },
        "S2_dn": {
            "import": B1_dn["import"],
            "export": B1_dn["export"],
            "total_cost": B1_dn["total_cost"],
        },
        "S2_dyn": {
            "import": B1_dyn["import"],
            "export": B1_dyn["export"],
            "total_cost": B1_dyn["total_cost"],
        },
        "S3_enkel": {
            "import": C1_enkel["import"],
            "export": C1_enkel["export"],
            "total_cost": C1_enkel["total_cost"],
        },
        "S3_dn": {
            "import": C1_dn["import"],
            "export": C1_dn["export"],
            "total_cost": C1_dn["total_cost"],
        },
        "S3_dyn": {
            "import": C1_dyn["import"],
            "export": C1_dyn["export"],
            "total_cost": C1_dyn["total_cost"],
        },
        # extra: A1–matrijs per tarief (handig voor toekomstige UI)
        "A1_per_tariff": {
            "enkel": _compute_A1_with_saldering(load, pv, prices_enkel, p_enkel_exp, vastrecht)["total_cost"],
            "dag_nacht": _compute_A1_with_saldering(load, pv, prices_dn, p_exp_dn, vastrecht)["total_cost"],
            "dynamisch": _compute_A1_with_saldering(load, pv, prices_dyn_series, p_export_dyn, vastrecht)["total_cost"],
        },
        "meta": {
            "interval_hours": INTERVAL_HOURS,
            "current_tariff": current_tariff,
        },
    }

    return result
