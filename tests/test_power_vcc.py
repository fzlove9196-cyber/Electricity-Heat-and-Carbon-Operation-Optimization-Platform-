"""Idle+dynamic / PDU PWL 功率模型 + Google 风格 VCC：向后兼容与功能测试。"""
import json, os, copy
import numpy as np
import pytest
from app.scenario import Scenario, build_default, load_preset, DataCenter
from app.tools import sdco_engine as eng
from app import power_model as pm
from app import vcc
from app import traces

HERE = os.path.dirname(__file__)
FP = "/tmp/baseline_fingerprint.json"

def _fp(r):
    return dict(obj=float(r["objective"]), cost=float(r["cost_cny"]), emis=float(r["emissions_t"]),
                nv=r["solver"]["n_vars"], nc=r["solver"]["n_constraints"])

@pytest.mark.parametrize("preset,key", [
    (None, "default"),
    ("zhongwei_summer_coupled", "zw"),
    ("ulanqab_cicdata_summer", "ulan"),
])
def test_backward_compatible_fingerprint(preset, key):
    """新字段缺省时，目标/成本/排放/规模与改动前指纹一致。"""
    if not os.path.isfile(FP):
        pytest.skip("no baseline fingerprint")
    base = json.load(open(FP))[key]
    sc = build_default(3, 50) if preset is None else load_preset(preset)
    assert sc.vcc_mode == "off"
    assert all(d.power_model == "identity" for d in sc.data_centers)
    r = eng.solve(sc, True)
    cur = _fp(r)
    for k in ("obj", "cost", "emis"):
        assert cur[k] == pytest.approx(base[k], rel=0, abs=1e-4), (k, cur[k], base[k])
    assert cur["nv"] == base["nv"] and cur["nc"] == base["nc"]
    assert r["vcc"] is None
    assert all(not info["hardware"] for info in r["power_model"].values())


def test_old_scenario_json_still_loads():
    old = json.load(open(os.path.join(HERE, "data", "old_scenario_v0.json")))
    sc = Scenario.model_validate(old)
    assert sc.vcc_mode == "off" and sc.data_centers[0].power_model == "identity"
    r = eng.solve(sc, True)
    assert r["solver"]["status"] == "optimal"


def test_idle_dynamic_affine_and_heat_uses_power():
    sc = build_default(1, 0)
    d = sc.data_centers[0]
    d.power_model = "idle_dynamic"
    d.p_idle_mw = 0.4 * d.cap_it_mw
    d.p_peak_mw = d.cap_it_mw
    assert not eng.validate(sc)
    r = eng.solve(sc, True)
    assert r["power_model"][d.name]["hardware"] is True
    df = r["df"]
    # 电气功率 = idle + (peak-idle)*work/cap
    for t in range(24):
        work = df.loc[t, f"{d.name}_IT_work_MW"]
        pit = df.loc[t, f"{d.name}_IT_MW"]
        expect = pm.eval_idle_dynamic(work, d.cap_it_mw, d.p_idle_mw, d.p_peak_mw)
        assert pit == pytest.approx(expect, abs=1e-5)
        assert pit >= d.p_idle_mw - 1e-6


def test_pdu_pwl_milp():
    sc = build_default(1, 0)
    d = sc.data_centers[0]
    d.power_model = "pdu_pwl"
    d.pdu_breakpoints = [
        {"util": 0.0, "power_mw": 0.4 * d.cap_it_mw},
        {"util": 0.5, "power_mw": 0.75 * d.cap_it_mw},
        {"util": 1.0, "power_mw": 1.0 * d.cap_it_mw},
    ]
    r = eng.solve(sc, True)
    assert "MILP" in r["solver"]["problem"]
    assert r["solver"]["status"] == "optimal"
    # 断点插值核对
    for t in range(24):
        work = r["df"].loc[t, f"{d.name}_IT_work_MW"]
        u = work / d.cap_it_mw
        assert r["df"].loc[t, f"{d.name}_IT_MW"] == pytest.approx(pm.eval_pwl(u, d.pdu_breakpoints), abs=1e-4)


def test_vcc_day_ahead_respects_cap_and_daily_energy():
    sc = build_default(2, 0)
    sc.vcc_mode = "carbon"
    sc.vcc_stage = "day_ahead"
    curves = vcc.day_ahead_all(sc)
    for d in sc.data_centers:
        cap = np.asarray(curves[d.name]["cap_mw"])
        assert cap.sum() == pytest.approx(d.batch_mwh, abs=1e-4)
        assert (cap <= np.asarray(vcc.residual_cap(d)) + 1e-6).all()
    r = eng.solve(sc, True)
    assert r["vcc"] is not None
    for d in sc.data_centers:
        cap = np.asarray(r["vcc"]["curves"][d.name]["cap_mw"])
        bt = r["df"][f"{d.name}_batch_IT"].values
        assert (bt <= cap + 1e-4).all()


def test_vcc_joint_emits_curve():
    sc = build_default(2, 0)
    sc.vcc_mode = "price"
    sc.vcc_stage = "joint"
    r = eng.solve(sc, True)
    assert r["vcc"]["dcs"][0]["stage"] == "joint"
    assert r["vcc"]["dcs"][0]["cap_sum_mwh"] == pytest.approx(sc.data_centers[0].batch_mwh, abs=1e-3)
    assert "vcc_shaping" in r["cost_terms"]


def test_vcc_off_matches_baseline_on_ulanqab():
    sc0 = load_preset("ulanqab_cicdata_summer")
    r0 = eng.solve(sc0, True)
    sc1 = load_preset("ulanqab_cicdata_summer")
    assert sc1.vcc_mode == "off"
    r1 = eng.solve(sc1, True)
    assert r0["objective"] == pytest.approx(r1["objective"], abs=1e-4)
    assert r0["emissions_t"] == pytest.approx(r1["emissions_t"], abs=1e-6)


def test_traces_util_to_power_identity_and_idle():
    sc = build_default(1, 0)
    d = sc.data_centers[0]
    util = np.linspace(0.2, 0.9, 24)
    p_id = traces.util_to_power_mw(util, d)
    assert p_id == pytest.approx((util * d.cap_it_mw).tolist(), abs=1e-6)
    d.power_model = "idle_dynamic"
    d.p_idle_mw, d.p_peak_mw = 5.0, d.cap_it_mw
    p_hw = traces.util_to_power_mw(util, d)
    assert p_hw[0] == pytest.approx(pm.eval_idle_dynamic(util[0]*d.cap_it_mw, d.cap_it_mw, 5.0, d.cap_it_mw), abs=1e-6)
    assert min(p_hw) >= 5.0 - 1e-6


def test_real_case_vcc_carbon_runs_zhongwei_shaoguan():
    """真实案例可解；报告碳/成本变化（不强制减排——信号与可再生/电价可能不完全对齐）。"""
    rows = []
    for name in ("zhongwei_summer_highwind", "ulanqab_cicdata_summer", "shaoguan_summer"):
        sc0 = load_preset(name); r0 = eng.solve(sc0, True)
        sc1 = load_preset(name); sc1.vcc_mode = "carbon"; sc1.vcc_stage = "day_ahead"
        r1 = eng.solve(sc1, True)
        rows.append(dict(case=name, emis0=r0["emissions_t"], emis1=r1["emissions_t"],
                         cost0=r0["cost_cny"], cost1=r1["cost_cny"],
                         status=r1["solver"]["status"]))
        assert r1["solver"]["status"] == "optimal"
        assert r1["vcc"] is not None
    print("\nVCC_REAL", rows)


def test_real_case_idle_dynamic_assumed_fan_params():
    """中卫耦合案例 + Fan 风格假设参数（idle=40% peak，peak=cap）可解；参数标注为假设。"""
    sc = load_preset("zhongwei_summer_coupled")
    for d in sc.data_centers:
        d.power_model = "idle_dynamic"
        d.p_peak_mw = d.cap_it_mw
        d.p_idle_mw = round(0.4 * d.cap_it_mw, 3)  # 【假设】Fan 2007 量级 idle 占比
    sc.sources = {**(sc.sources or {}), "功率模型": "【假设】idle=0.4×Cap、peak=Cap（Fan ISCA 2007 量级，未用本站 PDU 实测标定）"}
    assert not eng.validate(sc)
    r = eng.solve(sc, True)
    assert r["solver"]["status"] == "optimal"
    assert all(r["power_model"][d.name]["hardware"] for d in sc.data_centers)
    # 电气 IT 日电量应 ≥ 工作 IT 日电量的某一比例（idle>0）
    for d in sc.data_centers:
        work = r["df"][f"{d.name}_IT_work_MW"].sum()
        pit = r["df"][f"{d.name}_IT_MW"].sum()
        assert pit > work  # idle>0 时电气电气能量
