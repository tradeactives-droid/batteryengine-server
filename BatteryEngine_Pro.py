# ============================================================
# BatteryEngine_Pro.py — Kwartierdata + A1/B1/C1 scenario's
# ============================================================

def compute_scenarios(
    load,          # array quart-hour kWh
    pv,            # array quart-hour kWh
    prices_dyn,
    p_enkel_imp,
    p_enkel_exp,
    p_dag,
    p_nacht,
    p_exp_dn,
    E,             # kWh capacity
    P,             # kW power
    DoD,           # 0–1
    eta_rt,        # 0–1
    vastrecht
):

    # ============================
    # INTERVAL CONSTANT
    # ============================
    interval_hours = 0.25           # kwartierdata
    max_power = P * interval_hours  # maximale energie per kwartier

    batt_cap = E * DoD
    eta = eta_rt
    batt = 0

    n = len(load)

    # ============================================================
    # A1 — HUIDIGE SITUATIE MET SALDERING
    # ============================================================
    net = [load[i] - pv[i] for i in range(n)]
    saldering_balance = sum(net)

    if saldering_balance >= 0:
        A1_cost = saldering_balance * p_enkel_imp
    else:
        A1_cost = saldering_balance * p_enkel_exp

    A1_cost += vastrecht

    # ============================================================
    # B1 — TOEKOMST ZONDER SALDERING, GEEN BATTERIJ
    # ============================================================
    imp_B1 = 0
    exp_B1 = 0

    for i in range(n):
        if load[i] >= pv[i]:
            imp_B1 += (load[i] - pv[i])
        else:
            exp_B1 += (pv[i] - load[i])

    B1_cost = imp_B1 * p_enkel_imp - exp_B1 * p_enkel_exp + vastrecht

    # ============================================================
    # C1 — TOEKOMST ZONDER SALDERING, MET BATTERIJ
    # ============================================================
    batt = 0
    imp_C1 = 0
    exp_C1 = 0

    for i in range(n):

        # DIRECT CONSUMPTION
        direct = min(load[i], pv[i])
        remaining_load = load[i] - direct
        surplus_pv = pv[i] - direct

        # LADEN MET PV
        if surplus_pv > 0:
            charge = min(max_power, surplus_pv, batt_cap - batt)
            batt += charge * eta            # laadverlies
            surplus_pv -= charge
            exp_C1 += surplus_pv            # resterende PV → export

        # ONTLADEN BIJ LOAD
        if remaining_load > 0:
            discharge = min(max_power, remaining_load, batt)
            batt -= discharge
            remaining_load -= discharge

        # REST LOAD → IMPORT
        imp_C1 += remaining_load

    C1_cost = imp_C1 * p_enkel_imp - exp_C1 * p_enkel_exp + vastrecht

    # ============================================================
    # RESULT OBJECT
    # ============================================================
    return {
        "A1_current": A1_cost,
        "B1_future_no_batt": B1_cost,
        "C1_future_with_batt": C1_cost,

        "extra_cost_when_saldering_stops": B1_cost - A1_cost,
        "saving_by_battery": B1_cost - C1_cost,
        "future_vs_now_with_battery": C1_cost - A1_cost,

        "flows": {
            "B1_import": imp_B1,
            "B1_export": exp_B1,
            "C1_import": imp_C1,
            "C1_export": exp_C1
        }
    }
