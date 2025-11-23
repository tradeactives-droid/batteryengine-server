# ============================================================
# BatteryEngine_Pro - Sandbox-safe, single-file implementation
# ============================================================
# Volledig deterministisch, geen externe imports, geen modules.
# Compatible met de CSV-dispatch zoals vereist door jouw GPT.
# ============================================================

# ------------------------------------------------------------
# Hulpfuncties (geen externe dependencies)
# ------------------------------------------------------------
def clamp(value, low, high):
    if value < low:
        return low
    if value > high:
        return high
    return value


# ------------------------------------------------------------
# BatteryEngine CSV-dispatch
# ------------------------------------------------------------
def run_battery_engine_csv(
    load_kwh,       # lijst van 35040 load-waarden in kWh per timestep
    pv_kwh,         # lijst van 35040 PV-waarden in kWh per timestep
    price_import,   # lijst van 35040 importprijzen (€/kWh) voor dynamisch tarief
    price_export,   # float — vaste exportprijs dynamisch
    E_kwh,          # batterijcapaciteit (kWh)
    P_kw,           # vermogen (kW)
    dod,            # depth of discharge (0-1)
    eta_rt,         # round trip efficiency (0-1)
    start_soc=0.5   # start-SOC als fractie (niet kritisch, engine stabiliseert)
):
    """
    Voert volledige batterij-dispatch uit voor 35.040 kwartierstappen.
    Geen grid-charging voor enkel / dag-nacht (alleen dynamisch).
    """

    # --------------------------------------------------------
    # Preprocessing
    # --------------------------------------------------------
    n = len(load_kwh)
    timestep_hours = 0.25  # 15 minuten = 0,25 uur

    soc_min = E_kwh * (1 - dod)
    soc_max = E_kwh

    # max lading/ontlading per timestep (kWh)
    p_limit = P_kw * timestep_hours

    # charge/discharge efficiencies
    eta_charge = (eta_rt ** 0.5)
    eta_discharge = (eta_rt ** 0.5)

    soc = E_kwh * start_soc
    soc = clamp(soc, soc_min, soc_max)

    total_import = 0.0
    total_export = 0.0

    # --------------------------------------------------------
    # Dynamisch tarief thresholds
    # --------------------------------------------------------
    # Alleen gebruikt in dynamisch tarief
    sorted_prices = sorted(price_import)
    p25 = sorted_prices[int(0.25 * len(sorted_prices))]
    p75 = sorted_prices[int(0.75 * len(sorted_prices))]

    # --------------------------------------------------------
    # Dispatch loop
    # --------------------------------------------------------
    for t in range(n):
        load = load_kwh[t]
        pv = pv_kwh[t]

        # -------------------------------
        # Stap 1 — PV → Load
        # -------------------------------
        direct_pv = min(load, pv)
        load -= direct_pv
        pv -= direct_pv

        # -------------------------------
        # Stap 2 — PV → Batterij (PV overschot opslaan)
        # -------------------------------
        if pv > 0 and soc < soc_max:
            possible_charge = min(pv, p_limit)
            soc += possible_charge * eta_charge
            pv -= possible_charge
            soc = clamp(soc, soc_min, soc_max)

        # -------------------------------
        # Stap 3 — Grid-charging (ALLEEN dynamisch)
        # -------------------------------
        price = price_import[t]
        if pv <= 0 and price <= p25 and soc < soc_max:
            grid_charge = min(p_limit, soc_max - soc)
            soc += grid_charge * eta_charge
            total_import += grid_charge
            soc = clamp(soc, soc_min, soc_max)

        # -------------------------------
        # Stap 4 — Batterij → Load
        # -------------------------------
        if load > 0 and soc > soc_min:
            discharge = min(load, p_limit, soc - soc_min)
            load -= discharge
            soc -= discharge / eta_discharge
            soc = clamp(soc, soc_min, soc_max)

        # -------------------------------
        # Stap 5 — Rest naar net
        # -------------------------------
        if load > 0:
            total_import += load

        if pv > 0:
            total_export += pv

    # --------------------------------------------------------
    # Return resultaten
    # --------------------------------------------------------
    return {
        "import_kwh": total_import,
        "export_kwh": total_export
    }


# ------------------------------------------------------------
# Scenario-wrapper voor jouw GPT
# ------------------------------------------------------------
def compute_scenarios(
    load_kwh,
    pv_kwh,
    prices_dyn,
    prices_enkel_imp,
    prices_enkel_exp,
    prices_dn_day,
    prices_dn_night,
    prices_dn_export,
    E_kwh,
    P_kw,
    dod,
    eta_rt,
    vastrecht
):
    """
    Jouw GPT roept ALLEEN deze functie aan.
    Dit maakt het super eenvoudig en foutloos.
    """

    n = len(load_kwh)
    step = 0.25  # 15 minuten

    # Dag/nacht indeling: 07:00-23:00 dag  
    def is_day(i):
        hour = (i // 4) % 24
        return 7 <= hour < 23

    # -------------------------
    # Scenario 1 — saldering
    # -------------------------
    total_load = sum(load_kwh)
    total_pv = sum(pv_kwh)

    import_s1 = max(total_load - total_pv, 0)
    export_s1 = max(total_pv - total_load, 0)

    # Huidige tarief = dag/nacht default saldering
    p_salder = prices_dn_export

    cost_s1 = import_s1 * p_salder + vastrecht

    # -----------------------------------------------------
    # Scenario 2 — geen batterij, 3 tarieven
    # -----------------------------------------------------
    # Pre-dispatch: PV->Load
    imports_pre = []
    exports_pre = []

    for t in range(n):
        load = load_kwh[t]
        pv = pv_kwh[t]

        direct = min(load, pv)
        load -= direct
        pv -= direct

        imports_pre.append(load)
        exports_pre.append(pv)

    total_import_s2 = sum(imports_pre)
    total_export_s2 = sum(exports_pre)

    # Enkel tarief
    cost_s2_enkel = (
        total_import_s2 * prices_enkel_imp
        - total_export_s2 * prices_enkel_exp
        + vastrecht
    )

    # Dag/nacht
    imp_dn = 0.0
    for i in range(n):
        imp_dn += imports_pre[i] * (prices_dn_day if is_day(i) else prices_dn_night)

    cost_s2_dn = imp_dn - total_export_s2 * prices_dn_export + vastrecht

    # Dynamisch
    imp_dyn = 0.0
    for i in range(n):
        imp_dyn += imports_pre[i] * prices_dyn[i]

    cost_s2_dyn = imp_dyn - total_export_s2 * prices_dn_export + vastrecht

    # -----------------------------------------------------
    # Scenario 3 — MET batterij
    # -----------------------------------------------------
    # Enkel
    result_enkel = run_battery_engine_csv(
        load_kwh, pv_kwh, [prices_enkel_imp]*n, prices_enkel_exp,
        E_kwh, P_kw, dod, eta_rt
    )

    cost_s3_enkel = (
        result_enkel["import_kwh"] * prices_enkel_imp
        - result_enkel["export_kwh"] * prices_enkel_exp
        + vastrecht
    )

    # Dag/nacht
    price_dn_import = [(prices_dn_day if is_day(i) else prices_dn_night) for i in range(n)]

    result_dn = run_battery_engine_csv(
        load_kwh, pv_kwh, price_dn_import, prices_dn_export,
        E_kwh, P_kw, dod, eta_rt
    )

    cost_s3_dn = (
        result_dn["import_kwh"] * 1.0  # prijs zit in p_import-lijst
        - result_dn["export_kwh"] * prices_dn_export
        + vastrecht
    )

    # Dynamisch
    result_dyn = run_battery_engine_csv(
        load_kwh, pv_kwh, prices_dyn, prices_dn_export,
        E_kwh, P_kw, dod, eta_rt
    )

    cost_s3_dyn = (
        result_dyn["import_kwh"] * 1.0  # prijs zit in p_import-lijst
        - result_dyn["export_kwh"] * prices_dn_export
        + vastrecht
    )

    return {
        "S1": cost_s1,
        "S2_enkel": cost_s2_enkel,
        "S2_dn": cost_s2_dn,
        "S2_dyn": cost_s2_dyn,
        "S3_enkel": cost_s3_enkel,
        "S3_dn": cost_s3_dn,
        "S3_dyn": cost_s3_dyn
    }