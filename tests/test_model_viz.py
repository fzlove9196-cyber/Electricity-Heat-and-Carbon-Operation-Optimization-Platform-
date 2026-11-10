"""通用建模视图（模型拓扑 + 能流）测试。"""
import json, os, tempfile
import numpy as np, pytest
from app.tools import Session, call_tool
from app.tools.model_viz import build_model_graph
from app.tools import sdco_engine as eng
from app.scenario import build_default, load_preset, list_presets

def S(): return Session("t", tempfile.mkdtemp())

def test_ieee14_graph_before_solve():
    g = build_model_graph(build_default(3, 50))
    assert len(g["buses"]) == 14 and g["summary"]["母线数"] == 14 and g["summary"]["线路数"] == 15 and g["summary"]["变压器数"] == 5
    kinds = {d["kind"] for d in g["devices"]}
    assert {"grid", "thermal", "pv", "ess", "dc", "load"} <= kinds
    assert g["summary"]["光伏 MW"] == 190 and g["summary"]["储能 MWh"] == 50 and g["summary"]["储能 MW"] == 12.5
    assert g["summary"]["电气岛数"] == 1 and not g["solved"] and len(g["links"]) == 3   # 未定义链路 → 隐式全连接
    assert all(0 <= b["x"] <= 1 and 0 <= b["y"] <= 1 for b in g["buses"])
    json.dumps(g)

@pytest.mark.parametrize("name", [n for n in list_presets() if n.endswith("highwind") or n.endswith("noSH")][:3])
def test_presets_graph(name):
    sc = load_preset(name); g = build_model_graph(sc)
    assert len(g["buses"]) == len(sc.network.buses)
    assert g["summary"]["风电 MW"] > 0 and g["summary"]["光伏 MW"] > 0          # 中卫：风/光分类
    assert g["summary"]["风电 MW"] + g["summary"]["光伏 MW"] == pytest.approx(sum(p.cap_mw for p in sc.pv))
    if any("上海" in b.name for b in sc.network.buses): assert g["summary"]["电气岛数"] >= 2

def test_flows_match_dispatch_and_balance():
    s = S(); call_tool(s, "build_scenario", {"n_dc": 3, "storage_mwh": 50})
    call_tool(s, "run_dispatch", {}); g = s.state["model_graph"]; r = s.state["results"]["optimized"]
    assert g["solved"] and g["sankey"] and "kpi" in g
    load = np.array([[abs(f)/e["rating_mw"]*100 for f in e["flow_mw"]] for e in g["branches"]]).max(axis=0)
    assert np.allclose(load, r["df"].max_line_loading_pct.values, atol=0.5)   # 与 DC-OPF 支路潮流同口径
    h = g["peak_hour"]; tot = sum(d["p_mw"][h] for d in g["devices"] if "p_mw" in d)
    assert abs(tot) < 1.0                                                       # 无损：注入总和≈0

def test_build_scenario_auto_generates_model_view():
    s = S(); r = call_tool(s, "build_scenario", {"preset": "zhongwei_summer_highwind"})
    assert r["model_view"] == "model_topology.json" and "model_summary" in r
    for f in ["model_topology.json", "model_topology.png", "model_topology.html"]:
        assert os.path.getsize(os.path.join(s.artifact_dir, f)) > 1000
    html = open(os.path.join(s.artifact_dir, "model_topology.html"), encoding="utf-8").read()
    assert "ModelViz.render" in html and "echarts" in html
    r2 = call_tool(s, "run_dispatch", {}); assert r2["model_view"]
    g = json.load(open(os.path.join(s.artifact_dir, "model_topology.json"), encoding="utf-8")); assert g["solved"]
    t = call_tool(s, "show_model_topology", {}); assert t["ok"] and t["solved"]

def test_custom_island_network():
    from app.scenario import Scenario
    sc = load_preset("zhongwei_summer_highwind").model_copy(deep=True)
    g = build_model_graph(sc)
    assert sum(i["n_bus"] for i in g["islands"]) == len(g["buses"])

def test_mock_agent_build_step_shows_model():
    from app.agent import run_turn_events
    s = S(); evs = list(run_turn_events(s, "帮我建模：三个数据中心加50MWh储能，核对模型"))
    names = [e["name"] for e in evs if e["type"] == "tool_end" and e["ok"]]
    assert names[:2] == ["build_scenario", "show_model_topology"]

def test_preview_api():
    from fastapi.testclient import TestClient
    from app.main import app
    c = TestClient(app)
    r = c.post("/api/model/preview", json=load_preset("zhongwei_winter_lowwind").model_dump()); assert r.status_code == 200 and r.json()["graph"]["summary"]["风电 MW"] > 0
    r = c.post("/api/model/preview", json=build_default(2, 0).model_dump()); assert r.json()["graph"]["summary"]["储能 MW"] == 0
