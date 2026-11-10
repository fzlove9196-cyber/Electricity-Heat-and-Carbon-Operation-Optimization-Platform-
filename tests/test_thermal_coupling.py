"""算-电-热-碳耦合：热模型、热安全硬约束、DR、余热回收、能量平衡。"""
import numpy as np, pytest
from app.scenario import load_preset, build_default, DCThermal, HeatNetwork, DREvent
from app.tools import sdco_engine as eng, thermal as th

@pytest.fixture(scope="module")
def summer():
    sc = load_preset("zhongwei_summer_coupled"); return sc, eng.solve(sc, False), eng.solve(sc, True)

def test_cop_and_free_cooling_curves():
    t = DCThermal()
    cop = th.cop_curve(t, [5, 25, 40, 80]); assert cop[1] == pytest.approx(5.5) and cop[0] > cop[1] > cop[2] and cop[3] == t.cop_min
    ff = th.free_frac(t, [0, 8, 13, 18, 30]); assert list(ff) == pytest.approx([1, 1, 0.5, 0, 0])
    assert th.chiller_avail(DCThermal(chiller_cap_mw_th=100, chiller_units=5)) == pytest.approx(80)

def test_dynamic_pue_physical_range(summer):
    sc, b, o = summer
    for r in (b, o):
        for d, x in r["thermal"]["dcs"].items():
            assert 1.03 <= x["pue_min"] <= x["pue_avg"] <= x["pue_max"] <= 1.6, (d, x)
    # 动态 PUE 随室外温度：午后 PUE > 凌晨 PUE（基线定送风温度）
    df = b["df"]; assert df["ZW_NEW_A_PUE"][15] > df["ZW_NEW_A_PUE"][4]

def test_energy_balances_close(summer):
    sc, b, o = summer
    for r in (b, o):
        for x in r["thermal"]["dcs"].values():
            assert x["thermal_balance_max_residual"] < 1e-5 and x["elec_balance_max_residual"] < 1e-6
        # 电网侧节点平衡：发电+新能源 = 负荷+DC+储能+外送 （无损 DC-OPF）
        df = r["df"]; gen = sum(df[f"gen{g}_MW"] for g in range(len(r["gens"]))) + df.pv_used
        load = df.base_load_MW + sum(df[f"{d.name}_grid_MW"] for d in sc.data_centers) + sum(df[f"{s}_ch"] - df[f"{s}_dis"] for s in r["storage"]) + df.grid_export_MW
        assert np.abs(gen - load).max() < 1e-5

def test_thermal_safety_hard_constraints(summer):
    sc, b, o = summer
    for d in sc.data_centers:
        t = d.thermal; tin = o["df"][f"{d.name}_Tin_C"]
        assert tin.min() >= t.t_min_c - 1e-6 and tin.max() <= t.t_allow_max_c + 1e-6
        assert np.abs(np.diff(np.r_[t.t0_c, tin.values])).max() <= t.ramp_max_k_h + 1e-6
        assert (o["df"][f"{d.name}_chiller_MWth"] <= th.chiller_avail(t) + 1e-6).all()
    assert o["thermal"]["safe"] and not o["thermal"]["violations"]

def test_precooling_and_tes_reduce_cost(summer):
    sc, b, o = summer
    off = eng.solve(sc, True, levers=dict(precool=False, tes=False, heat=False, dr=False))
    assert o["objective"] < off["objective"] - 1.0
    assert o["df"]["ZW_NEW_A_tes_dis_MWth"].sum() > 1.0                     # 蓄冷罐被使用
    assert o["df"]["ZW_NEW_A_Tin_C"].min() < sc.data_centers[1].thermal.t0_c - 0.5   # 发生预冷

def test_heatwave_stress_binds():
    sc = load_preset("zhongwei_heatwave_stress"); r = eng.solve(sc, True); S = r["thermal"]["dcs"]
    assert r["thermal"]["safe"]
    assert sum(x["binding_hours"]["chiller_n1"] for x in S.values()) > 10
    assert max(x["tin_max_c"] for x in S.values()) > 27.0                     # 进入推荐~允许区间
    assert min(x["margin_to_allow_k"] for x in S.values()) >= -1e-6
    # 更严格的允许上限 → 成本上升（热安全约束起作用）
    tight = sc.model_copy(deep=True)
    for d in tight.data_centers: d.thermal.t_allow_max_c = 27.0
    assert eng.solve(tight, True)["objective"] > r["objective"] + 1.0

def test_demand_response_delivery_and_revenue():
    sc = load_preset("zhongwei_summer_coupled_dr"); r = eng.solve(sc, True)
    ev = r["dr"][0]; assert ev["kind"] == "reduce" and 0 < ev["delivered_mwh"] <= ev["requested_mwh"] + 1e-6
    assert ev["revenue_cny"] == pytest.approx(ev["delivered_mwh"]*ev["price_cny_mwh"], rel=1e-4)
    df = r["df"]; e = sc.dr_events[0]
    for t in range(e.start, e.end):   # 响应量 ≤ 基线 − 实际
        load = sum(df[f"{d}_grid_MW"][t] for d in e.dcs)
        assert df["dr_delivered_MW"][t] <= df["dr_baseline_MW"][t] - load + 1e-4
    no = eng.solve(sc, True, levers=dict(dr=False)); assert r["objective"] < no["objective"]

def test_mandatory_dr_hard():
    sc = load_preset("zhongwei_summer_coupled_dr"); sc.dr_events = [sc.dr_events[0].model_copy(update=dict(mandatory=True, request_mw=15.0))]
    r = eng.solve(sc, True); assert min(r["dr"][0]["delivered_mw"]) >= 15.0 - 1e-6

def test_heat_recovery_balance_and_offset():
    sc = load_preset("zhongwei_winter_coupled_heat"); r = eng.solve(sc, True); h = r["thermal"]["heat"]
    assert h["delivered_mwh"] > 100 and h["balance_max_residual"] < 1e-6
    assert h["carbon_offset_t"] == pytest.approx(h["delivered_mwh"]*sc.heat_network.boiler_ef_t_mwh_th, rel=1e-4)
    assert (r["df"]["heat_delivered_MWth"] <= np.array(sc.heat_network.demand_mw_th) + 1e-6).all()
    for d in sc.data_centers:   # 热泵取热 ≤ 可回收比例×IT
        t = d.thermal
        if t.hp_cap_mw_th > 0:
            assert (r["df"][f"{d.name}_hp_heat_MWth"]*(1 - 1/t.hp_cop) <= t.hr_max_frac*r["df"][f"{d.name}_IT_MW"] + 1e-6).all()
    nh = eng.solve(sc, True, levers=dict(heat=False)); assert nh["emissions_t"] > r["emissions_t"]

def test_constant_pue_fallback_unchanged():
    sc = load_preset("zhongwei_summer_highwind"); r = eng.solve(sc, True)
    assert "thermal" not in r and r["thermal_mode"] == "constant_pue"
    df = r["df"]; d = sc.data_centers[0]
    assert df[f"{d.name}_grid_MW"][5] == pytest.approx(d.pue*df[f"{d.name}_IT_MW"][5])

def test_default_scenario_with_thermal_tool():
    from app.tools.base import Session
    from app.tools.sim_tools import build_scenario, run_dispatch, compute_kpis
    import tempfile
    s = Session("tthermal", tempfile.mkdtemp())
    build_scenario(s, n_dc=2, storage_mwh=20, thermal=True, tes=True, heat_recovery=True, dr_mw=5)
    sc = s.state["scenario"]; assert sc.thermal_mode == "coupled" and sc.heat_network and sc.dr_events
    out = run_dispatch(s, "optimized"); assert out["thermal_safe"] and "dr" in out
    k = compute_kpis(s)["kpis"]; assert 1.0 < k["pue_avg"] < 1.6 and "heat_delivered_mwh" in k

def test_mock_routing_keywords():
    from app.scenario import preset_from_text
    from app.llm import parse_request
    assert preset_from_text("中卫夏季虚拟储冷与预冷，看动态PUE") == "zhongwei_summer_coupled"
    assert preset_from_text("中卫冬季余热供热") == "zhongwei_winter_coupled_heat"
    assert preset_from_text("中卫夏季需求响应") == "zhongwei_summer_coupled_dr"
    assert preset_from_text("中卫热浪热安全压力测试") == "zhongwei_heatwave_stress"
    assert preset_from_text("和林格尔冬季余热供暖") == "helinger_winter_coupled_heat"
    a = parse_request("三个数据中心，考虑余热回收和需求响应 30MW，18-21点")
    assert a["thermal"] and a["heat_recovery"] and a["dr_mw"] == 30 and a["dr_window"] == [18, 21]

def test_formulation_and_params_groups():
    from app import transparency as tr
    sc = load_preset("zhongwei_winter_coupled_heat")
    f = tr.formulation(sc); ids = {c["id"]: c["active"] for c in f["constraints"]}
    assert ids["rc"] and ids["tsafe"] and ids["n1"] and ids["heatbal"] and ids["dr"]
    f2 = tr.formulation(load_preset("zhongwei_summer_highwind")); ids2 = {c["id"]: c for c in f2["constraints"]}
    assert not ids2["rc"]["active"] and "常数 PUE" in ids2["rc"]["reason"]
    class S: state = dict(scenario=sc, origin=dict(kind="preset", name=sc.name))
    ps = tr.param_sheet(S()); names = [g["name"] for g in ps["groups"] if g["items"]]
    for g in ["热管理与冷却", "余热回收与供热", "需求响应", "碳"]: assert g in names
