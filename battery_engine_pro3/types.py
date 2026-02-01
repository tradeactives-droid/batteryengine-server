# battery_engine_pro3/types.py

from __future__ import annotations
from dataclasses import dataclass
from typing import List, Optional


# ============================================================
# TimeSeries (uniform voor load, PV en dynamische prijzen)
# ============================================================

@dataclass
class TimeSeries:
    timestamps: List           # list[datetime]
    values: List[float]        # kWh (load/pv) of €/kWh (prices)
    dt_hours: float            # 1.0 of 0.25


# ============================================================
# ScenarioResult — output per tarief, per scenario
# ============================================================

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


# ============================================================
# ROI Result — jaarlijkse besparing, payback & ROI
# ============================================================

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


# ============================================================
# Peak Shaving Info — alleen België
# ============================================================

@dataclass
class PeakInfo:
    monthly_before: List[float]   # 12 waarden (kW)
    monthly_after: List[float]    # 12 waarden (kW)

    def to_dict(self):
        return {
            "monthly_before": self.monthly_before,
            "monthly_after": self.monthly_after,
        }


# ============================================================
# Tariff Configuration — volledig inputmodel voor CostEngine
# ============================================================

from dataclasses import dataclass
from typing import Optional, List


@dataclass
class TariffConfig:
    # =========================
    # Context
    # =========================
    country: str                      # "NL" / "BE"
    current_tariff: str               # "enkel" / "dag_nacht" / "dynamisch"

    # =========================
    # Vaste kosten
    # =========================
    vastrecht_year: float

    # =========================
    # Enkel tarief
    # =========================
    p_enkel_imp: float
    p_enkel_exp: float

    # =========================
    # Dag / Nacht
    # =========================
    p_dag: float
    p_nacht: float
    p_exp_dn: float

    # =========================
    # Dynamisch
    # =========================
    p_export_dyn: float
    dynamic_prices: Optional[List[float]]

    # =========================
    # Terugleverkosten
    # =========================
    feedin_monthly_cost: float
    feedin_cost_per_kwh: float
    feedin_free_kwh: float
    feedin_price_after_free: float

    # =========================
    # Omvormer
    # =========================
    inverter_power_kw: float
    inverter_cost_per_kw: float

    # =========================
    # Capaciteitstarief (BE)
    # =========================
    capacity_tariff_kw: float

    # =========================
    # ⭐ Saldering (ALTIJD ALS LAATSTE)
    # =========================
    allow_grid_charge: bool = False
    saldering: bool = True


# ============================================================
# Battery Configuration — input voor BatteryModel & ROI
# ============================================================

@dataclass
class BatteryConfig:
    # Capaciteit en vermogen
    E: float
    P: float

    # DoD en rendement
    DoD: float
    eta_rt: float

    # Degradatie
    degradation_per_year: float  # bv 0.02 = 2% per jaar

    # Financieel
    investment_eur: float

    # Levensduur (default = 15 jaar)
    lifetime_years: int = 15

    def to_dict(self):
        return {
            "E": self.E,
            "P": self.P,
            "DoD": self.DoD,
            "eta_rt": self.eta_rt,
            "degradation_per_year": self.degradation_per_year,
            "investment_eur": self.investment_eur,
        }


# ============================================================
# Aliases voor duidelijkheid
# ============================================================

TariffCode = str
CountryCode = str
