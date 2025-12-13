# battery_engine_pro3/engine.py

from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, Any

from .types import (
    TimeSeries,
    TariffConfig,
    BatteryConfig,
)
from .scenario_runner import ScenarioRunner, FullScenarioOutput


@dataclass
class ComputeV3Input:
    """Structuur die 1-op-1 lijkt op je FastAPI request body."""
    load_kwh: list[float]
    pv_kwh: list[float]
    prices_dyn: list[float]

    # Tarieven
    p_enkel_imp: float
    p_enkel_exp: float
    p_dag: float
    p_nacht: float
    p_exp_dn: float
    p_export_dyn: float

    # Batterij
    E: float
    P: float
    DoD: float
    eta_rt: float
    vastrecht: float
    battery_cost: float
    battery_degradation: float

    # Feed-in / omvormer
    feedin_monthly_cost: float
    feedin_cost_per_kwh: float
    feedin_free_kwh: float
    feedin_price_after_free: float
    inverter_power_kw: float
    inverter_cost_per_kw_year: float
    capacity_tariff_kw_year: float

    current_tariff: str
    country: str


class BatteryEnginePro3:
    """
    Publieke interface van de engine.
    Wordt aangeroepen door FastAPI in main.py (endpoint /compute_v3).
    """

    @staticmethod
    def compute(input_data: ComputeV3Input) -> Dict[str, Any]:
        """
        Hoofdfunctie voor BatteryEngine Pro 3.
        Bouwt alle modellen, voert ScenarioRunner.run() uit en geeft API-ready output terug.
        """

        from datetime import datetime, timedelta
        from .types import TimeSeries, TariffConfig, BatteryConfig
        from .scenario_runner import ScenarioRunner

        # ------------------------------------------------------
        # 1) BASIC VALIDATION
        # ------------------------------------------------------
        if not input_data.load_kwh or not input_data.pv_kwh:
            return {"error": "LOAD_OR_PV_EMPTY"}

        n = min(len(input_data.load_kwh), len(input_data.pv_kwh))
        load_vals = input_data.load_kwh[:n]
        pv_vals = input_data.pv_kwh[:n]

        # ------------------------------------------------------
        # 2) DETECT RESOLUTION (1 uur of 0.25 uur)
        # ------------------------------------------------------
        if n >= 30000:
            dt = 0.25
        else:
            dt = 1.0

        start = datetime(2025, 1, 1)
        timestamps = [start + timedelta(hours=dt * i) for i in range(n)]

        load_ts = TimeSeries(timestamps, load_vals, dt)
        pv_ts = TimeSeries(timestamps, pv_vals, dt)

        # Dynamische prijzen
        dyn_prices = (
            input_data.prices_dyn
            if input_data.prices_dyn and len(input_data.prices_dyn) == n
            else None
        )

        # ------------------------------------------------------
        # 3) Tariefconfig
        # ------------------------------------------------------
        tariff_cfg = TariffConfig(
            country=input_data.country,
            current_tariff=input_data.current_tariff,

            vastrecht_year=input_data.vastrecht,

            p_enkel_imp=input_data.p_enkel_imp,
            p_enkel_exp=input_data.p_enkel_exp,

            p_dag=input_data.p_dag,
            p_nacht=input_data.p_nacht,
            p_exp_dn=input_data.p_exp_dn,

            p_export_dyn=input_data.p_export_dyn,
            dynamic_prices=dyn_prices,

            feedin_monthly_cost=input_data.feedin_monthly_cost,
            feedin_cost_per_kwh=input_data.feedin_cost_per_kwh,
            feedin_free_kwh=input_data.feedin_free_kwh,
            feedin_price_after_free=input_data.feedin_price_after_free,

            inverter_power_kw=input_data.inverter_power_kw,
            inverter_cost_per_kw=input_data.inverter_cost_per_kw_year,

            capacity_tariff_kw=input_data.capacity_tariff_kw_year,
        )

        # ------------------------------------------------------
        # 4) Batterijconfig
        # ------------------------------------------------------
        batt_cfg = BatteryConfig(
            E=input_data.E,
            P=input_data.P,
            DoD=input_data.DoD,
            eta_rt=input_data.eta_rt,
            investment_eur=input_data.battery_cost,
            degradation_per_year=input_data.battery_degradation,
        )

        # ------------------------------------------------------
        # 5) UITVOEREN SCENARIOENGINE
        # ------------------------------------------------------
        runner = ScenarioRunner(load_ts, pv_ts, tariff_cfg, batt_cfg)
        result = runner.run()     # dit is al API-ready (dicts!)

        # ------------------------------------------------------
        # 6) DIRECT TERUG NAAR API
        # ------------------------------------------------------
        return result
