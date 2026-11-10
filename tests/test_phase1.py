"""Phase 1：碳感知双目标 / Pareto / 任务级作业与迁移约束 / trace 加载 / 向后兼容 / Mock 路由。"""
import json, os, tempfile
import pytest
from app.tools import Session, call_tool
from app.tools import sdco_engine as eng
from app.scenario import Scenario, build_default, Job, Link, carbon_profile
from app.carbon import synthetic_profile, NATIONAL_FACTOR
from app.llm import route
from app.agent import run_turn

HERE = os.path.dirname(__file__)
def S(): return Session("p1", tempfile.mkdtemp())

def test_carbon_profile_default():
    p = synthetic_profile()
    assert len(p) == 24 and abs(sum(p)/24 - NATIONAL_FACTOR) < 1e-3
    assert min(p[10:15]) < NATIONAL_FACTOR < max(p[18:22])     # 午间低、晚高峰高（合成形状）

def test_old_scenario_json_backward_compatible():
    old = json.load(open(os.path.join(HERE, "data", "old_scenario_v0.json")))
    sc = Scenario.model_validate(old)
    assert sc.carbon_weight == 0 and sc.jobs == [] and sc.links == []
    r_new = eng.solve(sc, True)
    assert r_new["cost_cny"] == pytest.approx(r_new["objective"])   # w=0 时目标与旧版一致
    assert r_new["emissions_t"] > 0

def test_carbon_weight_reduces_emissions():
    sc = build_default(3, 50); r0 = eng.solve(sc, True)
    sc.carbon_weight = 20; r1 = eng.solve(sc, True)
    print("\nw=0", r0["cost_cny"], r0["emissions_t"], "w=20", r1["cost_cny"], r1["emissions_t"])
    assert r1["emissions_t"] < r0["emissions_t"] and r1["cost_cny"] >= r0["cost_cny"] - 1

def test_generation_accounting_and_multi_region():
    s = S(); call_tool(s, "build_scenario", {"carbon_accounting": "generation", "multi_region": True, "carbon_weight": 5})
    sc = s.state["scenario"]; assert sc.bus_region.get(13) == "west_synthetic"
    assert abs(carbon_profile(sc, 13).mean() - 0.42) < 1e-3
    r = call_tool(s, "run_dispatch", {}); assert r["emissions_tco2"] > 0
    cp = call_tool(s, "get_carbon_profile", {}); assert len(cp["profiles"]) == 3 and cp["echarts"]

def test_pareto_sweep_monotone():
    s = S(); call_tool(s, "build_scenario", {"storage_mwh": 50, "n_jobs": 30})
    r = call_tool(s, "run_pareto_sweep", {"weights": [0, 2, 10, 50]})
    pts = r["points"]; print("\nPARETO", pts, r["tradeoff"])
    em = [p["emissions_tco2"] for p in pts]; cost = [p["cost_cny"] for p in pts]
    assert all(a >= b - 1e-6 for a, b in zip(em, em[1:])), em          # 权重↑ 排放不增
    assert all(a <= b + 1 for a, b in zip(cost, cost[1:])), cost        # 权重↑ 成本不降
    assert em[-1] < em[0]
    for f in ["pareto.png", "pareto.csv", "pareto_echarts.json"]: assert os.path.exists(os.path.join(s.artifact_dir, f))
    opt = json.load(open(os.path.join(s.artifact_dir, "pareto_echarts.json"))); assert opt["series"][0]["type"] == "line"

def test_jobs_deadlines_and_migration_constraints():
    sc = build_default(3, 0, n_jobs=30); assert not eng.validate(sc)
    r = eng.solve(sc, True); j = r["jobs"]; lk = r["links"]
    assert j.met_deadline.all()
    # 每个任务只在 [release, deadline) 内运行
    df = r["df"]
    for jb in sc.jobs:
        row = j[j.job == jb.id].iloc[0]
        if row.finish_hour is not None: assert row.finish_hour <= jb.deadline
    # 带宽上限
    assert (lk.mw <= lk.cap_mw + 1e-6).all()
    # 时延敏感任务不得经由超出其时延上限的链路迁移
    L = eng.link_map(sc)
    for jb in sc.jobs:
        if jb.max_latency_ms is None: continue
        sites = j[j.job == jb.id].iloc[0].sites.split(",")
        for st in sites:
            if st and st != jb.dc: assert L[(jb.dc, st)].latency_ms <= jb.max_latency_ms
    # 迁移能耗 = κ × 迁移量
    assert r["mig_energy_mwh"] == pytest.approx(sc.mig_energy_mwh_per_mwh*j.migrated_mwh.sum(), rel=1e-4, abs=1e-6)
    print("\nJOBS met", j.met_deadline.mean(), "migrated", j.migrated_mwh.sum(), "mig_energy", r["mig_energy_mwh"], "link max", (lk.mw/lk.cap_mw).max())

def test_latency_blocks_migration_and_bandwidth_binds():
    sc = build_default(2, 0)
    sc.links = [Link(a="DC_A", b="DC_B", latency_ms=50, bw_mw=0.5)]
    sc.jobs = [Job(id="sens", dc="DC_A", release=17, deadline=22, energy_mwh=10, max_mw=4, max_latency_ms=10),
               Job(id="flex", dc="DC_A", release=17, deadline=22, energy_mwh=10, max_mw=4)]
    sc.mig_energy_mwh_per_mwh = 0.05
    r = eng.solve(sc, True); j = r["jobs"].set_index("job"); lk = r["links"]
    assert j.loc["sens", "migrated_mwh"] == 0
    assert (lk.mw <= 0.5 + 1e-6).all()

def test_infeasible_deadline_reported_as_unserved():
    sc = build_default(1, 0)
    sc.jobs = [Job(id="big", dc="DC_A", release=0, deadline=2, energy_mwh=50, max_mw=25)]   # 超过 IT 余量（约 2×20 MWh）
    r = eng.solve(sc, True); row = r["jobs"].iloc[0]
    assert not row.met_deadline and row.unserved_mwh > 0

def test_validate_job_errors():
    with pytest.raises(ValueError):
        call_tool(S(), "build_scenario", {"scenario": build_default(3).model_dump() | {"jobs": [
            dict(id="x", dc="DC_Z", release=5, deadline=3, energy_mwh=1, max_mw=1)]}})

def test_generate_jobs_and_kpis_tool():
    s = S(); call_tool(s, "build_scenario", {"storage_mwh": 50})
    g = call_tool(s, "generate_jobs", {"n_jobs": 20, "seed": 7}); assert g["n_jobs"] >= 20 and g["links"]
    call_tool(s, "run_dispatch", {"case": "optimized"}); call_tool(s, "run_dispatch", {"case": "baseline"})
    k = call_tool(s, "compute_kpis", {})["kpis"]
    assert k["jobs_deadline_met_pct"] == 100 and "emissions_tco2" in k and "migration_energy_mwh" in k
    c = call_tool(s, "compare_baseline", {}); assert "emissions_reduction_pct" in c
    p = call_tool(s, "make_plots", {}); assert "jobs_windows.png" in p["artifacts"] and "carbon_emissions.png" in p["artifacts"]
    call_tool(s, "write_report", {}); rep = open(os.path.join(s.artifact_dir, "report.md")).read()
    assert "截止前完成率" in rep and "tCO₂" in rep

@pytest.mark.parametrize("fmt,fname", [("alibaba_gpu", "sample_synthetic_pai_task_table.csv"), ("azure_llm", "sample_synthetic_azure_llm.csv")])
def test_trace_loaders(fmt, fname):
    s = S(); call_tool(s, "build_scenario", {})
    r = call_tool(s, "load_job_trace", {"path": os.path.join(HERE, "data", fname), "format": fmt, "target_mwh": 120})
    assert r["n_jobs"] > 0 and abs(r["total_energy_mwh"] - 120) < 1
    d = call_tool(s, "run_dispatch", {}); print("\n", fmt, r["n_jobs"], d.get("jobs_deadline_met_pct"))
    assert d["ok"] and "jobs_deadline_met_pct" in d

@pytest.mark.parametrize("text,must", [
    ("碳感知调度，碳价100元每吨，帮我优化", ["get_carbon_profile"]),
    ("做一下成本和碳排放的Pareto分析", ["run_pareto_sweep"]),
    ("30个任务，带截止时间，帮我优化调度", ["build_scenario"]),
])
def test_mock_routing_phase1(text, must):
    plan = route(text); names = [p[0] for p in plan]
    for m in must: assert m in names
    msgs = run_turn(S(), text); tools = [m for m in msgs if m["role"] == "tool"]
    assert all('"ok": true' in m["content"] for m in tools), [m["content"][:300] for m in tools]
    if "任务" in text: assert plan[0][1].get("n_jobs") == 30
    if "碳价" in text: assert plan[0][1].get("carbon_price_cny_t") == 100
