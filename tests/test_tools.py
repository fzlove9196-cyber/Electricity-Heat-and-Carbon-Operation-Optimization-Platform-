import os, tempfile, pytest
from app.tools import Session, call_tool, REGISTRY

def S(): return Session("t", tempfile.mkdtemp())

def test_registry():
    assert set(REGISTRY) >= {"build_scenario", "run_dispatch", "run_ac_check", "compute_kpis",
                             "make_plots", "compare_baseline", "write_report"}

def test_pipeline_with_storage():
    s = S()
    assert call_tool(s, "build_scenario", {"n_dc": 3, "storage_mwh": 50})["ok"]
    o = call_tool(s, "run_dispatch", {"case": "optimized"}); b = call_tool(s, "run_dispatch", {"case": "baseline"})
    assert o["objective_cny"] < b["objective_cny"]
    ac = call_tool(s, "run_ac_check", {}); assert ac["converged"]
    k = call_tool(s, "compute_kpis", {})["kpis"]; assert k["ESS_1_throughput_mwh"] > 0
    c = call_tool(s, "compare_baseline", {}); assert c["saving_pct"] > 0
    call_tool(s, "make_plots", {}); call_tool(s, "write_report", {})
    for f in ["report.md", "storage_ESS_1.png", "cost_compare.png", "dispatch_optimized.csv"]:
        assert os.path.exists(os.path.join(s.artifact_dir, f))
    print("\nKPI", k, "\nSAVING", c["saving_pct"], c["saving_cny"], "\nAC", ac)

def test_storage_adds_value():
    r = {}
    for e in (0, 50):
        s = S(); call_tool(s, "build_scenario", {"storage_mwh": e}); r[e] = call_tool(s, "run_dispatch", {})["objective_cny"]
    print("\nno-ESS", r[0], "ESS50", r[50]); assert r[50] < r[0]

def test_bad_scenario_errors():
    with pytest.raises(ValueError): call_tool(S(), "build_scenario", {"storage_mwh": 50, "storage_bus": 99})
    with pytest.raises(RuntimeError): call_tool(S(), "run_dispatch", {})
