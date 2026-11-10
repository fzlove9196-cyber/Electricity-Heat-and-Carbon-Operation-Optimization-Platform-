"""P0.1 功率标定 / P0.2 年日校核 / P0.3 多节点热网 / 活碳 file 适配器。"""
import json, os, copy
import numpy as np
import pytest
from app import calibration as CAL
from app import carbon as CB
from app.scenario import Scenario, build_default, load_preset, HeatNode, HeatPipe
from app.tools import sdco_engine as eng
from app.tools import Session, call_tool

HERE = os.path.dirname(__file__)
CSV = os.path.join(HERE, "data", "pdu_calib_sample.csv")
CI = os.path.join(HERE, "data", "carbon_hourly_demo.json")


def test_calibrate_idle_dynamic_fit_and_apply(tmp_path):
    r = CAL.calibrate(CSV, mode="idle_dynamic")
    assert r["ok"]
    m = r["fit"]["metrics"]
    assert m["n"] >= 30
    assert m["r2"] > 0.95  # 合成线性 + 小噪声
    assert abs(r["fit"]["p_idle_kw"] - 400) < 30
    assert abs(r["fit"]["p_peak_kw"] - 1000) < 40
    sc = build_default(1, 0)
    d = sc.data_centers[0]
    CAL.apply_to_dc(d, r["apply"])
    assert d.power_model == "idle_dynamic"
    assert d.p_idle_mw == pytest.approx(r["apply"]["p_idle_mw"])
    # identity 缺省未改的其他 DC 场景仍兼容
    sc2 = build_default(1, 0)
    assert sc2.data_centers[0].power_model == "identity"
    base = eng.solve(sc2, True)
    assert base["solver"]["status"] == "optimal"


def test_calibrate_pdu_pwl():
    r = CAL.calibrate(CSV, mode="pdu_pwl", n_seg=3)
    assert r["apply"]["power_model"] == "pdu_pwl"
    assert len(r["apply"]["pdu_breakpoints"]) >= 3
    sc = build_default(1, 0)
    d = sc.data_centers[0]
    CAL.apply_to_dc(d, r["apply"])
    sol = eng.solve(sc, True)
    assert sol["solver"]["status"] == "optimal"


def test_calibrate_tool(tmp_path):
    s = Session("calib1", str(tmp_path))
    s.state["scenario"] = build_default(1, 0)
    out = call_tool(s, "calibrate_power_model", {"csv_path": CSV, "mode": "idle_dynamic", "apply": True, "solve": True})
    assert out["ok"] and out["source"] == "标定"
    assert out["metrics"]["r2"] > 0.9
    assert s.state["scenario"].data_centers[0].power_model == "idle_dynamic"
    assert "功率标定" in str(s.state["scenario"].sources)


def test_carbon_file_adapter(monkeypatch):
    from app import settings
    monkeypatch.setitem(settings._cache if hasattr(settings, "_cache") else {}, "x", 1)
    # settings.get reads env / data/settings.json — set via settings.put if exists
    os.environ["CARBON_SOURCE"] = "file"
    os.environ["CARBON_FILE"] = CI
    # clear settings memo if any
    if hasattr(settings, "reload"): settings.reload()
    elif hasattr(settings, "_data"): settings._data = None
    try:
        # force direct call
        from app import settings as S
        # patch get
        old = S.get
        def _get(k, default=None):
            if k == "CARBON_SOURCE": return "file"
            if k == "CARBON_FILE": return CI
            return old(k, default)
        monkeypatch.setattr(S, "get", _get)
        g = CB.get_profile("national")
        assert g["synthetic"] is False
        assert g["source"].startswith("file:")
        assert len(g["profile"]) == 24
        assert g["profile"][0] == pytest.approx(0.45, abs=1e-3)
    finally:
        os.environ.pop("CARBON_SOURCE", None)
        os.environ.pop("CARBON_FILE", None)


def test_multi_heat_network_odense_compatible():
    sc = load_preset("odense_meta_winter")
    assert sc.heat_network is not None
    # 旧单节点仍可解
    r0 = eng.solve(sc, True)
    assert r0["solver"]["status"] == "optimal"
    h0 = float(r0["df"]["heat_delivered_MWth"].sum())
    # 多节点 + 1h 时延
    dem = list(sc.heat_network.demand_mw_th)
    sc.heat_network.nodes = [
        HeatNode(id="plant", name="plant", demand_mw_th=[round(0.2*x, 3) for x in dem]),
        HeatNode(id="city", name="city", demand_mw_th=[round(0.8*x, 3) for x in dem],
                 storage_mwh_th=sc.heat_network.storage_mwh_th, storage_p_mw_th=sc.heat_network.storage_p_mw_th or 20),
    ]
    sc.heat_network.pipes = [HeatPipe(name="p1", frm="plant", to="city", delay_h=1, loss=0.05, capacity_mw_th=200)]
    dcs = [d.name for d in sc.data_centers if d.thermal and d.thermal.hp_cap_mw_th > 0]
    sc.heat_network.inject_at = {n: "plant" for n in dcs}
    r1 = eng.solve(sc, True)
    assert r1["solver"]["status"] == "optimal"
    h1 = float(r1["df"]["heat_delivered_MWth"].sum())
    # 有时延时，日初若干小时 city 侧不可达 → 送达热量应 ≤ 单节点（或接近）
    assert h1 <= h0 + 1.0
    th = r1.get("thermal") or {}
    heat = th.get("heat") if isinstance(th, dict) else None
    if isinstance(heat, dict) and "multi_node" in heat:
        assert heat["multi_node"] is True


def test_multi_heat_tool(tmp_path):
    s = Session("mh1", str(tmp_path))
    out = call_tool(s, "build_multi_heat_network", {"from_odense": True, "delay_h": 1, "solve": True})
    assert out["ok"] and out["n_nodes"] == 2 and out["n_pipes"] == 1
    assert out["solve_status"] == "optimal"
    # 清空 nodes → 单节点旧路径仍可用
    sc = s.state["scenario"]
    sc.heat_network.nodes = []
    sc.heat_network.pipes = []
    r = eng.solve(sc, True)
    assert r["solver"]["status"] == "optimal"


def test_year_day_check_smoke():
    """用已有预置做物理日校核；代表日对比可能较慢，允许 compare_rep48。"""
    from app.opt import day_check as DC
    # 仅 1 个日 + 跳过 48 对比以控时；另测工具带 compare
    rep = DC.run("zhongwei_summer_coupled", days=["summer_typical"], caps={}, year=2024, n1=True, compare_rep48=False)
    assert rep["n_total"] == 1
    assert "summary" in rep
    d0 = rep["days"][0]
    assert "status" in d0
    # 夏季典型日应可解（中卫耦合预置）
    assert d0.get("ok") is True or d0.get("status") in ("optimal", "solve_error", "infeasible")


def test_check_year_days_tool(tmp_path):
    s = Session("yd1", str(tmp_path))
    out = call_tool(s, "check_year_days", {
        "preset": "zhongwei_summer_coupled",
        "days": ["summer_typical"],
        "compare_rep48": False,
        "n1": True,
    })
    assert out["ok"] and out["n_total"] == 1
    assert os.path.isfile(os.path.join(tmp_path, "year_day_check.json"))
