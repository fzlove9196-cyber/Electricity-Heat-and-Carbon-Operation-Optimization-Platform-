"""散热方式库 / 热泵 COP / 末端温度约束 / 配置构建器 / 参数扫描。"""
import numpy as np, pytest
from app.tools import cooling as CL, heat_grade as HG, config_builder as B, sweep as SW, sdco_engine as eng
from app.scenario import HeatNetwork, DCThermal

def test_library_complete():
    lib = {m["key"]: m for m in CL.library()}
    for k in ["air_chw", "air_iec", "air_dec", "liquid_cold_plate", "liquid_immersion", "hybrid"]:
        assert k in lib and lib[k]["sources"]
    assert lib["liquid_cold_plate"]["supply_c"] >= 35 and lib["liquid_immersion"]["waste_heat_c"] >= 50
    assert lib["air_chw"]["wue_l_kwh"] > lib["liquid_cold_plate"]["wue_l_kwh"]

def test_cop_monotone_and_liquid_free_cooling():
    th = DCThermal(); CL.apply_mode(th, "air_chw", cap_it=50); t = np.linspace(-10, 35, 24)
    h = CL.hourly(th, t); assert np.all(np.diff(h["cop"]) <= 1e-9) and h["ff"][0] == 1 and h["ff"][-1] == 0
    tl = DCThermal(); CL.apply_mode(tl, "liquid_cold_plate", cap_it=50); hl = CL.hourly(tl, np.full(24, 30.0))
    ha = CL.hourly(th, np.full(24, 30.0)); assert hl["ff"].mean() > ha["ff"].mean()      # 30°C 时液冷仍大量自然冷却
    assert tl.t_allow_max_c == 45 and tl.t0_c == 40                                     # 液冷节点为供液温度

def test_hybrid_fraction_blend():
    th = DCThermal(air_residual_mode="air_chw"); CL.apply_mode(th, "hybrid", 0.3, cap_it=10); t = np.full(24, 25.0)
    assert abs(CL.liquid_fraction(th) - 0.3) < 1e-9
    h = CL.hourly(th, t); assert 0 <= h["ff"].min() <= 1

def test_heat_pump_cop_carnot():
    c = HG.hp_cop(0.5, 70, 27); assert abs(c - 0.5*343.15/43) < 1e-6
    assert HG.hp_cop(0.5, 60, 45) > HG.hp_cop(0.5, 60, 25)   # 源温越高 COP 越高

def test_terminal_temperature_and_booster():
    hn = HeatNetwork(terminal_type="floor", pipe_length_km=1.0)
    H = HG.hourly(hn, 55.0, np.full(24, -12.0)); assert (H["mode"] == "direct").all() and H["margin"].min() >= 0   # 浸没 55°C 直供地暖
    hn2 = HeatNetwork(terminal_type="primary", pipe_length_km=10.0)
    H2 = HG.hourly(hn2, 32.0, np.full(24, -12.0)); assert H2["margin"].min() < 0 and H2["f_boost"].max() > 0     # 风冷余热进一次网需补热
    hn3 = HeatNetwork(terminal_type="radiator", pipe_length_km=5.0, booster="none"); H3 = HG.hourly(hn3, 32.0, np.full(24, -12.0))
    assert H3["f_boost"].max() == 0
    assert HG.supply_curve(hn2, [15.0])[0] == 70 and HG.supply_curve(hn2, [-12.0])[0] == 110

def test_config_builder_validation():
    v = B.validate_spec({"dcs": [{"name": "A", "cap_it_mw": -1, "cooling_mode": "foo"}]})
    assert not v["ok"] and any("IT 容量" in e for e in v["errors"]) and any("散热方式" in e for e in v["errors"])
    v2 = B.validate_spec({"dcs": [{"name": "A", "cap_it_mw": 20, "racks": 400, "cooling_mode": "air_chw"}]})
    assert v2["ok"] and any("液冷" in w for w in v2["warnings"])      # 50 kW/柜 风冷告警
    with pytest.raises(ValueError): B.build({"battery": {"energy_mwh": 10, "power_mw": 0}})

def test_builder_solve_safe_and_heat_feasibility():
    sp = {"dcs": [{"name": "A", "cap_it_mw": 40, "cooling_mode": "liquid_immersion", "hp_mw": 12}, {"name": "B", "cap_it_mw": 30, "cooling_mode": "air_iec", "hp_mw": 0}],
          "battery": {"power_mw": 20, "energy_mwh": 40}, "heat": {"terminal_type": "floor", "pipe_length_km": 2}}
    sc = B.build(sp); assert len(sc.data_centers) == 2 and sc.storage and sc.heat_network.terminal_type == "floor"
    r = eng.solve(sc, True, levers=B.levers(sp)); th = r["thermal"]
    assert th["safe"] and th["heat"]["feasibility"]["technical_ok_without_booster"] and th["heat"]["boost_mwh"] < 1e-6
    assert th["dcs"]["A"]["cooling"]["coolant_margin_k"] >= -1e-6 and th["dcs"]["A"]["thermal_balance_max_residual"] < 1e-5
    assert th["dcs"]["A"]["pue_avg"] < th["dcs"]["B"]["pue_avg"] + 0.05

def test_primary_network_requires_booster():
    sp = B.set_path({"heat": {"terminal_type": "primary", "pipe_length_km": 10}}, "dcs.*.cooling_mode", "air_chw")
    r = eng.solve(B.build(sp), True); F = r["thermal"]["heat"]["feasibility"]
    assert not F["technical_ok_without_booster"] and F["boost_mwh"] > 0 and F["level"] != "可行"

def test_sweep_grid_and_compare():
    res = SW.sweep({}, [{"path": "dcs.*.cooling_mode", "values": ["air_chw", "liquid_cold_plate"]}, {"path": "heat.pipe_length_km", "values": [1, 10]}])
    assert len(res["rows"]) == 4 and all(r["ok"] for r in res["rows"])
    a = [r for r in res["rows"] if r["raw"][0] == "air_chw"][0]; l = [r for r in res["rows"] if r["raw"][0] == "liquid_cold_plate"][0]
    assert l["pue"] <= a["pue"] and l["wue_l_kwh"] < a["wue_l_kwh"]
    c = SW.compare({}, [{"label": "无储能", "set": {"battery.energy_mwh": 0}}, {"label": "坏配置", "set": {"dcs.0.cap_it_mw": -5}}])
    assert c["rows"][0]["ok"] and not c["rows"][1]["ok"]
    assert "| 配置 |" in SW.to_markdown(c)

def test_api_and_agent_tools():
    from fastapi.testclient import TestClient
    from app.main import app
    c = TestClient(app)
    assert len(c.get("/api/cooling/modes").json()["modes"]) >= 6
    assert c.post("/api/config/validate", json={"spec": {"dcs": [{"name": "X", "cap_it_mw": 10}]}}).json()["ok"]
    r = c.post("/api/sessions/cfgtest1/config/build", json={"spec": {"dcs": [{"name": "X", "cap_it_mw": 20, "cooling_mode": "liquid_cold_plate", "hp_mw": 6}]}}).json()
    assert r["ok"] and "冷板" in r["dcs"][0]["cooling"]
    p = c.get("/api/sessions/cfgtest1/params").json(); names = [g["name"] for g in p["groups"]]
    for g in ["能源配置", "散热方式", "余热品位与供热末端"]: assert g in names
    sw = c.post("/api/sessions/cfgtest1/config/sweep", json={"params": [{"path": "battery.energy_mwh", "values": [0, 50]}]}).json()
    assert sw["n"] == 2
    f = c.get("/api/sessions/cfgtest1/formulation").json(); assert any(x["id"] == "hpcop" and x["active"] for x in f["constraints"])
