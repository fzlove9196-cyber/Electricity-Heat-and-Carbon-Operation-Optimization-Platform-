"""透明化工作流 API：参数表、数学模型、运行日志、确认暂停、结果解释、可复现运行包。"""
import io, json, os, subprocess, sys, zipfile
from fastapi.testclient import TestClient
from app.main import app
c = TestClient(app)

def _init(preset="zhongwei_summer_highwind"):
    r = c.post("/api/sessions/new/model/init", json={"preset": preset}).json(); return r["session_id"]

def test_param_sheet_groups_and_sources():
    sid = _init(); p = c.get(f"/api/sessions/{sid}/params").json()
    names = [g["name"] for g in p["groups"]]
    assert names == ["网络", "能源配置", "蓄能配置", "数据中心与算力负荷", "电价与碳", "约束", "求解器"]
    items = [i for g in p["groups"] for i in g["items"]]
    assert all({"name", "meaning", "value", "unit", "range", "source"} <= set(i) for i in items)
    assert any(i["source"] == "公开资料" and i["link"] for i in items)       # 案例 sources 中带 URL
    assert any(i["source"] == "案例假设" for i in items)
    assert p["confirmed"] is False and not p["errors"]

def test_param_edit_marks_user_and_validates():
    sid = _init(); p = c.patch(f"/api/sessions/{sid}/params", json={"path": "storage.0.energy_mwh", "value": 300}).json()
    it = next(i for g in p["groups"] for i in g["items"] if i["path"] == "storage.0.energy_mwh")
    assert it["value"] == 300 and it["source"] == "用户指定"
    r = c.patch(f"/api/sessions/{sid}/params", json={"path": "storage.0.soc0", "value": 5}); assert r.status_code == 400 and "修改失败" in r.text
    r = c.patch(f"/api/sessions/{sid}/params", json={"path": "solver.time_limit_s", "value": 30}); assert r.status_code == 200

def test_agent_infers_and_pauses_for_confirmation():
    r = c.post("/api/chat", json={"message": "三个数据中心，加50MWh储能，峰谷电价，帮我优化调度并分析", "auto_run": False}).json()
    sid = r["session_id"]; types = [e["type"] for e in r["events"]]
    assert "confirm_needed" in types and not any(e.get("name") == "run_dispatch" and e["type"] == "tool_end" for e in r["events"])
    p = c.get(f"/api/sessions/{sid}/params").json()
    inferred = [i for g in p["groups"] for i in g["items"] if i["source"] == "智能体推断"]
    assert any(i["path"].startswith("storage") for i in inferred) and p["source_counts"]["默认值"] > 0
    w = c.get(f"/api/sessions/{sid}/workflow").json(); assert w["current"] == "params" and "run_dispatch" in w["pending"]
    assert c.post(f"/api/sessions/{sid}/workflow/run?stream=0").status_code == 400     # 未确认不能运行
    c.post(f"/api/sessions/{sid}/workflow/confirm", json={})
    out = c.post(f"/api/sessions/{sid}/workflow/run?stream=0").json(); assert out["ok"], out["events"][-1]
    log = c.get(f"/api/sessions/{sid}/runlog").json()
    tools = [e["tool"] for e in log["log"]]
    assert tools[0] == "build_scenario" and "confirm" in tools and "run_ac_check" in tools and "attribution" in tools
    assert all(e.get("why") for e in log["log"]) and log["solver"]["optimized"]["status"] == "optimal"
    # 自动运行：不暂停
    r2 = c.post("/api/chat", json={"message": "三个数据中心，加50MWh储能，帮我优化调度", "auto_run": True}).json()
    assert "confirm_needed" not in [e["type"] for e in r2["events"]]

def test_formulation_reflects_scenario():
    sid = _init("zhongwei_summer_highwind_jobs40"); f = c.get(f"/api/sessions/{sid}/formulation").json()
    act = {x["id"]: x["active"] for x in f["constraints"]}
    assert act["job"] and not act["batch"] and act["sto"] and act["bal"]
    assert {o["id"]: o["active"] for o in f["objective"]}["uns"] and f["size"] is None
    c.post(f"/api/sessions/{sid}/workflow/confirm", json={})
    c.put(f"/api/sessions/{sid}/solver", json={"cfg": {"attribution": False, "ac_check": False}})
    assert c.post(f"/api/sessions/{sid}/workflow/run?stream=0").json()["ok"]
    f = c.get(f"/api/sessions/{sid}/formulation").json(); assert f["size"]["n_vars"] > 100 and f["size"]["n_constraints"] > 100

def test_results_explain_and_export_reproduces(tmp_path):
    sid = _init(); c.post(f"/api/sessions/{sid}/workflow/confirm", json={})
    assert c.post(f"/api/sessions/{sid}/workflow/run?stream=0").json()["ok"]
    r = c.get(f"/api/sessions/{sid}/results").json()
    assert r["ok"] and any(k["key"] == "total_objective_cny" and k["formula"] and k["baseline"] is not None for k in r["kpis"])
    a = r["attribution"]; assert abs(sum(p["saving"] for p in a["parts"]) - a["total_saving"]) < 1.0 and a["text"]
    assert r["warnings"] and r["series"]["optimized"]["dc_total"]
    z = c.get(f"/api/sessions/{sid}/export.zip"); assert z.status_code == 200
    zf = zipfile.ZipFile(io.BytesIO(z.content)); names = set(zf.namelist())
    assert {"scenario.json", "params.json", "formulation.json", "runlog.json", "results.json", "reproduce.py", "solver_config.json"} <= names
    zf.extractall(tmp_path)
    p = subprocess.run([sys.executable, str(tmp_path / "reproduce.py")], capture_output=True, text=True, timeout=300,
                       env={**os.environ, "SIM_AGENT_ROOT": os.path.dirname(os.path.dirname(os.path.abspath(__file__)))})
    assert p.returncode == 0, p.stderr[-800:]
    rep = json.loads(p.stdout.strip().splitlines()[-1])["reproduced_objective"]
    exp = json.loads(zf.read("results.json"))["objective"]
    for k in exp: assert abs(rep[k] - exp[k]) <= 1e-6*max(1, abs(exp[k]))
