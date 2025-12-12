# battery_engine_pro3/scenario_runner.py

from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, List

from .types import TimeSeries, TariffConfig, BatteryConfig, ScenarioResult
from .battery_model import BatteryModel
from .battery_simulator import BatterySimulator
from .cost_engine import CostEngine
from .peak_optimizer import PeakOptimizer, PeakShavingPlanner


# ============================================================
# PEAK INFO STRUCTUUR
# ============================================================

@dataclass
class PeakInfo:
    monthly_before: List[float]
    monthly_after: List[float]


# ============================================================
# FULL SCENARIO STRUCTUUR
# ============================================================

@dataclass
class FullScenarioOutput:
    A1: ScenarioResult
    B1: Dict[str, ScenarioResult]
    C1: Dict[str, ScenarioResult]
    roi: float
    peaks: PeakInfo


# ============================================================
# SCENARIO RUNNER
# ============================================================

class ScenarioRunner:

    def __init__(
        self,
        load: TimeSeries,
        pv: TimeSeries,
        tariff_cfg: TariffConfig,
        batt_cfg: BatteryConfig | None
    ) -> None:
        self.load = load
        self.pv = pv
        self.tariff_cfg = tariff_cfg
        self.batt_cfg = batt_cfg

    # ------------------------------------------------------------
    def _build_battery_model(self) -> BatteryModel:
        return BatteryModel(
            E_cap=self.batt_cfg.E,
            P_max=self.batt_cfg.P,
            dod=self.batt_cfg.DoD,
            eta=self.batt_cfg.eta_rt,
            initial_soc_frac=1.0
        )

    # ------------------------------------------------------------
    def run(self) -> FullScenarioOutput:

        tariff = self.tariff_cfg
        country = tariff.country
        cost_engine = CostEngine(tariff)

        # --------------------------------------------------------
        # 1. A1 — Huidige situatie
        # --------------------------------------------------------
        sim_no = BatterySimulator(self.load, self.pv, battery=None)
        A1_sim = sim_no.simulate_no_battery()

        A1_cost = cost_engine.compute_cost(
            A1_sim.import_profile,
            A1_sim.export_profile,
            tariff.current_tariff
        )

        # --------------------------------------------------------
        # 2. B1 — Toekomst zonder batterij, alle tarieven
        # --------------------------------------------------------
        B1_sim = sim_no.simulate_no_battery()

        B1_costs: Dict[str, ScenarioResult] = {
            "enkel": cost_engine.compute_cost(B1_sim.import_profile, B1_sim.export_profile, "enkel"),
            "dag_nacht": cost_engine.compute_cost(B1_sim.import_profile, B1_sim.export_profile, "dag_nacht"),
            "dynamisch": cost_engine.compute_cost(B1_sim.import_profile, B1_sim.export_profile, "dynamisch"),
        }

        # --------------------------------------------------------
        # 3. C1 — Met batterij
        # --------------------------------------------------------
        if self.batt_cfg is None:
            C1_costs = B1_costs.copy()
            peak_info = PeakInfo(monthly_before=[], monthly_after=[])

        else:
            battery_model = self._build_battery_model()

            # ----------------------------------------------------
            # NL — GEEN PEAK SHAVING
            # ----------------------------------------------------
            if country == "NL":
                sim_batt = BatterySimulator(self.load, self.pv, battery_model)
                C1_sim = sim_batt.simulate_with_battery()

                C1_costs = {
                    "enkel": cost_engine.compute_cost(C1_sim.import_profile, C1_sim.export_profile, "enkel"),
                    "dag_nacht": cost_engine.compute_cost(C1_sim.import_profile, C1_sim.export_profile, "dag_nacht"),
                    "dynamisch": cost_engine.compute_cost(C1_sim.import_profile, C1_sim.export_profile, "dynamisch")
                }

                peak_info = PeakInfo(monthly_before=[], monthly_after=[])

            # ----------------------------------------------------
            # BE — MET PEAK SHAVING
            # ----------------------------------------------------
            else:
                # 1. Baseline peaks
                baseline_peaks = PeakOptimizer.compute_monthly_peaks(self.load, self.pv)

                # 2. Doelpeaks (bv. 85%)
                monthly_targets = PeakOptimizer.compute_monthly_targets(baseline_peaks, 0.85)

                # 3. Minimum SoC curve
                soc_plan = PeakShavingPlanner.plan_monthly_soc_targets(
                    self.load, self.pv, battery_model,
                    baseline_peaks, monthly_targets
                )

                # 4. Peak shaving simulatie
                new_peaks, imp, exp, soc = PeakOptimizer.simulate_with_peak_shaving(
                    self.load, self.pv, battery_model,
                    monthly_targets, soc_plan
                )

                # 5. Kosten voor alle tarieven
                C1_costs = {
                    "enkel": cost_engine.compute_cost(imp, exp, "enkel",
                                                      peak_kw_before=max(baseline_peaks),
                                                      peak_kw_after=max(new_peaks)),
                    "dag_nacht": cost_engine.compute_cost(imp, exp, "dag_nacht",
                                                          peak_kw_before=max(baseline_peaks),
                                                          peak_kw_after=max(new_peaks)),
                    "dynamisch": cost_engine.compute_cost(imp, exp, "dynamisch",
                                                          peak_kw_before=max(baseline_peaks),
                                                          peak_kw_after=max(new_peaks)),
                }

                peak_info = PeakInfo(
                    monthly_before=baseline_peaks,
                    monthly_after=new_peaks
                )

        # --------------------------------------------------------
        # ROI berekening
        # --------------------------------------------------------
        baseline_cost = B1_costs[tariff.current_tariff].total_cost_eur
        with_batt_cost = C1_costs[tariff.current_tariff].total_cost_eur

        annual_saving = baseline_cost - with_batt_cost
        if self.batt_cfg and self.batt_cfg.investment_eur > 0:
            roi = annual_saving / self.batt_cfg.investment_eur
        else:
            roi = 0.0

        # --------------------------------------------------------
        # Structuur volledig teruggeven
        # --------------------------------------------------------
        return FullScenarioOutput(
            A1=A1_cost,
            B1=B1_costs,
            C1=C1_costs,
            roi=roi,
            peaks=peak_info
        )
