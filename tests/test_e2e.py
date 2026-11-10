import os, json
os.environ["LLM_MOCK"] = "1"
from fastapi.testclient import TestClient
from app.main import app
from app.agent import run_turn
from app.tools import Session

REQ = "三个数据中心，加50MWh储能，峰谷电价，帮我优化调度并分析"

def test_chat_e2e(tmp_path):
    c = TestClient(app); r = c.post("/chat", json={"message": REQ}).json()
    calls = [m["name"] for m in r["messages"] if m["role"] == "tool"]
    assert calls == ["build_scenario", "run_dispatch", "run_dispatch", "run_ac_check", "compute_kpis",
                     "compare_baseline", "make_plots", "write_report"]
    args = json.loads([m for m in r["messages"] if m.get("tool_calls")][0]["tool_calls"][0]["function"]["arguments"])
    assert args == {"n_dc": 3, "storage_mwh": 50.0, "price_kind": "peak_valley"}
    names = {a["name"] for a in r["artifacts"]}; assert "report.md" in names
    rep = c.get(f"/artifacts/{r['session_id']}/report.md"); assert rep.status_code == 200 and "储能" in rep.text
    assert c.get(f"/artifacts/{r['session_id']}/../../app/main.py").status_code == 404
    print("\nREPLY", r["reply"], "\nARTIFACTS", sorted(names))
    print(rep.text[:3000])

def test_fix_loop(tmp_path):
    s = Session("fix", str(tmp_path))
    msgs = run_turn(s, "三个数据中心，加50MWh储能，接在99号母线，峰谷电价")
    tools = [(m["name"], json.loads(m["content"])["ok"]) for m in msgs if m["role"] == "tool"]
    print("\nFIX", tools[:3], json.loads([m for m in msgs if m["role"] == "tool"][0]["content"])["error"])
    assert tools[0] == ("build_scenario", False) and tools[1] == ("build_scenario", True)
    assert os.path.exists(tmp_path / "report.md")

def test_kb_and_cards(tmp_path):
    c = TestClient(app)
    p = os.path.join(os.path.dirname(__file__), "data", "ess_guide.md")
    d = c.post("/api/kb/docs", files={"file": ("ess_guide.md", open(p, "rb"))}).json(); assert d["n_chunks"] >= 1
    r = c.post("/api/chat", json={"message": "根据知识库，储能SOC约束一般怎么设置？"}).json()
    assert r["citations"] == ["ess_guide.md#0"] and "10%–95%" in r["reply"]
    card = c.post("/api/cards", json={"title": "t", "steps": "run_matpower", "keywords": "x"}).json()
    assert c.put(f"/api/cards/{card['id']}", json={"title": "t2", "steps": "run_matpower"}).json()["title"] == "t2"
    assert c.delete(f"/api/cards/{card['id']}").json()["ok"]
    assert c.delete(f"/api/kb/docs/{d['id']}").json()["ok"]
