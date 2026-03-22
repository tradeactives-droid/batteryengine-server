import pytest

from battery_engine_pro3.roi_engine import ROIEngine, ROIConfig


def test_roi_near_zero_investment_is_safely_suppressed():
    res = ROIEngine.compute(
        ROIConfig(
            battery_cost_eur=1.0,
            yearly_saving_eur=120.0,
            degradation=0.01,
            horizon_years=15,
        )
    )

    assert res.yearly_saving_eur == pytest.approx(120.0)
    assert res.payback_years is None
    assert res.roi_percent == pytest.approx(0.0)


def test_roi_normal_investment_still_uses_formula():
    res = ROIEngine.compute(
        ROIConfig(
            battery_cost_eur=4000.0,
            yearly_saving_eur=500.0,
            degradation=0.0,
            horizon_years=10,
        )
    )

    # Totale besparing = 500 * 10 = 5000
    # ROI% = (5000 - 4000) / 4000 * 100 = 25%
    assert res.roi_percent == pytest.approx(25.0)
    assert res.payback_years == 8
