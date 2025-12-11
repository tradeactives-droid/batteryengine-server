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
    ##
from .battery_simulator import BatterySimulator
from .cost_engine import CostEngine
from .peak_optimizer import PeakOptimizer
from .peak_optimizer import PeakShavingPlanner  # Fase 3 planning
from .roi_engine import ROIEngine, ROIConfig


# ======================================================
# FullScenarioOutput
# ======================================================
@dataclass
class FullScenarioOutput:
    """
    Volledige output van BatteryEngine Pro 3.
    """
    A1: ScenarioResult
    B1: Dict[TariffCode, ScenarioResult]
    C1: Dict[TariffCode, ScenarioResult]
    roi: ROIResult
    peaks: PeakInfo


# ======================================================
# ScenarioRunner
# ======================================================
class ScenarioRunner:
    """
    Orkestreert alle scenario’s:
    A1 = huidige situatie (geen batterij)
    B1 = toekomst zonder batterij
    C1 = toekomst met batterij (incl. BE peak shaving)
    ROI = 15 jaar
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

    # ----------------------------------------------------
    # Battery builder
    # ----------------------------------------------------
    def _build_battery_model(self) -> BatteryModel:
        if self.batt_cfg is None:
            raise ValueError("BatteryConfig is required for battery scenarios")

        cfg = self.batt_cfg
        return BatteryModel(
            E_cap=cfg.E,
            P_max=cfg.P,
            dod=cfg.DoD,
            eta=cfg.eta_rt
        )

    # ----------------------------------------------------
    # Main execution
    # ----------------------------------------------------
    def run(self) -> FullScenarioOutput:
        country = self.tariff_cfg.country          # "NL" / "BE"
        current_tariff = self.tariff_cfg.current_tariff
        cost_engine = CostEngine(self.tariff_cfg)

        # =================================================
        # 1. A1 — huidige situatie
        # =================================================
        sim_no = BatterySimulator(self.load, self.pv, battery=None)
        A1_sim = sim_no.simulate_no_battery()

        A1_cost = cost_engine.compute_cost(
            A1_sim.import_profile,
            A1_sim.export_profile,
            current_tariff
        )

        # =================================================
        # 2. B1 — toekomst zonder batterij (alle tarieven)
        # =================================================
        B1_sim = sim_no.simulate_no_battery()

        B1_costs: Dict[TariffCode, ScenarioResult] = {
            "enkel":     cost_engine.compute_cost(B1_sim.import_profile, B1_sim.export_profile, "enkel"),
            "dag_nacht": cost_engine.compute_cost(B1_sim.import_profile, B1_sim.export_profile, "dag_nacht"),
            "dynamisch": cost_engine.compute_cost(B1_sim.import_profile, B1_sim.export_profile, "dynamisch"),
        }

        baseline_cost = B1_costs[current_tariff].total_cost_eur

        # =================================================
        # 3. C1 — toekomst met batterij
        # =================================================
        if self.batt_cfg is None:
            # Geen batterij → zelfde als B1
            C1_costs = B1_costs.copy()
            peak_info = PeakInfo(monthly_before=[], monthly_after=[])

        else:
            battery_model = self._build_battery_model()

            # --------------------------------------------
            # BE → Peak Shaving FASE 1+2+3
            # --------------------------------------------
            if country == "BE":

                # Fase 1: baseline peaks
                baseline_peaks = PeakOptimizer.compute_monthly_peaks(self.load, self.pv)

                # Fase 2: targets (bijv 85%)
                monthly_targets = PeakOptimizer.compute_monthly_targets(
                    baseline_peaks,
                    reduction_factor=0.85
                )

                # Fase 3: SoC–planning curve
                soc_plan = PeakShavingPlanner.plan_monthly_soc_targets(
                    self.load,
                    self.pv,
                    battery_model,
                    baseline_peaks,
                    monthly_targets
                )

                # Peak–shaving simulatie (met soc_plan)
                new_peaks, C1_import, C1_export, C1_soc = PeakOptimizer.simulate_with_peak_shaving(
                    self.load,
                    self.pv,
                    battery_model,
                    monthly_targets,
                    soc_plan
                )

                # Capaciteitstarief heeft JAAR–piek nodig
                peak_before_kw = max(baseline_peaks)
                peak_after_kw  = max(new_peaks)

                C1_costs = {
                    "enkel": cost_engine.compute_cost(
                        C1_import, C1_export, "enkel",
                        peak_kw_before=peak_before_kw,
                        peak_kw_after=peak_after_kw
                    ),
                    "dag_nacht": cost_engine.compute_cost(
                        C1_import, C1_export, "dag_nacht",
                        peak_kw_before=peak_before_kw,
                        peak_kw_after=peak_after_kw
                    ),
                    "dynamisch": cost_engine.compute_cost(
                        C1_import, C1_export, "dynamisch",
                        peak_kw_before=peak_before_kw,
                        peak_kw_after=peak_after_kw
                    ),
                }

                peak_info = PeakInfo(
                    monthly_before=baseline_peaks,
                    monthly_after=new_peaks
                )

            # --------------------------------------------
            # NL → normale batterij-optimalisatie
            # --------------------------------------------
            else:
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

        # =================================================
        # 4. ROI via ROIEngine
        # =================================================
        with_batt_cost = C1_costs[current_tariff].total_cost_eur
        yearly_saving = baseline_cost - with_batt_cost

        if self.batt_cfg is None:
            roi_result = ROIResult(
                yearly_saving_eur=yearly_saving,
                payback_years=None,
                roi_percent=0.0
            )
        else:
            roi_cfg = ROIConfig(
                battery_cost_eur=self.batt_cfg.investment_eur,
                yearly_saving_eur=yearly_saving,
                degradation=self.batt_cfg.degradation,
                horizon_years=15
            )
            roi_result = ROIEngine.compute(roi_cfg)

        # =================================================
        # 5. Teruggeven aan API
        # =================================================
        return {
            "A1": A1_cost.to_dict(),
            "B1": {k: v.to_dict() for k, v in B1_costs.items()},
            "C1": {k: v.to_dict() for k, v in C1_costs.items()},
            "roi": roi_result.to_dict(),
            "peaks": peak_info.to_dict(),
        }
