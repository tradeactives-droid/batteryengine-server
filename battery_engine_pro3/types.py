# battery_engine_pro3/types.py

from __future__ import annotations
from dataclasses import dataclass
from typing import List, Literal, Optional, Dict


CountryCode = Literal["NL", "BE"]
TariffCode = Literal["enkel", "dag_nacht", "dynamisch"]


@dataclass
class TimeSeries:
    """Generieke tijdreeks in kWh per timestep."""
    values: List[float]
    dt_hours: float  # 0.25 of 1.0 bijvoorbeeld


@dataclass
class TariffConfig:
    """Inputconfiguratie voor tarieven."""
    country: CountryCode
    current_tariff: TariffCode

    # Enkel
    p_enkel_imp: float
    p_enkel_exp: float

    # Dag/nacht
    p_dag: float
    p_nacht: float
    p_exp_dn: float

    # Dynamisch
    p_export_dyn: float
    dynamic_prices: Optional[List[float]] = None

    # Terugleverkosten / omvormer
    feedin_monthly_cost: float = 0.0
    feedin_cost_per_kwh: float = 0.0
    feedin_free_kwh: float = 0.0
    feedin_price_after_free: float = 0.0

    inverter_power_kw: float = 0.0
    inverter_cost_per_kw_year: float = 0.0

    capacity_tariff_kw_year: float = 0.0
    vastrecht_year: float = 0.0


@dataclass
class BatteryConfig:
    """Inputconfiguratie voor de batterij."""
    capacity_kwh: float
    power_kw: float
    dod: float           # 0–1
    roundtrip_eff: float # 0–1
    cost_eur: float
    degradation_per_year: float  # 0–1


@dataclass
class ScenarioResult:
    """Resultaat van één scenario (A1, B1 of C1)."""
    import_kwh: float
    export_kwh: float
    total_cost_eur: float


@dataclass
class PeakInfo:
    """Info over maandpieken."""
    monthly_peaks_kw_no_batt: List[float]
    monthly_peaks_kw_with_batt: List[float]
    capacity_saving_year_eur: float


@dataclass
class ROIResult:
    """Resultaat van ROI / terugverdientijd berekening."""
    yearly_saving_eur: float
    payback_years: Optional[float]
    roi_percent: float
