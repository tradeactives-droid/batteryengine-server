# battery_engine_pro3/scenario_runner.py

from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, Optional

from .types import (
    TimeSeries,
    TariffConfig,
    BatteryConfig,
    ScenarioResult,
    ROIResult,
    PeakInfo,
    TariffCode,
)
from .battery_model import BatteryModel
from .battery_simulator import BatterySimulator
from .cost_engine import CostEngine
from .peak_optimizer import PeakOptimizer


@dataclass
class FullScenarioOutput:
    """
    Volledige output van BatteryEngine Pro 3:

    - A1: huidige situatie (zonder batterij, huidig tarief)
    - B1: toekomst zonder batterij (per tarief)
    - C1: toekomst met batterij (per tarief)
    - roi: ROI-resultaten (besparing, terugverdientijd, ROI%)
    - peaks: peak shaving info (alleen relevant voor BE)
    """
    A1: ScenarioResult
    B1: Dict[TariffCode, ScenarioResult]
    C1: Dict[TariffCode, ScenarioResult]
    roi: ROIResult
    peaks: PeakInfo


class ScenarioRunner:
    """
    Orkestreert alle scenario’s (A1, B1, C1, ROI, peaks).
    """

    def __init__(
        self,
        load: TimeSeries,
        pv: TimeSeries,
        tariff_cfg: TariffConfig,
        batt_cfg: Optional[BatteryConfig] = None
    ) -> None:
        self.load = load
        self.pv = pv
        self.tariff_cfg = tariff_cfg
        self.batt_cfg = batt_cfg

    def _build_battery_model(self) -> BatteryModel:
        """
        Helper: bouwt een BatteryModel op basis van BatteryConfig.
        """
        if self.batt_cfg is None:
            raise ValueError("BatteryConfig is required for battery scenarios")

        cfg = self.batt_cfg
        return BatteryModel(
            E_cap=cfg.E,
            P_max=cfg.P,
            dod=cfg.DoD,
            eta=cfg.eta_rt
        )

    def run(self) -> FullScenarioOutput:
        """
        Voert alle scenario's uit:
        - A1 (huidig tarief, geen batterij)
        - B1 (toekomst zonder batterij, alle tarieven)
        - C1 (met batterij: NL = normaal, BE = peak shaving)
        - ROI (15 jaar, incl. degradatie)
        - PeakInfo (alleen BE)
        """

        country = self.tariff_cfg.country   # "NL" of "BE"
        current_tariff = self.tariff_cfg.current_tariff  # "enkel" / "dag_nacht" / "dynamisch"

        cost_engine = CostEngine(self.tariff_cfg)

        # ----------------------------------------------------
        # 1. Scenario A1 — huidige situatie (geen batterij)
        # ----------------------------------------------------
        sim_no = BatterySimulator(self.load, self.pv, battery=None)
        A1_sim = sim_no.simulate_no_battery()

        A1_cost = cost_engine.compute_cost(
            A1_sim.import_profile,
            A1_sim.export_profile,
            current_tariff
        )

        # ----------------------------------------------------
        # 2. Scenario B1 — toekomst zonder batterij (alle tarieven)
        # ----------------------------------------------------
        B1_sim = sim_no.simulate_no_battery()

        B1_costs: Dict[TariffCode, ScenarioResult] = {
            "enkel":     cost_engine.compute_cost(B1_sim.import_profile, B1_sim.export_profile, "enkel"),
            "dag_nacht": cost_engine.compute_cost(B1_sim.import_profile, B1_sim.export_profile, "dag_nacht"),
            "dynamisch": cost_engine.compute_cost(B1_sim.import_profile, B1_sim.export_profile, "dynamisch"),
        }

        baseline_cost = B1_costs[current_tariff].total_cost_eur

        # ----------------------------------------------------
        # 3. Scenario C1 — toekomst met batterij
        # ----------------------------------------------------
        if self.batt_cfg is None:
            # Geen batterijconfig → C1 = gelijk aan B1
            C1_costs = B1_costs.copy()
            peak_info = PeakInfo(monthly_before=[], monthly_after=[])
        else:
            battery_model = self._build_battery_model()

            if country == "BE":
                # 3A. BE → Peak Shaving

                # Baseline maandpieken (zonder batterij)
                baseline_peaks = PeakOptimizer.compute_monthly_peaks(self.load, self.pv)

                # Targets (bijv. 15% reductie)
                monthly_targets = PeakOptimizer.compute_monthly_targets(baseline_peaks, reduction_factor=0.85)

                # Simuleer batterij MET peak shaving
                new_peaks, C1_import, C1_export, C1_soc = PeakOptimizer.simulate_with_peak_shaving(
                    self.load,
                    self.pv,
                    battery_model,
                    monthly_targets
                )

                # Kosten met batterij (alle tarieven)
                C1_costs = {
                    "enkel":     cost_engine.compute_cost(C1_import, C1_export, "enkel"),
                    "dag_nacht": cost_engine.compute_cost(C1_import, C1_export, "dag_nacht"),
                    "dynamisch": cost_engine.compute_cost(C1_import, C1_export, "dynamisch"),
                }

                peak_info = PeakInfo(
                    monthly_before=baseline_peaks,
                    monthly_after=new_peaks
                )

            else:
                # 3B. NL → normale batterijsimulatie (geen peak shaving)
                sim_batt = BatterySimulator(self.load, self.pv, battery_model)
                C1_sim = sim_batt.simulate_with_battery()

                C1_costs = {
                    "enkel":     cost_engine.compute_cost(C1_sim.import_profile, C1_sim.export_profile, "enkel"),
                    "dag_nacht": cost_engine.compute_cost(C1_sim.import_profile, C1_sim.export_profile, "dag_nacht"),
                    "dynamisch": cost_engine.compute_cost(C1_sim.import_profile, C1_sim.export_profile, "dynamisch"),
                }

                peak_info = PeakInfo(
                    monthly_before=[],
                    monthly_after=[]
                )

        with_batt_cost = C1_costs[current_tariff].total_cost_eur

        # ----------------------------------------------------
        # 4. ROI-berekening (eenvoudig model)
        # ----------------------------------------------------
        yearly_saving = baseline_cost - with_batt_cost

        if self.batt_cfg is None or self.batt_cfg.investment_eur <= 0 or yearly_saving <= 0:
            roi_result = ROIResult(
                yearly_saving_eur=yearly_saving,
                payback_years=None,
                roi_percent=0.0
            )
        else:
            invest = self.batt_cfg.investment_eur
            degr = self.batt_cfg.degradation  # fractie per jaar, bijv. 0.02
            horizon = 15

            total_savings = 0.0
            payback: Optional[int] = None

            for year in range(1, horizon + 1):
                factor = (1 - degr) ** (year - 1)
                year_save = yearly_saving * factor
                total_savings += year_save

                if payback is None and total_savings >= invest:
                    payback = year

            roi_percent = (total_savings / invest) * 100.0

            roi_result = ROIResult(
                yearly_saving_eur=yearly_saving,
                payback_years=payback,
                roi_percent=roi_percent
            )

        # ----------------------------------------------------
        # 5. FullScenarioOutput teruggeven
        # ----------------------------------------------------
        return FullScenarioOutput(
            A1=A1_cost,
            B1=B1_costs,
            C1=C1_costs,
            roi=roi_result,
            peaks=peak_info
        )
