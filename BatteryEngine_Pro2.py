from __future__ import annotations
from dataclasses import dataclass
from typing import List, Dict, Any

# -----------------------------------------------------
# 15-minuten simulatie (0.25 uur)
# -----------------------------------------------------
INTERVAL_HOURS = 0.25


# -----------------------------------------------------
# BATTERIJ CONFIG
# -----------------------------------------------------
@dataclass
class BatteryConfig:
    capacity_kwh: float
    power_kw: float
    dod: float          # 0–1
    eta_rt: float       # round-trip efficiency, 0–1

    @property
    def usable_capacity(self) -> float:
        return max(self.capacity_kwh * self.dod, 0.0)


# -----------------------------------------------------
# HELPERS
# -----------------------------------------------------
def _ensure_same_length(a: List[float], b: List[float], c: List[float]) -> int:
    if c:
        return min(len(a), len(b), len(c))
    return min(len(a), len(b))


def _is_day_quarter(idx: int) -> bool:
    """Dag = 07:00–23:00 | Nacht = 23:00–07:00."""
    minutes = idx * 15
    minute_of_day = minutes % (24 * 60)
    return 7*60 <= minute_of_day < 23*60


# -----------------------------------------------------
# TARIEF-SERIES GENERATIE
# -----------------------------------------------------
def _build_import_price_series_enkel(n: int, price: float) -> List[float]:
    return [float(price)] * n


def _build_import_price_series_dn(n: int, p_dag: float, p_nacht: float) -> List[float]:
    out = []
    for i in range(n):
        out.append(p_dag if _is_day_quarter(i) else p_nacht)
    return out


def _build_import_price_series_dyn(n: int, dyn_prices: List[float], fallback: float) -> List[float]:
    if not dyn_prices:
        return [fallback] * n
    if len(dyn_prices) >= n:
        return [float(dyn_prices[i]) for i in range(n)]
    # cyclisch herhalen
    out = []
    m = len(dyn_prices)
    for i in range(n):
        out.append(float(dyn_prices[i % m]))
    return out


# -----------------------------------------------------
# B1 — ZONDER BATTERIJ
# -----------------------------------------------------
def _simulate_no_battery(
    load: List[float],
    pv: List[float],
    prices: List[float],
    export_price: float,
    vastrecht: float,
) -> Dict[str, float]:

    n = min(len(load), len(pv), len(prices))
    total_import = 0.0
    total_export = 0.0
    cost_import = 0.0
    revenue_export = 0.0

    for i in range(n):
        L = load[i]
        P = pv[i]
        price = prices[i]

        residual = L - P
        if residual >= 0:
            imp = residual
            exp = 0.0
        else:
            imp = 0.0
            exp = -residual

        total_import += imp
        total_export += exp
        cost_import += imp * price
        revenue_export += exp * export_price

    total_cost = cost_import - revenue_export + vastrecht

    return {
        "import": total_import,
        "export": total_export,
        "cost_import": cost_import,
        "revenue_export": revenue_export,
        "total_cost": total_cost,
    }


# -----------------------------------------------------
# C1 — MET BATTERIJ
# -----------------------------------------------------
def _simulate_with_battery(
    load: List[float],
    pv: List[float],
    prices: List[float],
    export_price: float,
    vastrecht: float,
    batt: BatteryConfig,
) -> Dict[str, float]:

    n = min(len(load), len(pv), len(prices))

    usable = batt.usable_capacity
    soc = usable * 0.5

    total_import = 0.0
    total_export = 0.0
    cost_import = 0.0
    revenue_export = 0.0

    for i in range(n):
        L = load[i]
        P = pv[i]
        price = prices[i]

        residual = L - P
        max_step = batt.power_kw * INTERVAL_HOURS

        if residual >= 0:
            # tekort -> eerst batterij
            max_from_batt = min(soc, max_step)
            needed = residual / batt.eta_rt if batt.eta_rt > 0 else 0
            take = min(max_from_batt, needed)

            soc -= take
            delivered = take * batt.eta_rt

            remaining = max(residual - delivered, 0)
            imp = remaining
            exp = 0.0

        else:
            # overschot -> batterij laden
            surplus = -residual
            space = max(usable - soc, 0)
            charge = min(min(max_step, space), surplus)

            soc += charge
            remaining_surplus = surplus - charge
            imp = 0.0
            exp = remaining_surplus

        total_import += imp
        total_export += exp
        cost_import += imp * price
        revenue_export += exp * export_price

    total_cost = cost_import - revenue_export + vastrecht

    return {
        "import": total_import,
        "export": total_export,
        "cost_import": cost_import,
        "revenue_export": revenue_export,
        "total_cost": total_cost,
    }


# -----------------------------------------------------
# A1 — MET SALDERING (JAARLIJKS)
# -----------------------------------------------------
def _compute_A1_with_saldering(
    load: List[float],
    pv: List[float],
    prices: List[float],
    export_price: float,
    vastrecht: float,
) -> Dict[str, float]:

    n = min(len(load), len(pv), len(prices))

    total_load = 0.0
    total_pv = 0.0
    weighted_cost = 0.0

    for i in range(n):
        L = load[i]
        P = pv[i]
        price = prices[i]

        total_load += L
        total_pv += P
        weighted_cost += L * price

    avg_price = (weighted_cost / total_load) if total_load > 0 else 0
    net = total_load - total_pv

    if net >= 0:
        # netto import
        cost = net * avg_price
        revenue = 0.0
        imp = net
        exp = 0.0
    else:
        # netto export
        cost = 0.0
        exp = -net
        revenue = exp * export_price
        imp = 0.0

    total_cost = cost - revenue + vastrecht

    return {
        "import": imp,
        "export": exp,
        "cost_import": cost,
        "revenue_export": revenue,
        "total_cost": total_cost,
    }


# -----------------------------------------------------
# HOOFDFUNCTIE V2 (DIT IS DE FUNCTIE DIE FASTAPI AANROEPT)
# -----------------------------------------------------
def compute_scenarios_v2(
    load,
    pv,
    prices_dyn,

    tariff_enkel,
    tariff_dn,
    tariff_dyn,

    battery,
    vastrecht,
):
    # --- normalize ---
    n = _ensure_same_length(load, pv, prices_dyn or load)
    load = [float(x) for x in load[:n]]
    pv = [float(x) for x in pv[:n]]
    dyn_prices = [float(x) for x in (prices_dyn[:n] if prices_dyn else [tariff_enkel["imp"]] * n)]

    # --- price series ---
    prices_enkel = _build_import_price_series_enkel(n, tariff_enkel["imp"])
    prices_dn = _build_import_price_series_dn(n, tariff_dn["dag"], tariff_dn["nacht"])
    prices_dyn_series = _build_import_price_series_dyn(n, dyn_prices, tariff_enkel["imp"])

    # --- battery config ---
    batt = BatteryConfig(
        capacity_kwh=battery["E_cap"],
        power_kw=battery["P_max"],
        dod=battery["dod"],
        eta_rt=battery["eta"],
    )

    vast = float(vastrecht)

    # -----------------------------------------------------
    # A1: alleen huidig tarief
    # -----------------------------------------------------
    # current_tariff wordt op frontend meegestuurd → zelf bepalen:
    curr = battery.get("current_tariff", "enkel").lower()

    if curr == "dag_nacht":
        A1 = _compute_A1_with_saldering(load, pv, prices_dn, tariff_dn["exp"], vast)
    elif curr == "dynamisch":
        A1 = _compute_A1_with_saldering(load, pv, prices_dyn_series, tariff_dyn["price_export"], vast)
    else:
        curr = "enkel"
        A1 = _compute_A1_with_saldering(load, pv, prices_enkel, tariff_enkel["exp"], vast)

    # -----------------------------------------------------
    # B1 — zonder batterij
    # -----------------------------------------------------
    B1_enkel = _simulate_no_battery(load, pv, prices_enkel, tariff_enkel["exp"], vast)
    B1_dn = _simulate_no_battery(load, pv, prices_dn, tariff_dn["exp"], vast)
    B1_dyn = _simulate_no_battery(load, pv, prices_dyn_series, tariff_dyn["price_export"], vast)

    B1_current = {"enkel": B1_enkel, "dag_nacht": B1_dn, "dynamisch": B1_dyn}[curr]

    # -----------------------------------------------------
    # C1 — met batterij
    # -----------------------------------------------------
    C1_enkel = _simulate_with_battery(load, pv, prices_enkel, tariff_enkel["exp"], vast, batt)
    C1_dn = _simulate_with_battery(load, pv, prices_dn, tariff_dn["exp"], vast, batt)
    C1_dyn = _simulate_with_battery(load, pv, prices_dyn_series, tariff_dyn["price_export"], vast, batt)

    C1_current = {"enkel": C1_enkel, "dag_nacht": C1_dn, "dynamisch": C1_dyn}[curr]

    # -----------------------------------------------------
    # financiële metrics
    # -----------------------------------------------------
    A_cost = A1["total_cost"]
    B_cost = B1_current["total_cost"]
    C_cost = C1_current["total_cost"]

    extra_cost = B_cost - A_cost
    saving_batt = B_cost - C_cost
    future_vs_now = C_cost - A_cost

    # -----------------------------------------------------
    # RETURN-STRUCTUUR (super clean!)
    # -----------------------------------------------------
    return {
        "A1_current": A_cost,
        "B1_future_no_batt": B_cost,
        "C1_future_with_batt": C_cost,

        "extra_cost_when_saldering_stops": extra_cost,
        "saving_by_battery": saving_batt,
        "future_vs_now_with_battery": future_vs_now,

        "flows": {
            "B1_import": B1_current["import"],
            "B1_export": B1_current["export"],
            "C1_import": C1_current["import"],
            "C1_export": C1_current["export"],
        },

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

        "meta": {
            "interval": INTERVAL_HOURS,
            "current_tariff": curr,
        },
    }
