from fastapi.testclient import TestClient

import main

client = TestClient(main.app)


def _minimal_profile_body(**extra):
    body = {
        "annual_load_kwh": 3500.0,
        "annual_pv_kwh": 4000.0,
        "household_profile": "alleenstaand_werkend",
        "has_heatpump": False,
        "has_ev": False,
        "allow_grid_charge": False,
        "battery_strategy": "self_consumption",
        "E": 5.0,
        "P": 3.0,
        "DoD": 0.9,
        "eta_rt": 0.9,
        "battery_cost": 3000.0,
        "battery_lifetime_years": 15,
        "country": "NL",
        "current_tariff": "enkel",
        "p_enkel_imp": 0.40,
        "p_enkel_exp": 0.10,
        "p_dag": 0.45,
        "p_nacht": 0.25,
        "p_exp_dn": 0.08,
        "p_export_dyn": 0.12,
        "p_dyn_imp": 0.28,
        "vastrecht_year": 100.0,
        "feedin_monthly_cost": 0.0,
        "feedin_cost_per_kwh": 0.0,
        "feedin_free_kwh": 0.0,
        "feedin_price_after_free": 0.0,
        "inverter_power_kw": 5.0,
        "inverter_cost_per_kw": 10.0,
        "capacity_tariff_kw": 0.0,
    }
    body.update(extra)
    return body


def _stub_profiles(monkeypatch, n, load_val, pv_val):
    def fake_load(*args, **kwargs):
        return (None, [float(load_val)] * n)

    def fake_pv(*args, **kwargs):
        return (None, [float(pv_val)] * n)

    monkeypatch.setattr(main, "generate_load_profile_kwh", fake_load)
    monkeypatch.setattr(main, "generate_pv_profile_kwh", fake_pv)


def test_feedin_validation_mismatch_warns(monkeypatch):
    n = 100
    _stub_profiles(monkeypatch, n, 0.0, 10.0)
    simulated = n * 10.0
    body = _minimal_profile_body(annual_feedin_kwh=simulated * 0.5)

    response = client.post("/compute_v3_profile", json=body)
    assert response.status_code == 200
    data = response.json()
    pw = data.get("profile_warning")
    assert pw is not None
    assert pw["type"] == "feedin_mismatch"
    assert pw["provided_feedin_kwh"] == simulated * 0.5
    fv = data["calculation_method"]["feedin_validation"]
    assert fv["provided_kwh"] == simulated * 0.5
    assert fv["simulated_kwh"] == float(round(simulated, 0))


def test_feedin_validation_match_no_warning(monkeypatch):
    n = 100
    _stub_profiles(monkeypatch, n, 0.0, 10.0)
    simulated = n * 10.0
    body = _minimal_profile_body(annual_feedin_kwh=simulated)

    response = client.post("/compute_v3_profile", json=body)
    assert response.status_code == 200
    data = response.json()
    assert data.get("profile_warning") is None


def test_feedin_validation_omitted_no_warning(monkeypatch):
    n = 10
    _stub_profiles(monkeypatch, n, 0.0, 1.0)
    body = _minimal_profile_body()

    response = client.post("/compute_v3_profile", json=body)
    assert response.status_code == 200
    data = response.json()
    assert "profile_warning" not in data or data.get("profile_warning") is None
