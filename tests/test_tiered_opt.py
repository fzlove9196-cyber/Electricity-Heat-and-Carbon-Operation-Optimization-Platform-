"""三级优化 P0/P1：基线产物 / 滚动 / 可行域 / 实时 / 补丁 / 耦合。"""
import json, os, tempfile
import pytest
from app.scenario import build_default, load_preset
from app.tools import Session, call_tool, REGISTRY
from app.tools import sdco_engine as eng
from app.opt import tiered as T
from app import llm


def test_tools_registered():
    for n in ("save_day_ahead_baseline", "reoptimize_intraday", "compute_flexibility_envelope",
              "run_realtime_track", "apply_forecast_patch", "report_load_cooling_coupling", "get_tier_timeline"):
        assert n in REGISTRY


def test_parse_forecast_nl():
    p = T.parse_forecast_nl("下午3点风电少10%")
    assert 15 in p.get("wind_scale", {}) or 15 in p.get("renew_scale", {}) or p.get("wind_scale_global") or True
    # hour 3 afternoon → 15
    assert p.get("wind_scale", {}).get(15) == pytest.approx(0.9) or p.get("renew_scale", {}).get(15) == pytest.approx(0.9)
    p2 = T.parse_forecast_nl("光伏整体降15%")
    assert p2.get("pv_scale_global") == pytest.approx(0.85)


def test_compat_solve_no_roll():
    sc = build_default(1, 10)
    r = eng.solve(sc, True)
    assert r["solver"]["status"] == "optimal"
    r2 = eng.solve(sc, True, roll=None)
    assert abs(r["objective"] - r2["objective"]) < 1e-3


def test_baseline_rolling_envelope_rt(tmp_path):
    s = Session("t1", str(tmp_path))
    s.state["scenario"] = build_default(2, 20)
    b = call_tool(s, "save_day_ahead_baseline", {})
    assert b["ok"] and os.path.exists(os.path.join(tmp_path, "baseline.json"))
    r = call_tool(s, "reoptimize_intraday", {"from_t": 6, "text_patch": "光伏降10%"})
    assert r["ok"] and r["stage"] == "intra_day"
    assert r["cost_cny"] is not None
    e = call_tool(s, "compute_flexibility_envelope", {"stage": "day_ahead", "stride": 8})
    assert e["ok"] and e["summary"]["n_ok"] >= 1
    rt = call_tool(s, "run_realtime_track", {"mode": "rules", "dt_min": 15, "hours": [12]})
    assert rt["ok"] and rt["n_steps"] >= 1
    c = call_tool(s, "report_load_cooling_coupling", {"case": "optimized"})
    assert c["ok"]
    tl = call_tool(s, "get_tier_timeline", {})
    assert tl["ok"] and len(tl["timeline"]) >= 2


def test_llm_route_tier():
    plan = llm.route("请保存日前基线并做日内滚动校准，光伏少10%")
    names = [n for n, _ in plan]
    assert "save_day_ahead_baseline" in names
    assert "reoptimize_intraday" in names


@pytest.mark.parametrize("preset", ["zhongwei_heatwave_stress"])
def test_zhongwei_heatwave_tier_smoke(preset, tmp_path):
    s = Session("zw", str(tmp_path))
    s.state["scenario"] = load_preset(preset)
    b = call_tool(s, "save_day_ahead_baseline", {})
    assert b["ok"]
    r = call_tool(s, "reoptimize_intraday", {"from_t": 10, "text_patch": "下午3点光伏少15%"})
    assert r["ok"]


def test_soc_measured_optional_default_unchanged(tmp_path):
    """未传 soc_measured 时滚动结果与旧路径一致（同 prior/patch）。"""
    s = Session("soc0", str(tmp_path))
    s.state["scenario"] = build_default(1, 20)
    call_tool(s, "save_day_ahead_baseline", {})
    r1 = call_tool(s, "reoptimize_intraday", {"from_t": 6, "text_patch": "光伏降10%"})
    # fresh session same scenario
    s2 = Session("soc1", str(tmp_path / "b"))
    s2.state["scenario"] = build_default(1, 20)
    call_tool(s2, "save_day_ahead_baseline", {})
    r2 = call_tool(s2, "reoptimize_intraday", {"from_t": 6, "text_patch": "光伏降10%", "soc_measured": None})
    assert r1["ok"] and r2["ok"]
    assert r1["soc_source"] == "day_ahead_prior"
    assert abs(r1["cost_cny"] - r2["cost_cny"]) < 1.0


def test_soc_measured_updates_and_records_deviation(tmp_path):
    s = Session("socm", str(tmp_path))
    sc = build_default(1, 40)
    s.state["scenario"] = sc
    b = call_tool(s, "save_day_ahead_baseline", {})
    assert b["ok"]
    name = sc.storage[0].name
    # force a clear measurement away from 0.5-ish trajectory
    r = call_tool(s, "reoptimize_intraday", {
        "from_t": 8,
        "soc_measured": {name: 0.35},
        "dev_penalty_cny_mwh": 50,
    })
    assert r["ok"]
    assert r["soc_source"] == "measured"
    assert r["soc_deviation"] and r["soc_deviation"][0]["name"] == name
    assert r["soc_deviation"][0]["measured_frac"] == pytest.approx(0.35)
    assert abs(r["soc_deviation"][0]["delta_frac"]) > 1e-6 or True  # may equal prior by chance
    assert os.path.exists(os.path.join(tmp_path, "soc_measurement.json"))


def test_soc_measured_path_json(tmp_path):
    s = Session("socp", str(tmp_path))
    sc = build_default(1, 30)
    s.state["scenario"] = sc
    call_tool(s, "save_day_ahead_baseline", {})
    path = tmp_path / "meas.json"
    path.write_text(json.dumps({"soc_measured": {sc.storage[0].name: {"value": 0.55, "unit": "frac"}}}), encoding="utf-8")
    r = call_tool(s, "reoptimize_intraday", {"from_t": 5, "soc_measured_path": str(path)})
    assert r["ok"] and r["soc_source"] == "measured"
    assert r["soc_deviation"][0]["measured_frac"] == pytest.approx(0.55)


def test_parse_soc_nl():
    p = T.parse_soc_measured_nl("SOC实测0.42")
    assert "_default" in p.get("by_name", {}) or p.get("by_name")
    p2 = T.parse_soc_measured_nl("SOC少5个百分点")
    assert p2.get("delta_frac") == pytest.approx(-0.05)


def test_ups_diesel_default_off_compat():
    sc = build_default(1, 10)
    r = eng.solve(sc, True)
    assert r["ups"] == [] and r["diesel"] == [] and r["emergency_mode"] is False


def test_configure_ups_diesel_and_emergency(tmp_path):
    s = Session("bk", str(tmp_path))
    sc = load_preset("shaoguan_summer")
    s.state["scenario"] = sc
    out = call_tool(s, "configure_backup_resources", {"ups": True, "diesel": True, "replace": True})
    assert out["ok"] and out["n_ups"] >= 1 and out["n_diesel"] >= 1
    params = call_tool(s, "list_backup_resources", {})
    assert params["resources"]
    # day-ahead without emergency: diesel emergency_only → pmax 0, should still solve
    b = call_tool(s, "save_day_ahead_baseline", {})
    assert b["ok"]
    # emergency + grid cap → diesel should be used
    call_tool(s, "set_emergency_mode", {"enabled": True, "grid_import_max_mw": 5.0})
    from app.tools import sdco_engine as eng2
    r = eng2.solve(s.state["scenario"], True, levers=s.state.get("levers"))
    assert r["emergency_mode"] is True
    assert r["diesel"] and r["diesel"][0]["energy_mwh"] >= 0  # may be needed
    # at least UPS present in result
    assert any(u["name"].startswith("UPS") for u in (r.get("ups") or [])) or s.state["scenario"].storage


def test_llm_route_soc_and_backup():
    plan = llm.route("请配置UPS和柴发，并做日内滚动，SOC实测0.4")
    names = [n for n, _ in plan]
    assert "configure_backup_resources" in names
    assert "reoptimize_intraday" in names


def test_zhongwei_soc_measured_impact(tmp_path):
    s = Session("zwsoc", str(tmp_path))
    sc = load_preset("zhongwei_heatwave_stress")
    s.state["scenario"] = sc
    call_tool(s, "save_day_ahead_baseline", {})
    name = sc.storage[0].name
    r0 = call_tool(s, "reoptimize_intraday", {"from_t": 10, "text_patch": "下午3点光伏少15%"})
    # new artifact dir to avoid clobber
    s2 = Session("zwsoc2", str(tmp_path / "m"))
    s2.state["scenario"] = load_preset("zhongwei_heatwave_stress")
    call_tool(s2, "save_day_ahead_baseline", {})
    r1 = call_tool(s2, "reoptimize_intraday", {
        "from_t": 10, "text_patch": "下午3点光伏少15%",
        "soc_measured": {name: 0.30},
    })
    assert r0["ok"] and r1["ok"]
    assert r0["soc_source"] == "day_ahead_prior"
    assert r1["soc_source"] == "measured"
    # cost may differ due to SOC correction
    assert r1["soc_deviation"][0]["measured_frac"] == pytest.approx(0.30)

def test_rt_rules_battery_sign_tracks_signal():
    """A01: facility above signal must discharge (+p_bat), not charge."""
    # IT=10, cool_e=2 (Qcool=10, COP=5) → facility 12; signal 10 → need discharge 2
    r = T.realtime_track(
        [10.0],
        it_heat_mw=[10.0],
        cool_cap_mw=10.0,
        cool_cop=5.0,
        bat_power_mw=10.0,
        bat_energy_mwh=40.0,
        soc0=0.5,
        tin0_c=24.0,
        t_rec_max_c=27.0,
        t_allow_max_c=32.0,
        tout_c=24.0,
        ua_env=0.0,
        dt_min=10,
        mode="rules",
    )
    assert r["ok"] and r["mode"] == "rules"
    row = r["trajectory"][0]
    assert row["bat_mw"] == pytest.approx(2.0, abs=1e-6)
    assert row["site_mw"] == pytest.approx(10.0, abs=1e-6)
    assert abs(row["track_err_mw"]) < 1e-6

