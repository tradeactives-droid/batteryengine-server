# battery_engine_pro3/types.py

from __future__ import annotations
from dataclasses import dataclass
from typing import List, Optional


# ============================================================
# Timeseries (load, PV, prices)
# ============================================================

@dataclass
class TimeSeries:
    timestamps: List            # datetime stamps (list)
    values: List[float]         # kWh or prices
    dt_hours: float             # resolution in hours (1.0 or 0.25)


# ============================================================
# ScenarioResult (output per scenario per tarief)
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
# ROI Result
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
# Peak Shaving Info (BE-only)
# ============================================================

@dataclass
class PeakInfo:
    monthly_before: List[float]   # 12 waardes, kW
    monthly_after: List[float]    # 12 waardes, kW

    def to_dict(self):
        return {
            "monthly_before": self.monthly_before,
            "monthly_after": self.monthly_after,
        }


# ============================================================
# Tariff Configuration (input voor CostEngine)
# ============================================================

@dataclass
class TariffConfig:
    # Land
    country: str                 # "NL" of "BE"

    # Huidig tarief van de gebruiker
    current_tariff: str          # "enkel" / "dag_nacht" / "dynamisch"

    # Vastrecht / vaste kosten per jaar
    vastrecht_year: float

    # Energieprijzen — enkel tarief
    p_enkel_imp: float           # €/kWh import
    p_enkel_exp: float           # €/kWh export

    # Energieprijzen — dag/nacht
    p_dag: float                 # €/kWh import dag
    p_nacht: float               # €/kWh import nacht
    p_exp_dn: float              # €/kWh export bij dag/nacht tarief

    # Dynamische tarieven
    p_export_dyn: float          # exportvergoeding bij dynamisch
    dynamic_prices: Optional[List[float]]  # importprijs per timestep; None = niet gebruikt

    # Terugleverkosten (NL-only)
    feedin_monthly_cost: float         # €/maand
    feedin_cost_per_kwh: float         # (alternatief – wordt zelden gebruikt)
    feedin_free_kwh: float
    feedin_price_after_free: float

    # Omvormerkosten
    inverter_power_kw: float           # kW
    inverter_cost_per_kw: float        # €/kW/jaar

    # Capaciteitstarief (BE)
    capacity_tariff_kw: float          # €/kW/jaar


# ============================================================
# Battery Configuration (input voor batterijmodellen)
# ============================================================

@dataclass
class BatteryConfig:
    # Capaciteit & vermogen
    E: float              # kWh, nominale capaciteit
    P: float              # kW, maximaal laad/ontlaadvermogen

    # Depth of Discharge en round-trip efficiency
    DoD: float            # fractie 0–1
    eta_rt: float         # round-trip efficiency (0–1)

    # Financieel
    investment_eur: float  # totale aanschafkosten €
    degradation: float     # jaarlijkse degradatie (0–1) — 0.02 = 2%

    def to_dict(self):
        return {
            "E": self.E,
            "P": self.P,
            "DoD": self.DoD,
            "eta_rt": self.eta_rt,
            "investment_eur": self.investment_eur,
            "degradation": self.degradation,
        }


# Alias types (voor duidelijkheid)
TariffCode = str
CountryCode = str
