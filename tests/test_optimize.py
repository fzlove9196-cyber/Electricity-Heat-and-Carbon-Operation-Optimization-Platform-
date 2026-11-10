"""全年 8760h / 逐时边际碳因子 / 需求驱动寻优（规格解析、ε-约束帕累托、对偶解释、边际减排成本、编排器与工具集成）。"""
import os, tempfile, numpy as np, pytest
from app.opt import annual as A, carbon as CB, engine as E, nl, schema as SC
from app.tools import Session, call_tool

@pytest.fixture(scope="module")
def odense(): return A.build_case("odense_meta_winter")

@pytest.fixture(scope="module")
def ulq(): return A.build_case("ulanqab_cicdata_summer")

def new(): return Session(id="o" + os.urandom(4).hex(), artifact_dir=tempfile.mkdtemp())

def test_marginal_factor_properties(ulq):
    m = ulq["ef_marg"]; assert m.size == 8760 and 0 <= m.min() and m.max() <= 1.0
    assert m.std() > 0.05                                  # 逐时变化
    hi_w = ulq["wind_cf"] > np.quantile(ulq["wind_cf"], .9); lo_w = ulq["wind_cf"] <= np.quantile(ulq["wind_cf"], .1)
    assert m[hi_w].mean() < m[lo_w].mean()                 # 大风时边际排放更低（新能源/高效煤电在边际）
    avg = A.build_case("ulanqab_cicdata_summer", carbon_basis="average")["ef"]; assert np.ptp(avg) == 0

def test_full_year_8760_solves_and_kpis(odense):
    M = A.build(odense, k=None); r = A.solve(M, A.objective_vec(M, "cost")); assert r["status"] == "optimal" and M["N"] == 8760
    K = A.kpis(M, r["x"]); assert 1.03 < K["pue"] < 1.4 and K["heat_mwh"] > 1e4 and 0 <= K["green_share"] <= 1 and K["grid_mwh"] > 0

def test_cluster_weights_and_reduction_error(odense):
    reps, w, lab = A.cluster(odense, 24); assert w.sum() == 365 and len(reps) == 24 and lab.max() == 23
    reps, w, lab = A.cluster(odense, 24, "medoid+ext"); assert w.sum() == 365
    Mf = A.build(odense); Mr = A.build(odense, k=24)
    cf = A.obj_value(Mf, "cost", A.solve(Mf, A.objective_vec(Mf, "cost"))["x"]); cr = A.obj_value(Mr, "cost", A.solve(Mr, A.objective_vec(Mr, "cost"))["x"])
    assert abs(cr - cf)/cf < 0.05

def test_storage_interday_linking_allows_seasonal_shift(odense):
    # 代表日 + 日间链接：电池日末荷电可以跨日结转（S 变量非恒定）
    c = dict(odense); M = A.build(c, k=12, plan={"bat_e": 500, "bat_p": 100}); r = A.solve(M, A.objective_vec(M, "carbon"))
    S = r["x"][M["lp"].names["bat_S"]]; assert r["status"] == "optimal" and S.size == 365

def test_carbon_price_changes_dispatch_only_with_marginal():
    # 欧登塞（热泵+电网，灵活性大）：边际口径下碳价把购电挪到低边际排放时段 → 购电的边际排放强度下降；平均口径下强度基本不变
    inten = {}
    for basis in ("marginal", "average"):
        v = []
        for cp in (0.0, 300.0):
            c = A.build_case("odense_meta_winter", carbon_basis=basis, carbon_price=cp); M = A.build(c, k=24)
            K = A.kpis(M, A.solve(M, A.objective_vec(M, "cost"))["x"]); v.append(K["emis_marg_t"]/K["grid_mwh"])
        inten[basis] = (v[0] - v[1])/v[0]
    print(inten); assert inten["marginal"] > 0.01 and inten["marginal"] > 3*abs(inten["average"])

def test_pareto_front_tags_duals_and_abatement():
    sp = E.default_spec("odense_meta_winter"); sp["resolution"] = 12; sp["pareto"]["n"] = 5; sp["verify_full"] = False
    r = E.run(sp); F = r["front"]; assert len(F) >= 3
    xs = [p["x"] for p in F]; ys = [p["y"] for p in F]
    assert xs == sorted(xs) and all(ys[i] >= ys[i + 1] - 1e-3 for i in range(len(ys) - 1))
    tags = {p.get("tag") for p in F}; assert {"cost_opt", "carbon_opt"} <= tags
    assert all(p["eps_dual"] is None or p["eps_dual"] >= -1e-6 for p in F) and all(p["why"] for p in F)
    a = E.abatement(r, 0.1); assert a["ok"] and a["d_cost"] >= -1 and a["d_carbon"] > 0 and a["marginal_mac"] >= 0

def test_constraints_green_payback_lexicographic():
    sp = E.default_spec("ulanqab_cicdata_summer"); sp.update(resolution=12, mode="single", objectives=[dict(key="cost")], constraints=[dict(key="green", value=0.9)], verify_full=False)
    s = E.run(sp)["schemes"][0]; assert s["kpi"]["green_share"] >= 0.9 - 1e-4 and s["kpi"]["caps"]
    sp["constraints"] = [dict(key="payback", value=5)]; s = E.run(sp)["schemes"][0]
    assert s["kpi"].get("payback_y") is None or s["kpi"]["payback_y"] <= 5 + 1e-3
    sp.update(mode="lexicographic", objectives=[dict(key="carbon", priority=1), dict(key="cost", priority=2)], constraints=[])
    lx = E.run(sp)["schemes"][0]; sp.update(mode="single", objectives=[dict(key="carbon")]); c1 = E.run(sp)["schemes"][0]
    assert lx["kpi"]["carbon_net_t"] <= c1["kpi"]["carbon_net_t"]*1.01 + 1 and lx["kpi"]["cost_total"] <= c1["kpi"]["cost_total"] + 1

def test_cooling_mode_enumeration_and_thermal_margin():
    sp = E.default_spec("shaoguan_summer"); sp.update(resolution=12, mode="single", objectives=[dict(key="cost")], cooling_modes=["air_chw", "air_iec"], verify_full=False)
    s = E.run(sp)["schemes"][0]; assert s["mode"] in ("air_chw", "air_iec")
    sp.update(cooling_modes=[], objectives=[dict(key="thermal_margin")], constraints=[dict(key="cost", value=E.run({**sp, "objectives": [dict(key="cost")]})["schemes"][0]["kpi"]["cost_total"]*1.02)])
    sp["decisions"]["chiller"] = True; s = E.run(sp)["schemes"][0]; assert s["kpi"]["margin"] > 0 and "chiller_0" in s["kpi"]["caps"]

def test_nl_parse_chinese():
    sp, _ = nl.parse("乌兰察布项目，我想看经济性最优和碳排放最优的方案，以及中间的折中"); assert sp["preset"].startswith("ulanqab") and sp["mode"] == "pareto" and sp["pareto"]["x"] == "cost"
    sp, _ = nl.parse("韶关：成本最低，绿电不低于90%，回收期不超过8年"); assert sp["mode"] == "single" and {c["key"] for c in sp["constraints"]} == {"green", "payback"}
    sp, _ = nl.parse("欧登塞 先保证碳排放最低，其次成本"); assert sp["mode"] == "lexicographic" and sp["objectives"][0]["key"] == "carbon"
    sp, _ = nl.parse("中卫 成本权重0.7 碳权重0.3 加权寻优，不新增风电，碳价300"); assert sp["mode"] == "weighted" and sp["decisions"]["wind"] is False and sp["carbon_price"] == 300
    assert [o["weight"] for o in sp["objectives"]] == [0.7, 0.3]
    sp2, _ = nl.parse("去掉绿电约束，改用平均碳因子", {**sp, "constraints": [dict(key="green", value=0.9)]}); assert sp2["constraints"] == [] and sp2["carbon_basis"] == "average"
    assert nl.followup("再降10%碳要多花多少钱") == ("abate", 0.1) and nl.followup("查看方案3") == ("show", "方案3")
    assert not nl.is_opt("中卫夏季热浪下保障热安全同时参与需求响应的最优方案")

def test_schema_validate():
    sp, err = SC.validate({"preset": "odense_meta_winter", "mode": "pareto", "objectives": [{"key": "cost"}, {"key": "bogus"}], "constraints": [{"key": "green", "value": 0.5}]})
    assert err and sp["pareto"]["x"] == "cost" and sp["constraints"][0]["key"] == "green"

def test_tools_function_calling_path():
    s = new(); r = call_tool(s, "submit_objective_spec", {"text": "欧登塞 成本和碳排放的帕累托 12个代表日 4个点"}); assert r["ok"] and r["spec"]["resolution"] == 12
    s.state["opt_spec"]["verify_full"] = False
    r = call_tool(s, "run_optimization", {}); assert r["ok"] and r["n_points"] >= 2
    r = call_tool(s, "query_abatement", {"pct": 0.05}); assert "d_cost" in r or "msg" in r
    from app.llm import route
    assert [n for n, _ in route("中卫 寻优：成本最优，绿电不低于95%")] == ["submit_objective_spec", "run_optimization"]

def test_orchestrator_chat_flow():
    from app.research import orchestrator as O
    s = new(); t = "欧登塞 寻优：成本和碳排放的帕累托前沿 12个代表日 4个点"
    assert O.route(s, t)
    ev = list(O.chat_events(s, t)); kinds = [e["card"]["kind"] for e in ev if e["type"] == "opt_card"]
    assert kinds == ["spec", "result"] and any(e["type"] == "progress" for e in ev) and any(e["type"] == "message" for e in ev)
    assert O.route(s, "再降10%碳要多花多少钱")
    ev = list(O.chat_events(s, "再降10%碳要多花多少钱")); assert any(e["type"] == "opt_card" and e["card"]["kind"] == "abate" for e in ev)
    ev = list(O.chat_events(s, "为什么选折中方案")) if any(p.get("tag") == "knee" for p in s.state["opt_result"]["front"]) else list(O.chat_events(s, "查看方案1"))
    assert any(e["type"] == "message" for e in ev)
    import json; sp = dict(s.state["opt_spec"]); sp["mode"] = "single"; sp["objectives"] = [{"key": "cost"}]
    ev = list(O.chat_events(s, "【目标规格】" + json.dumps(sp, ensure_ascii=False))); assert [e["card"]["kind"] for e in ev if e["type"] == "opt_card"] == ["spec", "result"]
