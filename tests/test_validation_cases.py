"""第二轮真实项目验证（cases/<project>/，Open-Meteo 真实气象）的回归测试：覆盖本轮发现并修复的问题。"""
import numpy as np, pytest
from app.scenario import load_preset, list_presets
from app.tools import sdco_engine as E, cooling as CL, thermal as TH
from app.tools.sim_tools import _kpis
from app.research import topics as TP, experiments as EX

def opt(name, **kw):
    sc = load_preset(name)
    for k, v in kw.items(): setattr(sc, k, v)
    return sc, E.solve(sc, True)

def dcpue(r, d):
    df = r["df"]; return float(df[f"{d}_grid_MW"].sum()/df[f"{d}_IT_MW"].sum())

def test_presets_listing_clean():
    P = list_presets()
    assert "presets" not in P and "results" not in P and "shaoguan_heatwave_dr" in P and "odense_meta_winter" in P

def test_empty_bus_does_not_crash():   # 修复：空母线功率平衡为恒等式（numpy bool）导致 Pyomo 报错
    sc, r = opt("renhe_alibaba_winter"); assert r["cost_cny"] > 0

def test_humidity_profile_used():      # 修复：湿度此前固定 0.35（湿球偏低→湿热地区冷却塔 COP/自然冷却偏乐观）
    sc = load_preset("shaoguan_summer"); d = sc.data_centers[1]
    from app.scenario import outdoor_rh
    rh = outdoor_rh(sc, d.bus); assert rh.mean() > 0.5
    hum = CL.hourly(d.thermal, np.array(sc.outdoor_temp_c), rh)["cop"].mean()
    dry = CL.hourly(d.thermal, np.array(sc.outdoor_temp_c), 0.35)["cop"].mean()
    assert hum < dry
    from app.tools import config_builder as CB
    assert CB.build({"rh": 0.8}).outdoor_rh == pytest.approx(0.8)

def test_dr_counts_behind_meter_storage():   # 新增：DR 计量关口含表后储能（临港 23MW = 储能 18MW + 算力/冷却）
    _, r = opt("lingang_dr_ess"); e = r["dr"][0]
    assert e["delivered_mw"] == pytest.approx([23.0, 23.0], abs=1e-3)
    _, r2 = opt("lingang_dr_noess"); assert max(r2["dr"][0]["delivered_mw"]) < 10.0   # 仅算力+冷却：≈6MW，与公开“全量最多 8MW”同量级

def test_direct_evap_pue_vs_published():     # 修复：直接蒸发/新风按 T_db−ε(T_db−T_wb) 判定（贵安公开 PUE 1.12）
    _, r = opt("guian_huawei_summer"); assert 1.08 <= dcpue(r, "华为云_贵安") <= 1.18

def test_immersion_pue_vs_published():       # 阿里仁和公开 PUE 1.09
    _, r = opt("renhe_alibaba_summer"); assert 1.05 <= dcpue(r, "阿里_仁和浸没") <= 1.12

def test_liquid_heat_rejection_and_cooling_diagnostics():
    with pytest.raises(RuntimeError, match="冷量不足"): E.solve(load_preset("renhe_alibaba_heatwave"), True)   # 41°C 干冷器 + 0.6×IT 冷机
    assert TH.cooling_deficits(load_preset("renhe_alibaba_heatwave"))
    _, r = opt("renhe_alibaba_heatwave_hybrid"); assert dcpue(r, "阿里_仁和浸没") < 1.12   # 干湿联合排热后可行

def test_soft_green_share():
    with pytest.raises(RuntimeError, match="min_green_share"): E.solve(load_preset("ulanqab_21vianet_lowwind_hardgreen"), True)
    _, r = opt("ulanqab_21vianet_lowwind"); assert r["cost_cny"] > 0

def test_research_resolves_site_presets():   # 修复：研究模式此前固定中卫预设
    assert TP.resolve_preset("heatwave_dr", "韶关热浪需求响应")[0] == "shaoguan_heatwave_dr"
    assert TP.resolve_preset("heat_recovery", "Meta Odense 余热供暖")[0] == "odense_meta_winter"
    F = TP.formulate("heatwave_dr", "韶关华南数谷热浪下需求响应最优方案"); assert F["card"]["preset"] == "shaoguan_heatwave_dr" and "韶关" in F["card"]["title"]
    assert next(q for q in F["questions"] if q["id"] == "q_dr")["default"] == 15.0
    assert TP.formulate("heat_recovery", "中卫冬季余热供暖值不值")["card"]["preset"] == "zhongwei_winter_coupled_heat"

def test_air_inlet_standard_not_applied_to_liquid():   # 修复：研究“热安全标准 32°C”曾施加到冷板供液节点（40°C）→ 必然不可行
    sc = EX.apply_mods(load_preset("shaoguan_heatwave_dr"), {"data_centers.*.thermal.t_allow_max_c": 32.0})
    assert [d.thermal.t_allow_max_c for d in sc.data_centers] == [45.0, 32.0]
    k = _kpis(sc, E.solve(sc, True)); assert k["tin_air_max_c"] <= 32.0 + 1e-6 and k["coolant_supply_max_c"] > 32.0

def test_terminal_switch_clears_overrides():   # 修复：换末端类型时原末端供水温度覆盖值未清除（三种末端结果相同）
    sc = EX.apply_mods(load_preset("odense_meta_winter"), {"heat_network.terminal_type": "floor"})
    assert sc.heat_network.t_supply_min_c is None and sc.heat_network.t_supply_max_c is None
    sc2 = EX.apply_mods(load_preset("odense_meta_winter"), {"heat_network.terminal_type": "radiator"}); assert sc2.heat_network.t_supply_max_c == 75.0

def test_odense_heat_pump_cop_vs_published():   # 公开 COP 4.5–5.0：卡诺效率 0.5 低估，0.7 吻合
    r = E.solve(load_preset("odense_meta_winter_eta07"), True); F = r["thermal"]["heat"]["feasibility"]
    assert 4.5 <= F["cop_min"] <= F["cop_max"] <= 5.0
    assert r["thermal"]["heat"]["balance_max_residual"] < 1e-6

@pytest.mark.parametrize("name", ["ulanqab_cicdata_winter", "shaoguan_heatwave_n1", "wuhu_telecom_heatwave", "odense_meta_coldwave"])
def test_balances_and_bounds(name):
    sc, r = opt(name)
    for d in sc.data_centers:
        x = r["thermal"]["dcs"][d.name]; assert x["thermal_balance_max_residual"] < 1e-6 and x["elec_balance_max_residual"] < 1e-6
        t = r["df"][f"{d.name}_Tin_C"]; assert t.min() >= d.thermal.t_min_c - 1e-6 and t.max() <= d.thermal.t_allow_max_c + 1e-6
        assert 1.02 < dcpue(r, d.name) < 1.5
