"""研究编排器：状态机、诊断、证据链接、what-if、知识沉淀、LLM 桥接（mock）。"""
import json, os, tempfile
import pytest
from app.tools import Session
from app.research import orchestrator as O, diagnostics as DG, experiments as EX, topics as TP, llm_bridge as LB
from app.scenario import load_preset

def drive(s, text):
    return list(O.chat_events(s, text, force=True))

def new():
    return Session(id="t" + os.urandom(4).hex(), artifact_dir=tempfile.mkdtemp())

@pytest.fixture(scope="module")
def heatwave():
    s = new(); drive(s, "中卫夏季热浪下保障热安全同时参与需求响应的最优方案")
    assert O.get(s)["state"] == "clarify"
    drive(s, "【澄清回答】q_firm=True; q_dr=40")
    assert O.get(s)["state"] == "plan"
    ev = drive(s, "【批准计划】")
    return s, ev

def test_formulate_and_clarify():
    s = new(); ev = drive(s, "中卫冬季想用余热供暖，看值不值，末端是地暖")
    st = O.get(s); assert st["topic"] == "heat_recovery" and st["state"] == "clarify"
    kinds = [e["card"]["kind"] for e in ev if e["type"] == "study_card"]; assert kinds == ["problem", "clarify"]
    q = next(x for x in st["questions"] if x["id"] == "q_terminal")
    assert q["answer"] == "floor" and q["source"]["tag"] == "用户指定" and q["source"]["msg"]["idx"] == 0   # 原话解析 + 消息引用
    pend = next(e for e in ev if e["type"] == "study_card" and e["card"]["kind"] == "clarify")["card"]["questions"]
    assert all(p["options"] and "default" in p for p in pend) and "q_terminal" not in [p["id"] for p in pend]
    drive(s, "【澄清回答】q_price=200")
    st = O.get(s); assert st["state"] == "plan" and st["model_mods"]["heat_network.price_cny_mwh_th"] == 200.0
    assert s.state["scenario"].heat_network.price_cny_mwh_th == 200.0
    ps = s.state["param_src"]["heat_network.price_cny_mwh_th"]; assert ps["tag"] == "用户指定" and ps["msg_ref"]["idx"] == 1
    assert s.state["param_src"]["heat_network.pipe_length_km"]["tag"] == "智能体推断"
    out = O.edit_plan(s, {"steps": [{"id": "P5", "enabled": False}, {"id": "P3", "values": [100, 150]}]})
    assert [v["mods"]["heat_network.price_cny_mwh_th"] for v in next(p for p in out["plan"] if p["id"] == "P3")["variants"]] == [100.0, 150.0]

def test_infeasible_diagnose_revise_loop(heatwave):
    s, ev = heatwave; st = O.get(s)
    assert st["state"] == "checkpoint"
    r2 = st["runs"]["R2"]; assert r2["status"] == "infeasible"
    assert any(f["code"] == "INFEAS_CAUSE" for f in r2["findings"])
    assert any(t["key"] == "dr_soft" and t["feasible"] for t in r2["infeasibility"]["tests"])
    k = st["checkpoints"][0]; assert k["recommend"] == "adopt_firm" and k["status"] == "open"
    firm = st["firm_dr"]["firm_mw"]; assert 0 < firm < 40
    drive(s, f"【检查点】{k['id']} adopt_firm")
    st = O.get(s); assert st["state"] == "done" and st["iter"]["revisions"] == 1
    assert st["model_mods"]["dr_events.0.request_mw"] == firm
    p2r = next(p for p in st["plan"] if p["id"] == "P2r"); assert p2r["added_by"] == "revise" and p2r["status"] == "done"
    m = TP.main_run(st); assert m["status"] == "optimal" and m["kpis"]["dr_delivered_mwh"] == pytest.approx(firm*3, rel=1e-3)
    assert s.state["param_src"]["dr_events.0.request_mw"]["note"].startswith("诊断修订")

def test_evidence_links(heatwave):
    s, _ = heatwave; st = O.get(s)
    assert len(st["conclusions"]) >= 4
    for c in st["conclusions"]:
        assert c["confidence"] in ("高", "中", "低") and c["assumptions"]
        for e in c["evidence"]:
            if e and e.get("run"): assert e["run"] in st["runs"]
            if e and e.get("metric") not in (None, "status") and e.get("run") in st["runs"] and st["runs"][e["run"]]["status"] == "optimal":
                assert st["runs"][e["run"]]["kpis"].get(e["metric"]) == e["value"]   # 结论数字 = 运行结果
    c2 = next(c for c in st["conclusions"] if "硬承诺上限" in c["text"]); assert f"{st['firm_dr']['firm_mw']:g} MW" in c2["text"]
    assert os.path.exists(os.path.join(s.artifact_dir, "study_report.md")) and os.path.exists(os.path.join(s.artifact_dir, "study_report.html"))
    md = open(os.path.join(s.artifact_dir, "study_report.md"), encoding="utf-8").read(); assert "证据" in md and "R2" in md

def test_why_and_whatif(heatwave):
    s, _ = heatwave
    ev = drive(s, "为什么 C2 成立？"); txt = [e["content"] for e in ev if e["type"] == "message"][-1]
    assert "影子价格" in txt and "收益归因" in txt
    ev = drive(s, "如果蓄冷翻倍会怎样"); st = O.get(s); w = st["whatifs"][-1]
    assert w["mods"]["data_centers.*.thermal.tes_mwh_th"] == {"op": "mul", "value": 2.0} and w["status"] == "optimal"
    r = st["runs"][w["run"]]; m = st["runs"][w["ref_run"]]
    row = next(x for x in w["rows"] if x["k"] == "cost_cny"); assert row["delta"] == pytest.approx(r["kpis"]["cost_cny"] - m["kpis"]["cost_cny"], abs=1e-3)
    assert "value" in w and any(e["type"] == "study_card" and e["card"]["kind"] == "whatif" for e in ev)
    ev = drive(s, "如果天上掉馅饼会怎样"); assert "没识别出" in [e["content"] for e in ev if e["type"] == "message"][-1]

def test_ui_edit_sync(heatwave):
    s, _ = heatwave
    from app import transparency as tr
    tr.set_param(s, "dr_events.0.price_cny_mwh", 2500.0)
    ev = drive(s, "如果削峰 15 MW 会怎样")
    assert any(e["type"] == "message" and "检测到你在界面修改" in e["content"] for e in ev)
    st = O.get(s); assert st["param_src"]["dr_events.0.price_cny_mwh"]["tag"] == "用户指定"
    assert st["runs"][st["whatifs"][-1]["run"]]["_sc"].dr_events[0].price_cny_mwh == 2500.0

def test_sediment_and_reuse(heatwave):
    s, _ = heatwave; st = O.get(s)
    ids = [x["id"] for x in st["sediment"]]; assert "S1" in ids and all(x["status"] == "proposed" for x in st["sediment"])
    drive(s, "【采纳沉淀】" + " ".join(ids))
    assert all(x["status"] == "saved" for x in O.get(s)["sediment"])
    from app import knowledge as kb
    assert any(c["title"] == "经验：热浪日 DR 硬承诺需先校核热安全可承诺上限" for c in kb.list_cards())
    s2 = new(); drive(s2, "中卫夏季热浪时参与晚高峰需求响应，怎么保障热安全？")
    assert any("热浪" in r["title"] or "DR" in r["title"] for r in O.get(s2)["references"])

def test_diagnostics_unit():
    st = {}; b = load_preset("zhongwei_winter_coupled_heat")
    r = EX.run_variant(st, b, "x", {"heat_network.terminal_type": "radiator", "heat_network.pipe_length_km": 5.0})
    codes = {f["code"]: f["level"] for f in r["findings"]}
    assert codes["SOLVER_OK"] == "ok" and codes["BALANCE"] == "ok" and codes["PUE_RANGE"] == "ok" and codes["HEAT_TERMINAL"] == "ok"
    assert any(f["code"] == "BINDING" for f in r["findings"]) and r["binding"][0]["n_binding"] > 0
    fake = dict(status="optimal", kpis=dict(pue_min=0.9, pue_max=1.2, pue_avg=1.0, thermal_margin_k=5), _sc=r["_sc"], _r={**r["_r"], "thermal": {**r["_r"]["thermal"], "violations": []}})
    assert any(f["code"] == "PUE_UNREAL" and f["level"] == "error" for f in DG.diagnose(fake))
    df = r["_r"]["df"].copy(); df.loc[3, "gen0_MW"] = 5.0; df.loc[3, "gen0_export_MW"] = 5.0
    fake2 = dict(status="optimal", kpis=r["kpis"], _sc=r["_sc"], _r={**r["_r"], "df": df})
    assert any(f["code"] == "SIM_BUY_SELL" for f in DG.diagnose(fake2))
    assert DG.diagnose(dict(status="infeasible", error="LP 求解失败: infeasible"))[0]["code"] == "INFEASIBLE"

def test_apply_mods_paths():
    b = load_preset("zhongwei_heatwave_stress")
    sc = EX.apply_mods(b, {"data_centers.*.thermal.tes_mwh_th": {"op": "mul", "value": 2.0}, "outdoor_temp_c": {"op": "add", "value": 1.0}, "outdoor_temp_profiles.*": {"op": "add", "value": 1.0}, "__no_dr__": 1})
    assert sc.dr_events == [] and sc.data_centers[1].thermal.tes_mwh_th == 2*b.data_centers[1].thermal.tes_mwh_th
    assert sc.outdoor_temp_c[0] == b.outdoor_temp_c[0] + 1
    with pytest.raises(ValueError): EX.apply_mods(b, {"no.such.path": 1})

def test_llm_bridge_mock_and_schema(monkeypatch):
    assert LB.is_mock() and LB.call("decide_next", "x", {}) is None
    for n, sp in LB.SCHEMAS.items():
        assert sp["parameters"]["type"] == "object" and sp["parameters"]["required"]
        json.dumps({"type": "function", "function": {"name": n, **sp}})
    # 伪造 OpenAI 兼容客户端：验证 function calling 解析路径
    class TC:
        def __init__(s): s.function = type("F", (), {"name": "decide_next", "arguments": json.dumps({"choice": "adopt_soft", "rationale": "测试"})})()
    class Cl:
        class chat:
            class completions:
                @staticmethod
                def create(**kw):
                    assert kw["tool_choice"]["function"]["name"] == "decide_next"
                    return type("R", (), {"choices": [type("C", (), {"message": type("M", (), {"tool_calls": [TC()], "content": None})()})()]})()
    import app.llm as L
    monkeypatch.setattr(LB, "is_mock", lambda: False)
    monkeypatch.setattr(L, "OpenAILLM", lambda: type("O", (), {"client": Cl, "model": "fake"})())
    assert LB.call("decide_next", "sys", {"a": 1}) == {"choice": "adopt_soft", "rationale": "测试"}

def test_route_legacy_unaffected():
    s = new()
    assert O.route(s, "中卫冬季余热供暖可行吗") is False   # 未开研究模式：仍走原智能体流程
    assert O.route(s, "中卫冬季余热供暖可行吗", force=True) is True
