"""拓扑编辑 API 与 编辑→重新仿真 流程测试。"""
import os, tempfile, json
os.environ.setdefault("RAG_PRELOAD", "0")
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.scenario import build_default
from app.tools import sdco_engine as eng, model_edit as me

c = TestClient(app)

def _init(**body):
    r = c.post("/api/sessions/new/model/init", json=body); assert r.status_code == 200, r.text; return r.json()

def test_ieee14_to_custom_is_equivalent():
    sc = build_default(3, 50); cu = me.to_custom(sc)
    a, b = eng.solve(sc, True), eng.solve(cu, True)
    assert b["cost_cny"] == pytest.approx(a["cost_cny"], rel=1e-6)
    assert eng.ac_check(cu, b)["converged"]

def test_edit_crud_undo_redo_validate():
    j = _init(preset="helinger_typical_noBJ"); sid = j["session_id"]; nb = len(j["graph"]["buses"])
    r = c.patch(f"/api/sessions/{sid}/model/element/ess/ESS_HD", json={"power_mw": 100, "energy_mwh": 400}); assert r.status_code == 200
    assert c.get(f"/api/sessions/{sid}/model/element/ess/ESS_HD").json()["params"]["power_mw"] == 100
    r = c.post(f"/api/sessions/{sid}/model/element", json={"type": "bus", "params": {"name": "新母线X", "vn_kv": 35}}).json()
    assert len(r["graph"]["buses"]) == nb + 1 and any("悬空" in w for w in r["validation"]["warnings"])
    r = c.post(f"/api/sessions/{sid}/model/element", json={"type": "line", "params": {"from_bus": 1, "to_bus": nb, "rating_mva": 100}}).json()
    assert any("电压等级不同" in e for e in r["validation"]["errors"])                      # 220kV-35kV 用线路 → 错误
    c.post(f"/api/sessions/{sid}/model/undo")
    r = c.post(f"/api/sessions/{sid}/model/element", json={"type": "trafo", "params": {"hv_bus": 1, "lv_bus": nb, "sn_mva": 100}}).json()
    assert not r["validation"]["errors"]
    r = c.post(f"/api/sessions/{sid}/model/element", json={"type": "pv", "params": {"bus": nb, "cap_mw": 80}}).json()
    assert r["graph"]["summary"]["光伏 MW"] == 140
    r = c.patch(f"/api/sessions/{sid}/model/element/dc/移动_HLGE", json={"pue": 1.3, "flex_share": 0.4, "name": "移动_X"}).json()
    sc = me.Scenario.model_validate(c.get(f"/api/sessions/{sid}/model/edit").json()["scenario"])
    d = next(x for x in sc.data_centers if x.name == "移动_X"); assert d.pue == 1.3 and abs(d.batch_mwh/24/(sum(d.interactive_mw)/24 + d.batch_mwh/24) - 0.4) < 1e-3
    assert any(l.a == "移动_X" or l.b == "移动_X" for l in sc.links) or not sc.links
    assert c.delete(f"/api/sessions/{sid}/model/element/bus/{nb}").status_code == 400          # 有元件 → 需级联
    r = c.delete(f"/api/sessions/{sid}/model/element/bus/{nb}?cascade=1").json(); assert len(r["graph"]["buses"]) == nb
    assert r["graph"]["summary"]["光伏 MW"] == 60
    r = c.post(f"/api/sessions/{sid}/model/undo").json(); assert len(r["graph"]["buses"]) == nb + 1 and r["can_redo"]
    r = c.post(f"/api/sessions/{sid}/model/redo").json(); assert len(r["graph"]["buses"]) == nb
    assert c.patch(f"/api/sessions/{sid}/model/element/line/0", json={"to_bus": 99}).status_code == 400   # 越界被拒绝

def test_isolated_load_blocks_rerun_and_layout():
    j = _init(preset="zhangbei_summer"); sid = j["session_id"]
    r = c.post(f"/api/sessions/{sid}/model/element", json={"type": "bus", "params": {"name": "孤岛", "vn_kv": 110}}).json(); nb = len(r["graph"]["buses"]) - 1
    r = c.post(f"/api/sessions/{sid}/model/element", json={"type": "dc", "params": {"bus": nb, "name": "DC_ISO"}}).json()
    assert any("没有任何电源" in e for e in r["validation"]["errors"])
    assert c.post(f"/api/sessions/{sid}/model/rerun", json={"ac": False}).status_code == 400
    assert c.post(f"/api/sessions/{sid}/model/layout", json={"positions": {"b0": [0.1, 0.2]}}).json()["ok"]
    g = c.get(f"/api/sessions/{sid}/model/edit").json()["graph"]; assert g["buses"][0]["x"] == 0.1 and g["buses"][0]["y"] == 0.2

def test_edit_then_rerun_compare_and_agent_sees_edit():
    j = _init(preset="helinger_typical_noBJ"); sid = j["session_id"]
    r0 = c.post(f"/api/sessions/{sid}/model/rerun", json={"ac": False}).json(); base_cost = r0["after"]["总成本 元"]
    c.patch(f"/api/sessions/{sid}/model/element/re/0", json={"cap_mw": 450})
    r = c.post(f"/api/sessions/{sid}/model/rerun", json={"ac": True}).json()
    cmp = {x["metric"]: x for x in r["compare"]}
    assert cmp["总成本 元"]["before"] == base_cost and cmp["外网购电 MWh"]["after"] < cmp["外网购电 MWh"]["before"]
    assert cmp["新能源占比 %"]["after"] > cmp["新能源占比 %"]["before"] and r["ac"]["converged"] and r["graph"]["solved"]
    # 导出 / 加载 JSON
    sj = c.get(f"/api/sessions/{sid}/model/scenario.json").json(); assert sj["pv"][0]["cap_mw"] == 450
    sj["pv"][0]["cap_mw"] = 300; assert c.post(f"/api/sessions/{sid}/model/load", json=sj).status_code == 200
    # 智能体对话：收到编辑同步，build_scenario 保留编辑后模型
    r = c.post("/api/chat", json={"message": "帮我优化调度并分析", "session_id": sid}).json()
    from app.main import SESSIONS
    s = SESSIONS[sid]
    assert any(m["role"] == "system" and "模型编辑同步" in (m.get("content") or "") for m in s.messages)
    assert s.state["scenario"].pv[0].cap_mw == 300 and s.state["scenario"].name.startswith("helinger")
