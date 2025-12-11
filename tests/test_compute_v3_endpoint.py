import pytest
from fastapi.testclient import TestClient

# We importeren de FastAPI app uit main.py
from main import app  

client = TestClient(app)


# ------------------------------------------------------------
# Helper: minimal request body voor NL
# ------------------------------------------------------------
def make_request_NL():
    return {
        "load_kwh": [2, 2, 2],
        "pv_kwh": [1, 1, 1],
        "prices_dyn": None,

        "E": 5,
        "P": 3,
        "DoD": 0.9,
        "eta_rt": 0.9,
        "battery_cost": 3000,
        "battery_degradation": 0.01,

        "country": "NL",
        "current_tariff": "enkel",

        "p_enkel_imp": 0.40,
        "p_enkel_exp": 0.10,
        "p_dag": 0.45,
        "p_nacht": 0.25,
        "p_exp_dn": 0.08,
        "p_export_dyn": 0.12,

        "vastrecht_year": 100.0,

        "feedin_monthly_cost": 0.0,
        "feedin_cost_per_kwh": 0.0,
        "feedin_free_kwh": 0.0,
        "feedin_price_after_free": 0.0,

        "inverter_power_kw": 5.0,
        "inverter_cost_per_kw": 10.0,

        "capacity_tariff_kw": 0.0
    }


# ------------------------------------------------------------
# Helper: minimal request body voor BE
# ------------------------------------------------------------
def make_request_BE():
    req = make_request_NL()
    req["country"] = "BE"
    req["capacity_tariff_kw"] = 50.0
    return req


# ------------------------------------------------------------
# 1. Test NL endpoint werkt
# ------------------------------------------------------------
def test_compute_v3_NL_endpoint():
    response = client.post("/compute_v3", json=make_request_NL())
    assert response.status_code == 200

    data = response.json()

    # Outputstructuur
    assert "A1" in data
    assert "B1" in data
    assert "C1" in data
    assert "roi" in data
    assert "peaks" in data

    # NL → peaks moeten leeg zijn
    assert data["peaks"]["monthly_before"] == []
    assert data["peaks"]["monthly_after"] == []


# ------------------------------------------------------------
# 2. Test BE endpoint voert peak shaving uit
# ------------------------------------------------------------
def test_compute_v3_BE_endpoint():
    response = client.post("/compute_v3", json=make_request_BE())
    assert response.status_code == 200

    data = response.json()

    # Outputstructuur
    assert "A1" in data
    assert "B1" in data
    assert "C1" in data
    assert "roi" in data
    assert "peaks" in data

    # BE → peaks moeten aanwezig zijn
    assert len(data["peaks"]["monthly_before"]) == 12
    assert len(data["peaks"]["monthly_after"]) == 12

    # reductie ≥ 0
    before = data["peaks"]["monthly_before"][0]
    after = data["peaks"]["monthly_after"][0]
    assert before >= after
