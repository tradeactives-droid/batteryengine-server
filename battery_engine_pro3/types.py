# battery_engine_pro3/types.py

from __future__ import annotations
from dataclasses import dataclass
from typing import List, Optional


# ========================================
# Core Timeseries Model
# ========================================
@dataclass
class TimeSeries:
    timestamps: List
    values: List[float]
    dt_hours: float


# ========================================
# ScenarioResult
# ========================================
@dataclass
class ScenarioResult:
    import_kwh: float
    export_kwh: float
    total_cost_eur: float

    def to_dict(self):
        return {
            "import_kwh": self.import_kwh,
            "export_kwh": self.export_kwh,
            "total_cost_eur": self.total_cost_eur,
        }


# ========================================
# ROI Result
# ========================================
@dataclass
class ROIResult:
    yearly_saving_eur: float
    payback_years: Optional[int]
    roi_percent: float

    def to_dict(self):
        return {
            "yearly_saving_eur": self.yearly_saving_eur,
            "payback_years": self.payback_years,
            "roi_percent": self.roi_percent,
        }


# ========================================
# Peak Info
# ========================================
@dataclass
class PeakInfo:
    monthly_before: List[float]
    monthly_after: List[float]

    def to_dict(self):
        return {
            "monthly_before": self.monthly_before,
            "monthly_after": self.monthly_after,
        }


# ========================================
# Tariff Config
# ========================================
@dataclass
class TariffConfig:
    country: str
    current_tariff: str

    # Prices
    p_enkel_imp: float
    p_enkel_exp: float

    p_dag: float
    p_nacht: float
    p_exp_dn: float

    p_export_dyn: float
    dynamic_prices: Optional[List[float]]

    # Fixed fees
    vastrecht_year: float
    feedin_monthly_cost: float
    feedin_cost_per_kwh: float
    feedin_free_kwh: float
    feedin_price_after_free: float

    # Inverter
    inverter_power_kw: float
    inverter_cost_per_kw: float

    # BE capacity tariff
    capacity_tariff_kw: float


# ========================================
# BatteryConfig
# ========================================
@dataclass
class BatteryConfig:
    E: float
    P: float
    DoD: float
    eta_rt: float
    investment_eur: float
    degradation: float

    def to_dict(self):
        return {
            "E": self.E,
            "P": self.P,
            "DoD": self.DoD,
            "eta_rt": self.eta_rt,
            "investment_eur": self.investment_eur,
            "degradation": self.degradation,
        }


TariffCode = str
CountryCode = str
