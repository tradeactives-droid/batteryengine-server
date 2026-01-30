# battery_engine_pro3/scenario_runner.py

from __future__ import annotations
from typing import Dict, Optional, List

from .types import ScenarioResult, PeakInfo, ROIResult
from .battery_simulator import BatterySimulator
from .battery_model import BatteryModel
from .cost_engine import CostEngine
from .peak_optimizer import PeakOptimizer
from .roi_engine import ROIEngine, ROIConfig
from .dynamic_prices import build_dynamic_prices_hybrid

def _scenario_result_to_dict(sr: ScenarioResult) -> dict:
    return {
        "import_kwh": float(sr.import_kwh),
        "export_kwh": float(sr.export_kwh),
        "total_cost_eur": float(sr.total_cost_eur),
    }

def _roi_to_dict(roi: ROIResult) -> dict:
    return {
        "yearly_saving_eur": float(roi.yearly_saving_eur),
        "payback_years": roi.payback_years,
        "roi_percent": float(roi.roi_percent),
    }

def _peak_to_dict(p: PeakInfo) -> dict:
    return {
        "monthly_before": list(p.monthly_before),
        "monthly_after": list(p.monthly_after),
    }

def assess_battery(
    E: float,
    P: float,
    energy_profile: dict,
    has_ev: bool,
    has_heatpump: bool
) -> dict:
    """
    Technische beoordeling van batterij-dimensionering.
    GEEN aannames, GEEN financiële uitspraken.
    """

    assessment = {
        "capacity_fit": "unknown",
        "power_fit": "unknown",
        "primary_use": "unknown",
        "notes": []
    }

    # Veiligheid
    if E <= 0 or P <= 0:
        assessment["notes"].append("Geen actieve batterijconfiguratie.")
        return assessment

    yearly_load = energy_profile.get("yearly_load_kwh", 0)
    peak_kw = energy_profile.get("peak_load_kw", 0)

    # --- Capaciteit ---
    if yearly_load > 0:
        hours_equivalent = E / (yearly_load / 365)

        if hours_equivalent < 2:
            assessment["capacity_fit"] = "small"
            assessment["notes"].append(
                "Batterijcapaciteit is relatief klein t.o.v. dagverbruik."
            )
        elif hours_equivalent > 6:
            assessment["capacity_fit"] = "large"
            assessment["notes"].append(
                "Batterijcapaciteit is relatief groot t.o.v. dagverbruik."
            )
        else:
            assessment["capacity_fit"] = "adequate"

    # --- Vermogen ---
    if peak_kw > 0:
        power_ratio = P / peak_kw

        if power_ratio < 0.25:
            assessment["power_fit"] = "undersized"
            assessment["notes"].append(
                "Laad/ontlaadvermogen is laag t.o.v. piekbelasting."
            )
        elif power_ratio > 0.75:
            assessment["power_fit"] = "oversized"
            assessment["notes"].append(
                "Laad/ontlaadvermogen is hoog t.o.v. piekbelasting."
            )
        else:
            assessment["power_fit"] = "adequate"

    # --- Primair gebruik ---
    if has_ev or has_heatpump:
        assessment["primary_use"] = "load_shifting"
    else:
        assessment["primary_use"] = "self_consumption"

    return assessment

FullScenarioOutput = Dict[str, object]


class ScenarioRunner:
    """
    Orkestreert alle scenario’s:
    - A1: huidige situatie (met saldering)
    - B1: toekomst zonder batterij (zonder saldering)
    - C1: toekomst met batterij (zonder saldering)
    Inclusief maandelijkse kosten + cumulatieve maand-ROI
    """

    def __init__(
        self,
        load,
        pv,
        tariff_cfg,
        batt_cfg: Optional[object] = None,
    ):
        self.load = load
        self.pv = pv
        self.tariff_cfg = tariff_cfg
        self.batt_cfg = batt_cfg

    # =================================================
    # HELPER — SPLITS TIJDREEKS PER MAAND
    # =================================================
    def split_by_month(self, values: List[float], dt_hours: float) -> List[List[float]]:
        steps_per_day = int(24 / dt_hours)
        days_per_month = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]

        months: List[List[float]] = []
        idx = 0

        for days in days_per_month:
            steps = days * steps_per_day
            months.append(values[idx: idx + steps])
            idx += steps

        return months

    # =================================================
    # MAIN RUNNER
    # =================================================
    def run(self) -> FullScenarioOutput:

        current_tariff = self.tariff_cfg.current_tariff
        cost_engine = CostEngine(self.tariff_cfg)

        # =================================================
        # A1 — huidige situatie (MET saldering)
        # =================================================
        sim_no = BatterySimulator(self.load, self.pv, battery=None)
        A1_sim = sim_no.simulate_no_battery()

        self.tariff_cfg.saldering = True

        A1_per_tariff = {
            tariff: cost_engine.compute_cost(
                A1_sim.import_profile,
                A1_sim.export_profile,
                tariff,
            )
            for tariff in ["enkel", "dag_nacht", "dynamisch"]
        }

        A1 = A1_per_tariff.get(current_tariff, A1_per_tariff["enkel"])

        # =================================================
        # B1 — toekomst zonder batterij (GEEN saldering)
        # =================================================
        self.tariff_cfg.saldering = False

        B1 = {
            "enkel": cost_engine.compute_cost(
                A1_sim.import_profile,
                A1_sim.export_profile,
                "enkel",
            ),
            "dag_nacht": cost_engine.compute_cost(
                A1_sim.import_profile,
                A1_sim.export_profile,
                "dag_nacht",
            ),
        }

        # Dynamisch zonder batterij -> uurprijzen (hybride model)
        B1["dynamisch"] = cost_engine.compute_cost(
            A1_sim.import_profile,
            A1_sim.export_profile,
            "dynamisch",
        )

        B1_monthly: Dict[str, List[float]] = {}
        # enkel + dag/nacht monthly
        imp_m = self.split_by_month(A1_sim.import_profile, self.load.dt_hours)
        exp_m = self.split_by_month(A1_sim.export_profile, self.load.dt_hours)
        
        for tariff in ["enkel", "dag_nacht"]:
            B1_monthly[tariff] = [
                cost_engine.compute_cost(i, e, tariff).total_cost_eur
                for i, e in zip(imp_m, exp_m)
            ]
        
        # dynamisch monthly (uurprijzen)
        B1_monthly["dynamisch"] = [
            cost_engine.compute_cost(i, e, "dynamisch").total_cost_eur
            for i, e in zip(imp_m, exp_m)
        ]

        # =================================================
        # C1 — toekomst met batterij (GEEN saldering)
        # =================================================
        if self.batt_cfg is None:
            C1 = B1
            C1_monthly = B1_monthly
            peak_info = PeakInfo(monthly_before=[], monthly_after=[])

        else:
            battery_model = BatteryModel(
                E_cap=self.batt_cfg.E,
                P_max=self.batt_cfg.P,
                dod=self.batt_cfg.DoD,
                eta=self.batt_cfg.eta_rt,
                initial_soc_frac=0.5
            )

            # -------------------------------------------------
            # 1) PV-only batterij (GEEN uurprijs-arbitrage)
            # -> gebruiken voor enkel + dag/nacht
            # -------------------------------------------------
            sim_batt_pv_only = BatterySimulator(
                self.load,
                self.pv,
                battery_model,
                prices_dyn=None,  # <-- cruciaal: geen prijzen
            )
            sim_res_pv_only = sim_batt_pv_only.simulate_with_battery()
        
            # -------------------------------------------------
            # 2) Dynamisch HYBRIDE: fallback profiel + evt historisch
            # -------------------------------------------------
            prices_dyn, price_source = build_dynamic_prices_hybrid(
                n_steps=len(self.load.values),
                dt_hours=self.load.dt_hours,
                avg_import_price=self.tariff_cfg.p_enkel_imp
                if self.tariff_cfg.current_tariff != "dynamisch"
                else self.tariff_cfg.p_export_dyn + (
                    self.tariff_cfg.p_enkel_imp - self.tariff_cfg.p_export_dyn
                ),
                historic_prices=self.tariff_cfg.dynamic_prices,
            )

            sim_batt_dyn = BatterySimulator(
                self.load,
                self.pv,
                battery_model,
                prices_dyn=prices_dyn,
                allow_grid_charge=getattr(self.tariff_cfg, "allow_grid_charge", False),
            )
            sim_res_dyn = sim_batt_dyn.simulate_with_battery()
        
            # -------------------------------------------------
            # C1 kosten per tarief: juiste flows per tarief
            # -------------------------------------------------
            C1 = {
                "enkel": cost_engine.compute_cost(
                    sim_res_pv_only.import_profile,
                    sim_res_pv_only.export_profile,
                    "enkel",
                ),
                "dag_nacht": cost_engine.compute_cost(
                    sim_res_pv_only.import_profile,
                    sim_res_pv_only.export_profile,
                    "dag_nacht",
                ),
                "dynamisch": cost_engine.compute_cost(
                    sim_res_dyn.import_profile,
                    sim_res_dyn.export_profile,
                    "dynamisch",
                ),
            }
        
            # -------------------------------------------------
            # C1 monthly (zelfde logica per tarief)
            # -------------------------------------------------
            C1_monthly: Dict[str, List[float]] = {}
        
            # enkel + dag/nacht -> pv-only profielen
            imp_m_pv = self.split_by_month(sim_res_pv_only.import_profile, self.load.dt_hours)
            exp_m_pv = self.split_by_month(sim_res_pv_only.export_profile, self.load.dt_hours)
        
            for tariff in ["enkel", "dag_nacht"]:
                C1_monthly[tariff] = [
                    cost_engine.compute_cost(i, e, tariff).total_cost_eur
                    for i, e in zip(imp_m_pv, exp_m_pv)
                ]
        
            # dynamisch -> dynamisch profielen
            imp_m_dyn = self.split_by_month(sim_res_dyn.import_profile, self.load.dt_hours)
            exp_m_dyn = self.split_by_month(sim_res_dyn.export_profile, self.load.dt_hours)
        
            C1_monthly["dynamisch"] = [
                cost_engine.compute_cost(i, e, "dynamisch").total_cost_eur
                for i, e in zip(imp_m_dyn, exp_m_dyn)
            ]
        
            peak_info = PeakInfo(monthly_before=[], monthly_after=[])

        # =================================================
        # STAP 2.2 — CUMULATIEVE MAAND-ROI + PAYBACK
        # =================================================
        roi_monthly: Dict[str, Dict[str, object]] = {}

        if self.batt_cfg is not None:
            investment = self.batt_cfg.investment_eur

            for tariff in ["enkel", "dag_nacht", "dynamisch"]:
                monthly_savings = [
                    b - c
                    for b, c in zip(B1_monthly[tariff], C1_monthly[tariff])
                ]

                cumulative = []
                total = 0.0
                payback_month = None

                for idx, val in enumerate(monthly_savings):
                    total += val
                    cumulative.append(total)
                    if payback_month is None and total >= investment:
                        payback_month = idx + 1  # maanden tellen vanaf 1

                roi_monthly[tariff] = {
                    "monthly_savings": monthly_savings,
                    "cumulative_savings": cumulative,
                    "payback_month": payback_month,
                    "payback_years": (
                        round(payback_month / 12, 1)
                        if payback_month is not None
                        else None
                    ),
                }

        # =================================================
        # ROI — PER TARIEF (nodig voor UI-switch)
        # =================================================
        roi_per_tariff = {}

        if self.batt_cfg is not None:
            for tariff in ["enkel", "dag_nacht", "dynamisch"]:
                yearly_saving = (
                    B1[tariff].total_cost_eur
                    - C1[tariff].total_cost_eur
                )

                roi_per_tariff[tariff] = ROIEngine.compute(
                    ROIConfig(
                        battery_cost_eur=self.batt_cfg.investment_eur,
                        yearly_saving_eur=yearly_saving,
                        degradation=self.batt_cfg.degradation_per_year,
                        horizon_years=self.batt_cfg.lifetime_years,
                    )
                )
        else:
            for tariff in ["enkel", "dag_nacht", "dynamisch"]:
                roi_per_tariff[tariff] = ROIResult(
                    yearly_saving_eur=0.0,
                    payback_years=None,
                    roi_percent=0.0,
                )

        # =================================================
        # ENERGY PROFILE SUMMARY (backend facts for advice)
        # NL-only: gebaseerd op meetdata (load/pv) en basisflows zonder batterij
        # =================================================
        total_load_kwh = sum(self.load.values)
        total_pv_kwh = sum(self.pv.values)

        direct_self_consumption_kwh = 0.0
        pv_export_kwh = 0.0

        for l, p in zip(self.load.values, self.pv.values):
            direct_self_consumption_kwh += min(l, p)
            pv_export_kwh += max(p - l, 0.0)

        # Piekuren op uurniveau (werkt voor uur- en kwartierdata)
        steps_per_hour = int(round(1.0 / self.load.dt_hours))
        hourly_load = [0.0] * 24
        hourly_pv = [0.0] * 24

        for i, (l, p) in enumerate(zip(self.load.values, self.pv.values)):
            hour = int((i / steps_per_hour) % 24)
            hourly_load[hour] += l
            hourly_pv[hour] += p

        peak_load_hour = max(range(24), key=lambda h: hourly_load[h])
        peak_pv_hour = max(range(24), key=lambda h: hourly_pv[h])

        energy_profile = {
            "annual_load_kwh": total_load_kwh,
            "annual_pv_kwh": total_pv_kwh,
            "direct_self_consumption_kwh": direct_self_consumption_kwh,
            "pv_export_kwh": pv_export_kwh,
            "peak_load_hour": peak_load_hour,
            "peak_pv_hour": peak_pv_hour,
        }

        battery_assessment = assess_battery(
            E=float(getattr(self.batt_cfg, "E", 0.0) or 0.0),
            P=float(getattr(self.batt_cfg, "P", 0.0) or 0.0),
            energy_profile={
                 "yearly_load_kwh": total_load_kwh,
                "peak_load_kw": max(self.load.values) / self.load.dt_hours
            },
            has_ev=getattr(self.batt_cfg, "has_ev", False),
            has_heatpump=getattr(self.batt_cfg, "has_heatpump", False),
        )
        
        return {
            "A1": _scenario_result_to_dict(A1),

            "A1_per_tariff": {
                k: _scenario_result_to_dict(v)
                for k, v in A1_per_tariff.items()
            },

            "B1": {
                k: _scenario_result_to_dict(v)
                for k, v in B1.items()
            },

            "C1": {
                k: _scenario_result_to_dict(v)
                for k, v in C1.items()
            },

            "B1_monthly": B1_monthly,
            "C1_monthly": C1_monthly,

            "roi_per_tariff": {
                k: _roi_to_dict(v)
                for k, v in roi_per_tariff.items()
            },

            "peaks": _peak_to_dict(peak_info),

            "energy_profile": energy_profile,
            "battery_assessment": battery_assessment,
        }
