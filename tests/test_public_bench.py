"""公开基准 (cases/public_bench) 发现问题的回归测试。"""
import numpy as np, pandapower as pp, pandapower.networks as pn, pytest
from app.tools import sdco_engine as E
from app.market import core as C


@pytest.mark.parametrize("case", ["case14", "case57"])
def test_dc_branch_model_matches_pandapower_with_taps(case):
    net = getattr(pn, case)(); pp.rundcpp(net)
    A = E.branch_arrays(net); th = np.deg2rad(net._ppc["bus"][:, 8].real)
    f = (th[A["fb"]] - th[A["tb"]]) / A["xb"] * net.sn_mva
    ref = np.r_[net.res_line.p_from_mw.values, net.res_trafo.p_hv_mw.values]
    assert np.abs(f - ref).max() < 1e-6


def test_water_fill_equals_flat_when_unconstrained_and_conserves_energy():
    assert np.allclose(C._water_fill([10.0]*24, 48.0), [2.0]*24)
    a = C._water_fill([0.5]*6 + [10.0]*18, 48.0)
    assert abs(sum(a) - 48.0) < 1e-9 and max(a[:6]) <= 0.5 + 1e-12


def _portfolio(chiller_x=None):
    res, _, _ = C.resources_from_case("zhongwei", with_backup=True)
    for r in res:
        if chiller_x and r["type"] == "dc": r["thermal"]["chiller_cap_mw_th"] = chiller_x*r["cap_it_mw"]
    return {"id": "t", "rule_id": "demo_ningxia", "resources": res}


def test_baseline_keeps_batch_energy_when_thermal_binds():
    P = _portfolio(1.05)
    for r in P["resources"]:
        if r["type"] == "dc": r["outdoor_temp_c"] = [42.0]*12 + [25.0]*12
    price = [300.0]*24
    b = C.optimize(P, price, baseline=True); o = C.optimize(P, price)
    for r in P["resources"]:
        if r["type"] == "dc":
            sb = sum(b["per"][r["id"]]["it_mw"]) ; so = sum(o["per"][r["id"]]["it_mw"])
            assert abs(sb - so) < 1e-2


def test_rolling_with_fixed_past_stays_feasible_and_reports_unserved():
    P = _portfolio(1.05); price = list(np.linspace(100, 400, 24))
    da = C.optimize(P, price)
    for r in P["resources"]:
        if r["type"] == "dc": r["outdoor_temp_c"] = [45.0]*24
    new = C.optimize(P, price, target=da["g"], dev_pen=5.0, fix=da, from_t=8)
    assert new["ok"] and "unserved_batch_mwh" in new


def test_dr_baseline_day_type_filter_optional_and_default_unchanged():
    wk = [[10.0]*24]*5; we = [[4.0]*24]*2; hist = wk[:3] + we + wk[3:]
    types = ["workday"]*3 + ["weekend"]*2 + ["workday"]*2
    old = C.dr_baseline(hist, "prior_n_days", [14])
    assert old["baseline_mw"][14] < 10.0                       # 旧行为：混入周末
    new = C.dr_baseline(hist, "prior_n_days", [14], history_day_types=types, event_day_type="workday")
    assert new["baseline_mw"][14] == pytest.approx(10.0)


def test_adjusted_baseline_does_not_read_event_hours():
    hist = [[10.0]*24 for _ in range(5)]
    act = [11.0]*24; act[14] = act[15] = float("nan")
    b = C.dr_baseline(hist, "adjusted_similar_days", [14, 15], actual=act)
    assert all(np.isfinite(b["baseline_mw"])) and b["adjust_ratio"] == pytest.approx(1.1)


def test_default_rule_dr_method_unchanged():
    assert C.get_rule("demo_ningxia")["dr"]["baseline_method"] == "similar_days_avg"


def test_dr_v2_x_of_y_picks_highest_and_additive_cap():
    hist = [[float(v)]*24 for v in (1, 5, 3, 4, 2)]
    b = C.dr_baseline_v2(hist, [14], method="x_of_y", x=2, y=5)
    assert b["baseline_mw"][14] == pytest.approx(4.5)
    act = [100.0]*24; act[14] = float("nan")
    b2 = C.dr_baseline_v2(hist, [14], method="x_of_y", x=2, y=5, actual=act, adjust="add", adjust_cap_pct=20)
    assert b2["adjust_window"] == [10, 11, 12] and b2["adjust_shift"] == pytest.approx(0.9)


def test_dr_v2_towt_recovers_temperature_response_without_event_data():
    rng = np.random.default_rng(0); T = rng.uniform(15, 35, (30, 24)); L = 50 + 2.0*np.maximum(T - 22, 0)
    te = np.full(24, 33.0); b = C.dr_baseline_v2(L, [14], method="towt", history_temps=T, event_temps=te)
    assert b["baseline_mw"][14] == pytest.approx(50 + 2*11, rel=0.02)
