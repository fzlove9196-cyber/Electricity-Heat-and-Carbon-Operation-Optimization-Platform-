import os, tempfile
os.environ["LLM_MOCK"] = "1"
import pytest
from app.tools import Session, call_tool
from app.agent import run_turn
from app.llm import route

def S(): return Session("m", tempfile.mkdtemp())

def test_matpower():
    r = call_tool(S(), "run_matpower", {"case": "case14", "mode": "runopf"}); print("\nMATPOWER", r)
    assert r["ok"] and abs(r["f"] - 8081.5) < 1
    assert call_tool(S(), "run_matpower", {"case": "case30", "mode": "runpf"})["ok"]

def test_andes():
    r = call_tool(S(), "run_andes_tds", {"step_mw": 50}); print("\nANDES", r)
    assert r["converged"] and r["f_min_hz"] < 60

def test_opendss():
    a = call_tool(S(), "run_opendss", {}); b = call_tool(S(), "run_opendss", {"storage_kwh": 4000})
    print("\nOPENDSS", a, "\n+ESS", b); assert a["vmin_pu"] < 1.0

def test_openmodelica_default():
    r = call_tool(S(), "run_openmodelica", {"step_pu": 0.1}); print("\nOM", r["summary"])
    assert r["ok"] and r["summary"]["df"]["min"] < 0

def test_openmodelica_powersystems():
    r = call_tool(S(), "run_openmodelica", {"model_name": "PowerSystems.Examples.PowerWorld.PowerWorld", "stop_time": 60})
    print("\nOM-PS", list(r["summary"])[:4]); assert r["n_points"] > 100

def test_paraview():
    s = S(); call_tool(s, "build_scenario", {}); call_tool(s, "run_dispatch", {}); call_tool(s, "run_ac_check", {})
    r = call_tool(s, "run_paraview_render", {}); print("\nPV", r); assert r["ok"]

@pytest.mark.parametrize("text,first", [
    ("用MATPOWER跑一下case30的潮流", "run_matpower"),
    ("数据中心负荷突增80MW，做暂态稳定仿真看频率", "run_andes_tds"),
    ("10kV配网馈线接入数据中心5000kW，加储能4000kWh，看电压", "run_opendss"),
    ("用OpenModelica仿真数据中心负荷阶跃0.2pu的频率响应", "run_openmodelica"),
    ("三个数据中心，加50MWh储能，峰谷电价，帮我优化调度并分析", "build_scenario")])
def test_routing_and_agent(text, first):
    plan = route(text); assert plan[0][0] == first
    msgs = run_turn(S(), text); tools = [m for m in msgs if m["role"] == "tool"]
    assert [m["name"] for m in tools] == [p[0] for p in plan]
    assert all('"ok": true' in m["content"] for m in tools), [m["content"][:300] for m in tools]
    print("\n", text, "->", [p for p in plan])
