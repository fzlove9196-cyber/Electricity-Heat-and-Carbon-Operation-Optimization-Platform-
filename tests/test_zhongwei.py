"""自定义等值网络 + 中卫项目预设 冒烟测试。"""
from app.scenario import load_preset, list_presets, preset_from_text
from app.tools import sdco_engine as eng
from app.tools.sim_tools import _kpis

def test_presets_listed():
    assert "zhongwei_summer_highwind" in list_presets()
    assert preset_from_text("宁夏中卫冬季小风日优化") == "zhongwei_winter_lowwind"
    assert preset_from_text("三个数据中心优化") is None

def test_custom_network_dispatch_and_ac():
    sc = load_preset("zhongwei_winter_lowwind")
    assert not eng.validate(sc)
    b = eng.solve(sc, optimize=False); o = eng.solve(sc, optimize=True)
    kb, ko = _kpis(sc, b), _kpis(sc, o)
    assert ko["cost_cny"] <= kb["cost_cny"] + 1e-6
    assert ko["grid_import_mwh"] <= kb["grid_import_mwh"] + 1e-6
    assert 0 < ko["green_share_pct"] <= 100
    ac = eng.ac_check(sc, o)
    assert ac["converged"] and ac["voltage_ok"] and ac["loading_ok"]
    assert len(ac["ext_grid_p_mw"]) == 2   # 西北 + 华东（独立电气岛）


def test_viz_tools_topology_and_energy_flow(tmp_path):
    from app.tools import Session, call_tool
    s = Session(id="viz", artifact_dir=str(tmp_path))
    call_tool(s, "build_scenario", {"preset": "zhongwei_summer_highwind"})
    r = call_tool(s, "plot_topology", {})
    assert r["n_buses"] == 11 and r["voltage_levels_kv"] == [750.0, 330.0, 110.0] and "SH_EAST" in r["assumed"]
    r = call_tool(s, "plot_energy_flow", {"annualize_days": 1})
    fl = r["flows"]["baseline"]
    assert abs(fl["西北汇集→外送西北电网(宁夏)"] - 11492.28) < 1 and len(r["echarts"]) == 3
    r = call_tool(s, "plot_topology", {"with_flows": True})
    assert r["ac"]["converged"] and "沙坡头-天都山750" in r["ac"]["line_p_from_mw"]
    for f in r["artifacts"]: assert (tmp_path / f).exists()
