from dataclasses import dataclass
from typing import List, Optional


@dataclass
class TimeSeries:
    timestamps: List
    values: List[float]
    dt_hours: float


@dataclass
class ScenarioResult:
    import_kwh: float
    export_kwh: float
    total_cost_eur: float


@dataclass
class ROIResult:
    yearly_saving_eur: float
    payback_years: Optional[int]
    roi_percent: float


@dataclass
class PeakInfo:
    monthly_before: List[float]
    monthly_after: List[float]


@dataclass
class TariffConfig:
    country: str
    current_tariff: str
    vastrecht_year: float
    p_enkel_imp: float
    p_enkel_exp: float
    p_dag: float
    p_nacht: float
    p_exp_dn: float
    p_export_dyn: float
    dynamic_prices: Optional[List[float]]
    feedin_monthly_cost: float
    feedin_cost_per_kwh: float
    feedin_free_kwh: float
    feedin_price_after_free: float
    inverter_power_kw: float
    inverter_cost_per_kw: float
    capacity_tariff_kw: float


@dataclass
class BatteryConfig:
    E: float
    P: float
    DoD: float
    eta_rt: float
    investment_eur: float
    degradation: float
