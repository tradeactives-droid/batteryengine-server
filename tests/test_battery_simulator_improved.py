from datetime import datetime, timedelta

from battery_engine_pro3.battery_model import BatteryModel
from battery_engine_pro3.battery_simulator import (
    BatterySimulator,
    _get_target_soc,
)
from battery_engine_pro3.profile_generator import generate_year_timestamps
from battery_engine_pro3.types import TimeSeries


def _make_ts(values, start=None):
    if start is None:
        start = datetime(2025, 1, 1)
    timestamps = [start + timedelta(hours=i) for i in range(len(values))]
    return TimeSeries(timestamps=timestamps, values=values, dt_hours=1.0)


def test_c_rate_derate_high_soc_limits_charge_below_pmax_dt():
    """Hoge SOC: laadvermogen < P_max * dt door C-rate derating."""
    batt = BatteryModel(
        E_cap=50.0,
        P_max=5.0,
        dod=0.9,
        eta=0.9,
        initial_soc_frac=0.90,
    )
    load = _make_ts([0.0])
    pv = _make_ts([5.0])
    sim = BatterySimulator(load, pv, batt, prices_dyn=None)
    res = sim.simulate_with_battery(simulation_year=0)

    assert len(res.import_profile) == 1
    assert len(res.export_profile) == 1
    # Van PV naar batterij (vóór rendement): moet door C-rate < P_max * dt blijven
    soc0 = batt.initial_soc_kwh
    charge_kwh = (res.soc_profile[0] - soc0) / batt.eta_charge
    assert charge_kwh > 0
    assert charge_kwh < batt.P_max * load.dt_hours


def test_c_rate_derate_low_soc_limits_discharge_below_pmax_dt():
    """
    Lage SOC-fractie (<20% van nominale span): ontladen < P_max * dt.
    Met vaste EMS-reserve (20% van effectieve span) is dat alleen haalbaar
    als effectieve E_max < nominaal (degradatie): dan E_reserve lager terwijl
    soc_frac nog op de nominale schaal < 0.2 kan zijn.
    """
    batt = BatteryModel(
        E_cap=10.0,
        P_max=5.0,
        dod=0.9,
        eta=0.9,
        initial_soc_frac=0.5,
    )
    # Eerste uur: ontladen tot net boven E_reserve; tweede uur: lage soc_frac + derate
    load = _make_ts([2.71, 3.0])
    pv = _make_ts([0.0, 0.0])
    sim = BatterySimulator(
        load,
        pv,
        batt,
        prices_dyn=None,
        annual_degradation_frac=0.02,
    )
    res = sim.simulate_with_battery(simulation_year=7)

    delivered = 3.0 - res.import_profile[1]
    assert delivered > 0
    assert delivered < batt.P_max * load.dt_hours


def test_seasonal_target_soc_winter_above_summer():
    E_min, E_max = 1.0, 10.0
    ts_winter = [datetime(2025, 1, 15, 12, 0, 0)]
    ts_summer = [datetime(2025, 7, 15, 12, 0, 0)]
    w = _get_target_soc(0, E_min, E_max, ts_winter)
    s = _get_target_soc(0, E_min, E_max, ts_summer)
    assert w > s


def test_simulation_year_degradation_increases_import_over_year():
    ts = generate_year_timestamps(2025, 1.0)
    n = len(ts)
    load_vals = [1.2] * n
    pv_vals = [0.0 if (i % 24) < 10 else 2.8 for i in range(n)]

    load = TimeSeries(timestamps=ts, values=load_vals, dt_hours=1.0)
    pv = TimeSeries(timestamps=ts, values=pv_vals, dt_hours=1.0)

    batt = BatteryModel(
        E_cap=12.0,
        P_max=5.0,
        dod=0.9,
        eta=0.9,
        initial_soc_frac=0.5,
    )

    sim0 = BatterySimulator(
        load,
        pv,
        batt,
        prices_dyn=None,
        timestamps=ts,
        annual_degradation_frac=0.02,
    )
    res0 = sim0.simulate_with_battery(simulation_year=0)

    sim7 = BatterySimulator(
        load,
        pv,
        batt,
        prices_dyn=None,
        timestamps=ts,
        annual_degradation_frac=0.02,
    )
    res7 = sim7.simulate_with_battery(simulation_year=7)

    assert res7.import_kwh > res0.import_kwh
