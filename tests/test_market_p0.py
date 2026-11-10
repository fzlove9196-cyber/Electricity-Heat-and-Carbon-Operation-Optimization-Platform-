"""P0 运营沙盘：台账/规则包不可混用/日前MILP申报+检查/审批/出清/日内/实时分解/DR/结算/审计/IO/API/对话。"""
import json
import numpy as np
import pytest
from fastapi.testclient import TestClient
from app.market import core as M, store
from app.tools import REGISTRY, Session, call_tool
from app import llm

@pytest.fixture(scope="module")
def loops():
    return {k: M.run_closed_loop("pf-" + k) for k in ("zhongwei", "ulanqab", "shaoguan")}

def test_rules_are_demo_and_labeled():
    rs = M.list_rules(); assert {"demo_ningxia", "demo_mengxi", "demo_guangdong"} <= {r["id"] for r in rs}
    assert all(r["official"] is False and "假设" in r["label"] for r in rs)

def test_portfolio_excludes_cross_province():
    p = M.portfolio_from_case("zhongwei")
    assert p["rule_id"] == "demo_ningxia"
    assert all(r["province"] == "ningxia" for r in p["resources"])
    assert {e["name"] for e in p["excluded"]} >= {"SH_EAST"}
    types = {r["type"] for r in p["resources"]}; assert types == {"dc", "ess", "ups", "diesel"}

def test_rule_mixing_rejected():
    res, _, _ = M.resources_from_case("shaoguan")
    with pytest.raises(M.MarketError, match="不可混用"):
        M.create_portfolio("mix", "demo_ningxia", res, pid="pf-mixtest")

def test_exclusive_account_binding():
    M.portfolio_from_case("ulanqab")
    res, _, _ = M.resources_from_case("ulanqab")
    with pytest.raises(M.MarketError, match="独占"):
        M.create_portfolio("dup", "demo_mengxi", res, pid="pf-dup")

def test_capability_thermal():
    cap = M.capability(M.get_portfolio("pf-zhongwei"))
    dc = [r for r in cap["resources"] if r["type"] == "dc"]
    assert dc and all(r["cooling_inertia_mwh_th"] > 0 and r["thermal_cap_it_mw_min"] > 0 for r in dc)
    dg = [r for r in cap["resources"] if r["type"] == "diesel"]; assert dg and not dg[0]["market_allowed"]

def test_dayahead_milp_and_check():
    p = M.get_portfolio("pf-shaoguan"); pr = M.prices(p)
    plan = M.optimize(p, pr["forecast"]); assert plan["ok"] and plan["n_int"] > 0
    for k, v in plan["per"].items():
        if v["type"] == "dc": assert all(v["it_mw"][t] <= v["thermal_cap_it_mw"][t] + 1e-6 for t in range(24))
        if v["type"] == "diesel": assert sum(v["p_mw"]) == 0   # 示范规则禁止柴发参与市场
    dcs = [r for r in p["resources"] if r["type"] == "dc"]
    for d in dcs:   # 批处理能量守恒；受热安全容量限制时如实告警（韶关液冷 96 MWh > 可容纳 95.9）
        got = sum(plan["per"][d["id"]]["batch_mw"]); cap = sum(max(0, M._therm_cap(d, t) - d["interactive_mw"][t]) for t in range(24))
        assert got == pytest.approx(min(d["batch_mwh"], cap), abs=0.05)
        if cap < d["batch_mwh"]: assert any(d["name"] in w for w in plan["warnings"])
    bid = M.build_bid(p, plan, pr["forecast"]); chk = M.check_bid(p, bid, pr["forecast"])
    assert chk["feasible"], chk["issues"]
    for h in bid["hours"]:
        ps = [s["p"] for s in h["segments"]]; assert ps == sorted(ps, reverse=True) and len(ps) <= 3

def test_infeasible_bid_detected():
    p = M.get_portfolio("pf-shaoguan"); pr = M.prices(p)
    plan = M.optimize(p, pr["forecast"]); bid = M.build_bid(p, plan, pr["forecast"])
    bid["hours"][12]["segments"][0]["q_mw"] = 1e4; bid["hours"][12]["planned_mw"] = 1e4
    chk = M.check_bid(p, bid, pr["forecast"]); assert not chk["feasible"] and any("物理上限" in i for i in chk["issues"])

def test_optimized_beats_baseline():
    p = M.get_portfolio("pf-ulanqab"); pr = M.prices(p)
    assert M.optimize(p, pr["forecast"])["energy_cost_cny"] < M.optimize(p, pr["forecast"], baseline=True)["energy_cost_cny"]

def test_closed_loop_all_cases(loops):
    for k, o in loops.items():
        assert o["mode"] == "sandbox" and "不代表现场收益" in o["disclaimer"]
        assert o["day_ahead"]["check"]["feasible"]
        kp = o["kpi"]; assert kp["thermal_ok"] and kp["saving_cny"] > 0
        assert kp["abs_dev_pct"] < 5 and kp["dr_ratio"] > 0.5
        b = M.get_bid(o["day_ahead"]["bid_id"]); assert b["status"] == "settled"
        assert [h["to"] for h in b["history"]] == ["draft", "submitted", "approved", "sandbox_cleared", "settled"]
        assert o["p1_p2_not_done"]

def test_intraday_limits(loops):
    o = loops["zhongwei"]; rule = M.get_rule(o["rule"]); q_da = o["day_ahead"]["cleared_mw"]; q_id = o["intra_day"]["q_id"]
    lim = rule["intraday_adjust_max_pct"] / 100
    for t in range(24):
        assert abs(q_id[t] - q_da[t]) <= lim * q_da[t] + 1e-6
        if t in o["intra_day"]["check"]["locked_hours"]: assert q_id[t] == q_da[t]

def test_realtime_decomposition_order_and_thermal(loops):
    for o in loops.values():
        dec = o["real_time"]["decomposition"]
        assert dec["thermal_ok"] and not any(t["kind"] == "shortfall" for t in dec["tickets"])
        assert dec["max_rate_k_h"] <= 5.0
        assert not any(t["kind"] == "diesel" for t in dec["tickets"])

def test_decompose_shortfall_and_diesel_blocked():
    p = M.get_portfolio("pf-shaoguan"); pr = M.prices(p); plan = M.optimize(p, pr["forecast"])
    dec = M.decompose(p, plan, {"hours": [19], "mw": 500})
    sf = [t for t in dec["tickets"] if t["kind"] == "shortfall"]; assert sf and "柴发" in sf[0]["note"]

def test_dr_baseline_methods():
    hist = [[100.0 + d] * 24 for d in range(6)]
    assert M.dr_baseline(hist, "prior_n_days", [19], n_days=3)["baseline_mw"][0] == pytest.approx(104)
    assert M.dr_baseline(hist, "similar_days_avg", [19], n_days=5)["baseline_mw"][0] == pytest.approx(103)
    act = [110.0] * 24
    b = M.dr_baseline(hist, "adjusted_similar_days", [19], actual=act, n_days=5, adjust_window_h=2, adjust_cap_pct=5)
    assert b["adjust_ratio"] == pytest.approx(1.05) and b["adjust_window"]

def test_dr_assess_formula():
    r = M.get_rule("demo_guangdong")
    a = M.dr_assess(r, [100] * 24, [90] * 24, [19, 20], 10); assert a["valid"] and a["payment_cny"] == pytest.approx(1500 * 20)
    b = M.dr_assess(r, [100] * 24, [99] * 24, [19, 20], 10); assert b["payment_cny"] == 0 and b["penalty_cny"] == pytest.approx(300 * 18)

def test_settlement_identity():
    r = M.get_rule("demo_ningxia"); pr = {"da": [500] * 24, "id": [550] * 24, "rt": [600] * 24}
    s = M.settle(r, pr, [100] * 24, [100] * 24, [110] * 24)
    assert s["da_cny"] == 1_200_000 and s["rt_cny"] == pytest.approx(24 * 10 * 600)
    assert s["deviation_penalty_cny"] == pytest.approx(24 * 7 * 100)

def test_approval_flow_guards():
    p = M.get_portfolio("pf-shaoguan"); pr = M.prices(p); plan = M.optimize(p, pr["forecast"])
    bid = M.build_bid(p, plan, pr["forecast"]); b = M.save_bid(p, bid, M.check_bid(p, bid, pr["forecast"]), "alice")
    with pytest.raises(M.MarketError): M.transition(b["id"], "approved", "bob")        # 跳级
    M.transition(b["id"], "submitted", "alice")
    with pytest.raises(M.MarketError, match="四眼"): M.transition(b["id"], "approved", "alice")
    with pytest.raises(PermissionError, match="不可执行"): M.transition(b["id"], "external_submit", "bob")
    assert M.transition(b["id"], "approved", "bob")["status"] == "approved"
    acts = [a["action"] for a in store.audit_list(50, b["id"])]
    assert "bid.external_submit.refused" in acts and "bid.approved" in acts

def test_audit_chain_verifies():
    store.audit("test.ping", "pytest"); assert store.audit_verify()["ok"]

def test_io_roundtrip(tmp_path):
    o = M.run_closed_loop("pf-shaoguan")
    csvt = M.export_bid_csv(o["day_ahead"]["bid_id"]); assert "非真实" in csvt and csvt.count("\n") > 24
    x = M.export_bid_xlsx(o["day_ahead"]["bid_id"], str(tmp_path / "b.xlsx")); assert (tmp_path / "b.xlsx").exists()
    M.import_prices_csv("pf-shaoguan", "hour,price\n" + "\n".join(f"{t},{300 + t}" for t in range(24)))
    assert M.prices(M.get_portfolio("pf-shaoguan"))["forecast"][5] == 305
    hist = M.import_meter_csv("day,hour,mw\n" + "\n".join(f"{d},{t},{50 + d}" for d in range(3) for t in range(24)))
    assert len(hist) == 3 and hist[2][0] == 52
    d = store.load("portfolios.json", {}); d["pf-shaoguan"].pop("price_override"); store.save("portfolios.json", d)

def test_custom_rule():
    r = M.save_custom_rule({"id": "my_gd", "base": "demo_guangdong", "deviation_tolerance_pct": 2.0})
    assert r["official"] is False and r["province"] == "guangdong" and M.get_rule("my_gd")["deviation_tolerance_pct"] == 2.0

def test_api_endpoints():
    from app.main import app
    c = TestClient(app)
    assert c.get("/api/market/info").json()["real_trading"] is False
    assert c.post("/api/market/portfolios/from_case/shaoguan").status_code == 200
    assert c.get("/api/market/portfolios/pf-shaoguan/capability").status_code == 200
    r = c.post("/api/market/portfolios/pf-shaoguan/loop", json={"seed": 3}); assert r.status_code == 200
    bid = r.json()["day_ahead"]["bid_id"]
    assert c.post(f"/api/market/bids/{bid}/external_submit", json={}).status_code == 403
    assert c.post(f"/api/market/bids/{bid}/transition", json={"to": "draft"}).status_code == 400
    assert c.get(f"/api/market/bids/{bid}/export.csv").status_code == 200
    assert c.get(f"/api/market/bids/{bid}/export.xlsx").status_code == 200
    assert c.get("/api/market/audit/verify").json()["ok"]
    assert c.post("/api/market/portfolios/from_case/nope").status_code == 404
    assert "v-market" in c.get("/").text

def test_chat_tools_and_mock_route(tmp_path):
    for n in ("market_portfolio", "market_closed_loop", "market_bid_action", "market_audit"): assert n in REGISTRY
    plan = llm.route("运营沙盘：中卫、乌兰察布、韶关交易闭环")
    assert [x[1].get("case") for x in plan if x[0] == "market_closed_loop"] == ["zhongwei", "ulanqab", "shaoguan"]
    s = Session("mk", str(tmp_path)); out = call_tool(s, "market_closed_loop", {"case": "韶关"})
    assert out["ok"] and out["artifacts"]
    rf = call_tool(s, "market_bid_action", {"bid_id": out["day_ahead_bid"], "to": "external_submit"})
    assert rf["refused"]
    assert not llm.is_market("三级优化 日前基线")   # 不影响原有路由
