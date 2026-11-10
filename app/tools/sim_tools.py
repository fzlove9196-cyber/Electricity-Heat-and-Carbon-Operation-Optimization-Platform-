"""算电协同仿真工具集。每个函数签名 fn(session, **json_args) -> dict，通过 @tool 注册。"""
from __future__ import annotations
import json, os
import numpy as np
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
from .base import tool, Session
from ..scenario import Scenario, build_default
from . import sdco_engine as eng

plt.rcParams["font.sans-serif"] = ["Noto Sans CJK SC", "WenQuanYi Micro Hei", "SimHei", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False

def _art(s: Session, fname: str) -> str:
    os.makedirs(s.artifact_dir, exist_ok=True)
    if fname not in s.artifacts: s.artifacts.append(fname)
    return os.path.join(s.artifact_dir, fname)

def _sc(s: Session) -> Scenario:
    if "scenario" not in s.state: raise RuntimeError("尚未构建场景，请先调用 build_scenario")
    return s.state["scenario"]

def _res(s: Session, case="optimized"):
    r = s.state.get("results", {}).get(case)
    if r is None: raise RuntimeError(f"缺少 {case} 调度结果，请先调用 run_dispatch(case='{case}')")
    return r

@tool("build_scenario", "构建/修改算电协同场景（IEEE14 + 数据中心 + 光伏 + 储能 + 电价）。默认数据为合成数据。"
      "可用快捷参数，或用 scenario 传入完整 JSON 覆盖。", {
    "type": "object", "properties": {
        "n_dc": {"type": "integer", "description": "数据中心数量 1-3", "default": 3},
        "storage_mwh": {"type": "number", "description": "储能容量 MWh，0 表示无储能", "default": 0},
        "storage_bus": {"type": "integer", "description": "储能接入母线(0-index)", "default": 4},
        "storage_power_mw": {"type": "number", "description": "储能功率 MW，缺省=容量/4"},
        "price_kind": {"type": "string", "enum": ["peak_valley", "flat"], "default": "peak_valley"},
        "load_scale": {"type": "number", "default": 1.0},
        "carbon_weight": {"type": "number", "description": "碳权重 w：目标=成本+w×碳价×排放（0=纯成本）"},
        "carbon_price_cny_t": {"type": "number", "description": "碳价 元/tCO2，默认 100"},
        "carbon_accounting": {"type": "string", "enum": ["location", "generation"], "description": "排放核算口径"},
        "multi_region": {"type": "boolean", "description": "DC_C 所在母线13设为合成“西部风电”区域（碳强度不同），体现空间迁移减碳"},
        "n_jobs": {"type": "integer", "description": ">0 时生成合成任务级作业（释放/截止时间/能量/功率/允许DC）并启用默认链路（时延/带宽/迁移能耗）"},
        "jobs_seed": {"type": "integer", "default": 42},
        "preset": {"type": "string", "description": "场景预设名（cases/ 下 JSON），如 zhongwei_summer_highwind / zhongwei_winter_lowwind / *_noSH（无上海迁移节点）/ zhongwei_summer_highwind_jobs40；适用于“宁夏中卫/大唐中卫云基地绿电直供”"},
        "scenario": {"type": "object", "description": "完整 Scenario JSON（可选，优先级最高）"},
        "thermal": {"type": "boolean", "description": "启用 算-电-热-碳 耦合（RC 热模型、冷机 COP 随室外温度、自然冷却、动态 PUE、热安全硬约束：入口温度/温变率/N+1/IT≤冷量）；预设 *_coupled* 已启用"},
        "tes": {"type": "boolean", "description": "为数据中心增加蓄冷罐（虚拟储冷，2h@0.4×IT）"},
        "heat_recovery": {"type": "boolean", "description": "余热回收：热泵（0.3×IT MW_th）向区域供热网售热（含热网虚拟储热），热碳抵扣"},
        "heatwave": {"type": "boolean", "description": "夏季热浪室外温度（25–39°C）热安全压力测试"},
        "dr_mw": {"type": "number", "description": "电网需求响应削峰要求 MW（默认 19–22 时，补偿 2000 元/MWh，基线=无 DR 优化计划）"},
        "dr_window": {"type": "array", "items": {"type": "integer"}, "description": "DR 时段 [start, end)"},
        "vcc_mode": {"type": "string", "enum": ["off", "carbon", "price", "weighted"], "description": "VCC 虚拟容量整形；缺省 off=旧行为"},
        "vcc_stage": {"type": "string", "enum": ["joint", "day_ahead"], "description": "VCC 阶段"},
        "power_model": {"type": "string", "enum": ["identity", "idle_dynamic", "pdu_pwl"], "description": "IT 硬件功率模型；缺省 identity"},
        "idle_frac": {"type": "number", "description": "idle_dynamic 时 P_idle=idle_frac×Cap（【假设】标定，默认 0.4）"}}})
def build_scenario(s: Session, n_dc=3, storage_mwh=0, storage_bus=4, storage_power_mw=None,
                   price_kind="peak_valley", load_scale=1.0, carbon_weight=None, carbon_price_cny_t=None,
                   carbon_accounting=None, multi_region=False, n_jobs=0, jobs_seed=42, scenario=None, preset=None,
                   thermal=False, tes=False, heat_recovery=False, heatwave=False, dr_mw=None, dr_window=None,
                   vcc_mode=None, vcc_stage=None, power_model=None, idle_frac=None):
    if scenario or preset: s.state["model_edited"] = False
    if scenario:
        sc = Scenario.model_validate(scenario)
    elif preset:
        from ..scenario import load_preset, generate_jobs as _gj
        sc = load_preset(preset)
        if storage_mwh and sc.storage: sc.storage[0].energy_mwh = storage_mwh; sc.storage[0].power_mw = storage_power_mw or storage_mwh/2
        if n_jobs and not sc.jobs: sc.jobs = _gj(sc, int(n_jobs), int(jobs_seed))
    elif (s.state.pop("preset", False) or s.state.get("model_edited")) and "scenario" in s.state:   # 前端参数面板预置 / 拓扑编辑器编辑后的场景
        sc = s.state["scenario"]
    else:
        sc = build_default(n_dc, storage_mwh, storage_bus, price_kind, n_jobs=int(n_jobs or 0), jobs_seed=int(jobs_seed), load_scale=load_scale)
        if storage_power_mw and sc.storage: sc.storage[0].power_mw = storage_power_mw
        if multi_region: _set_multi_region(sc)
        from ..carbon import get_profile
        cp = get_profile("national", sc.carbon_factor, sc.carbon_shape)
        sc.carbon_source = cp["source"]
        if not cp["synthetic"]: sc.carbon_profiles["national"] = cp["profile"]
    for k, v in dict(carbon_weight=carbon_weight, carbon_price_cny_t=carbon_price_cny_t, carbon_accounting=carbon_accounting).items():
        if v is not None: setattr(sc, k, v)
    if thermal or tes or heat_recovery or heatwave or dr_mw: _apply_thermal(sc, tes, heat_recovery, heatwave, dr_mw, dr_window)
    if vcc_mode: sc.vcc_mode = vcc_mode
    if vcc_stage: sc.vcc_stage = vcc_stage
    if power_model and power_model != "identity":
        frac = float(idle_frac if idle_frac is not None else 0.4)
        for d in sc.data_centers:
            d.power_model = power_model
            if power_model == "idle_dynamic":
                d.p_peak_mw = d.cap_it_mw; d.p_idle_mw = round(frac * d.cap_it_mw, 3)
            elif power_model == "pdu_pwl":
                d.pdu_breakpoints = [{"util": 0.0, "power_mw": round(frac*d.cap_it_mw, 3)},
                                     {"util": 0.5, "power_mw": round((frac+1)*0.5*d.cap_it_mw, 3)},
                                     {"util": 1.0, "power_mw": d.cap_it_mw}]
        sc.sources = {**(sc.sources or {}), "功率模型": f"【假设】power_model={power_model}, idle_frac={frac}（Fan/SPECpower 量级，未用本站 PDU 实测）"}
    if vcc_mode and vcc_mode != "off":
        sc.sources = {**(sc.sources or {}), "VCC": f"vcc_mode={sc.vcc_mode}, stage={sc.vcc_stage}（Google Carbon-Intelligent 风格容量整形）"}
    errs = eng.validate(sc)
    if errs: raise ValueError("场景校验失败: " + "; ".join(errs))
    s.state["scenario"] = sc; s.state["results"] = {}
    for k in ("compare", "ac", "attribution", "kpis"): s.state.pop(k, None)
    with open(_art(s, "scenario.json"), "w") as f: f.write(sc.model_dump_json(indent=2))
    mv = _model_view(s)
    return {"ok": True, "preset": preset, **mv, "summary": {"network": sc.network_case, "data_centers": [(d.name, d.bus, d.cap_it_mw) for d in sc.data_centers],
            "storage": [(x.name, x.bus, x.energy_mwh, x.power_mw) for x in sc.storage],
            "pv_mw": sum(p.cap_mw for p in sc.pv), "price_kind": sc.price_kind, "synthetic": sc.synthetic,
            "carbon": {"weight": sc.carbon_weight, "price_cny_t": sc.carbon_price_cny_t, "accounting": sc.carbon_accounting,
                       "source": sc.carbon_source, "regions": sorted(set(sc.bus_region.values()) | {"national"})},
            "jobs": len(sc.jobs), "links": [(l.a, l.b, l.latency_ms, l.bw_mw) for l in sc.links],
            "mig_energy_mwh_per_mwh": sc.mig_energy_mwh_per_mwh,
            "thermal_mode": sc.thermal_mode, "heat_network": bool(sc.heat_network), "dr_events": [(e.name, e.start, e.end, e.request_mw) for e in sc.dr_events]},
            "artifact": "scenario.json"}

def _apply_thermal(sc, tes=False, heat=False, heatwave=False, dr_mw=None, dr_window=None):
    """对任意场景开启 算-电-热-碳 耦合（预设已配置的保留原值；新增部分为合成/假设值）。"""
    import os as _o, sys as _s
    _s.path.insert(0, _o.path.join(_o.path.dirname(_o.path.dirname(_o.path.dirname(_o.path.abspath(__file__)))), "cases", "common"))
    from thermal_params import thermal_for, CLIMATE, heat_demand
    from ..scenario import DCThermal, HeatNetwork, DREvent
    sc.thermal_mode = "coupled"
    if heatwave: sc.outdoor_temp_c = CLIMATE["zhongwei_heatwave"]; sc.outdoor_temp_profiles = {}
    elif sc.outdoor_temp_c == [25.0]*24 and not sc.outdoor_temp_profiles: sc.outdoor_temp_c = CLIMATE["zhongwei_summer"]
    for d in sc.data_centers:
        if d.thermal is None: d.thermal = DCThermal(**thermal_for(d.cap_it_mw))
        if tes and d.thermal.tes_mwh_th <= 0: d.thermal.tes_mwh_th = round(0.8*d.cap_it_mw, 1); d.thermal.tes_p_mw_th = round(0.4*d.cap_it_mw, 1)
        if heat and d.thermal.hp_cap_mw_th <= 0: d.thermal.hp_cap_mw_th = round(0.3*d.cap_it_mw, 1)
    if heat and sc.heat_network is None:
        pk = round(0.5*sum(d.cap_it_mw for d in sc.data_centers), 1)
        sc.heat_network = HeatNetwork(name="区域供热网(合成)", demand_mw_th=heat_demand(pk), price_cny_mwh_th=120.0, storage_mwh_th=2*pk, storage_p_mw_th=round(pk/2, 1))
        if sc.outdoor_temp_c == CLIMATE["zhongwei_summer"]: sc.outdoor_temp_c = CLIMATE["zhongwei_winter"]
    if dr_mw:
        st, en = (dr_window or [19, 22])[:2]
        if sc.dr_events:
            sc.dr_events[0].request_mw = float(dr_mw)
            if dr_window: sc.dr_events[0].start, sc.dr_events[0].end = int(st), int(en)
        else: sc.dr_events = [DREvent(name="晚高峰削峰", start=int(st), end=int(en), request_mw=float(dr_mw), price_cny_mwh=2000.0)]
    sc.sources.setdefault("热参数(合成)", "【假设】由 build_scenario 按 IT 容量缩放生成（cases/common/thermal_params.py）")

def _model_view(s):
    """建模步骤自动生成“模型拓扑 + 能流”视图（失败不阻断主流程）。"""
    try:
        from .model_viz import refresh, brief
        g = refresh(s); b = brief(g)
        return {"model_view": "model_topology.json", "model_summary": b["summary"], "model_islands": b["islands"],
                "artifacts": ["model_topology.png", "model_topology.html", "model_topology.json"]}
    except Exception as e:
        return {"model_view_error": f"{type(e).__name__}: {e}"}

def _set_multi_region(sc):
    from ..carbon import synthetic_profile
    import numpy as _np
    h = _np.arange(24); wind = 1 + 0.25*_np.cos((h - 14)/24*2*_np.pi)   # 夜间风电多 -> 夜间低、午后高（合成）
    sc.carbon_profiles.setdefault("west_synthetic", [round(float(x), 4) for x in 0.42*(2 - wind)/(2 - wind).mean()])
    for d in sc.data_centers:
        if d.bus == 13: sc.bus_region[13] = "west_synthetic"

@tool("run_dispatch", "运行 24h 多时段 DC-OPF 调度 (Pyomo + HiGHS)。case=optimized: 批处理时移+跨DC迁移+储能；"
      "case=baseline: 批处理均匀、无迁移、无储能（任务模式：本地均匀运行）。可选 carbon_weight 覆盖场景碳权重（成本-碳双目标）。", {
    "type": "object", "properties": {"case": {"type": "string", "enum": ["optimized", "baseline"], "default": "optimized"},
                                     "carbon_weight": {"type": "number", "description": "目标=成本+w×碳价×排放"}}})
def run_dispatch(s: Session, case="optimized", carbon_weight=None):
    sc = _sc(s)
    if carbon_weight is not None: sc.carbon_weight = float(carbon_weight)
    cfg = s.state.get("solver_cfg") or {}
    r = eng.solve(sc, optimize=(case == "optimized"), solver_opts=dict(time_limit_s=cfg.get("time_limit_s")), levers=s.state.get("levers"))
    from ..foundation.service import code_identity
    from ..foundation.store import digest
    from datetime import datetime
    r["execution_context"] = dict(code_hash=code_identity(),input_model_hash=digest(json.loads(sc.model_dump_json())),input_model_hash_basis="canonical_export_json_v1",python_model_hash=digest(sc.model_dump()),executed_at=datetime.now().astimezone().isoformat(),time_zone="Asia/Shanghai",dt_hours=sc.dt_hours,objective_mode=sc.objective_mode,network_domain=sc.network_domain)
    s.state.setdefault("results", {})[case] = r; s.state.pop("attribution", None)
    from ..foundation.store import digest
    s.state["foundation_result_model_hash"] = digest(sc.model_dump())
    s.state["foundation_results_stale"] = False
    r["df"].to_csv(_art(s, f"dispatch_{case}.csv"), index=False)
    out = {"ok": True, "case": case, "objective_cny": round(r["objective"], 1), "cost_cny": round(r["cost_cny"], 1),
           "gen_cost_cny": round(r["gen_cost"], 1), "emissions_tco2": round(r["emissions_t"], 2), "carbon_weight": sc.carbon_weight,
           "pv_curtail_mwh": round(r["curtail_mwh"], 2), "solver_status": r["solver"]["status"], "solver_time_s": r["solver"]["time_s"],
           "n_vars": r["solver"]["n_vars"], "n_constraints": r["solver"]["n_constraints"], "artifact": f"dispatch_{case}.csv", "artifacts": [f"dispatch_{case}.csv"]}
    th = r.get("thermal")
    if th:
        D = th["dcs"]
        out.update(thermal_mode="coupled", thermal_safe=th["safe"], thermal_violations=th["violations"],
                   pue_range=[min(x["pue_min"] for x in D.values()), max(x["pue_max"] for x in D.values())],
                   tin_range_c=[min(x["tin_min_c"] for x in D.values()), max(x["tin_max_c"] for x in D.values())],
                   thermal_margin_k=min(x["margin_to_allow_k"] for x in D.values()),
                   binding_hours={d: x["binding_hours"] for d, x in D.items()},
                   balance_check=dict(thermal_max_residual=max(x["thermal_balance_max_residual"] for x in D.values()),
                                      elec_max_residual=max(x["elec_balance_max_residual"] for x in D.values()),
                                      heat_max_residual=(th.get("heat") or {}).get("balance_max_residual")))
        if th.get("heat"):
            out["heat"] = {k: th["heat"][k] for k in ("delivered_mwh", "revenue_cny", "carbon_offset_t")}
            if th["heat"].get("feasibility"): out["heat_feasibility"] = th["heat"]["feasibility"]
        out["cooling"] = {d: x.get("cooling") for d, x in D.items()}
    if r.get("dr"): out["dr"] = [{k: e[k] for k in ("name", "kind", "requested_mwh", "delivered_mwh", "revenue_cny")} for e in r["dr"]]
    mv = _model_view(s)
    if "model_view" in mv: out["model_view"] = mv["model_view"]; out["artifacts"] += ["model_topology.png", "model_topology.html"]
    if "jobs" in r:
        r["jobs"].to_csv(_art(s, f"jobs_{case}.csv"), index=False); r["links"].to_csv(_art(s, f"migration_{case}.csv"), index=False)
        out.update(jobs_deadline_met_pct=round(100*float(r["jobs"].met_deadline.mean()), 1),
                   jobs_unserved_mwh=round(float(r["jobs"].unserved_mwh.sum()), 3),
                   migrated_mwh=round(float(r["jobs"].migrated_mwh.sum()), 2))
        out["artifacts"] += [f"jobs_{case}.csv", f"migration_{case}.csv"]
    return out

@tool("run_ac_check", "用 pandapower 交流潮流校核调度结果（默认取总负荷峰值时刻）。", {
    "type": "object", "properties": {"hour": {"type": "number", "description": "物理小时，须对齐dt；空=峰值步"},
                                     "case": {"type": "string", "default": "optimized"}}})
def run_ac_check(s: Session, hour=None, case="optimized"):
    ac = eng.ac_check(_sc(s), _res(s, case), hour)
    s.state.setdefault("ac", {})[case] = ac; s.state["_vm"] = _res(s, case).get("_vm")
    with open(_art(s, f"ac_check_{case}.json"), "w") as f: json.dump(ac, f, indent=2)
    return {"ok": True, **ac}

def _kpis(sc, r):
    dt=r.get("solver",{}).get("resolution_h",1)
    df = r["df"]; dc = [c for c in df if c.endswith("_grid_MW")]
    dcE = dt*float(df[dc].sum().sum()); dc_cost = dt*float((df[dc].sum(axis=1)*df.price*1000).sum())
    k = dict(total_objective_cny=r["objective"], gen_cost_cny=r["gen_cost"], pv_curtail_mwh=r["curtail_mwh"],
             pv_util_pct=100*float(df.pv_used.sum()/max(df.pv_avail.sum(), 1e-9)),
             max_line_loading_pct=float(df.max_line_loading_pct.max()), dc_energy_mwh=dcE,
             dc_energy_cost_tou_cny=dc_cost, dc_avg_price_cny_kwh=dc_cost/dcE/1000 if dcE else 0,
             migrated_mwh=dt*float(df[[c for c in df if c.endswith("_mig_out")]].sum().sum()),
             dc_peak_mw=float(df[dc].sum(axis=1).max()),
             cost_cny=r.get("cost_cny", r["objective"]), emissions_tco2=r.get("emissions_t", 0.0),
             dc_emissions_location_tco2=float(df.emis_location_t.sum()) if "emis_location_t" in df else 0.0,
             system_emissions_generation_tco2=float(df.emis_generation_t.sum()) if "emis_generation_t" in df else 0.0,
             carbon_cost_cny=r.get("emissions_t", 0.0)*sc.carbon_price_cny_t,
             dc_carbon_intensity_kg_kwh=(float(df.emis_location_t.sum())/dcE if dcE and "emis_location_t" in df else 0.0),
             migration_energy_mwh=r.get("mig_energy_mwh", 0.0),
             energy_cost_cny=float(df.hour_cost.sum()), unserved_penalty_cny=r.get("unserved_penalty_cny", 0.0))
    if "grid_import_MW" in df:
        stoloss = sum(dt*float((df[f"{st}_ch"] - df[f"{st}_dis"]).sum()) for st in r["storage"])
        load = dcE + dt*float(df.base_load_MW.sum()) + max(stoloss, 0.0)
        imp = dt*float(df.grid_import_MW.sum()); fos = dt*float(df.fossil_gen_MW.sum())
        k.update(grid_import_mwh=imp, grid_export_mwh=dt*float(df.grid_export_MW.sum()),
                 green_share_pct=100*max(0.0, 1 - (imp + fos)/load) if load else 0.0,
                 renewable_avail_mwh=dt*float(df.pv_avail.sum()), renewable_used_mwh=dt*float(df.pv_used.sum()),
                 renewable_curtail_pct=100*float((df.pv_avail - df.pv_used).sum()/max(df.pv_avail.sum(), 1e-9)))
        for g, gi in enumerate(r.get("gens", [])):
            if gi.get("ext") and len([x for x in r["gens"] if x.get("ext")]) > 1:
                k[f"import_{gi.get('name', g)}_mwh"] = dt*float(df[f"gen{g}_MW"].sum())
    for d in sc.data_centers:
        if f"{d.name}_grid_MW" in df: k[f"{d.name}_energy_mwh"] = dt*float(df[f"{d.name}_grid_MW"].sum())
    if "jobs" in r:
        j = r["jobs"]; lk = r["links"]
        k.update(jobs_n=len(j), jobs_deadline_met_pct=100*float(j.met_deadline.mean()), jobs_unserved_mwh=float(j.unserved_mwh.sum()),
                 jobs_migrated_n=int((j.migrated_mwh > 1e-4).sum()),
                 jobs_latency_sensitive_migrated_n=int(((j.migrated_mwh > 1e-4) & j.latency_sensitive).sum()),
                 link_max_util_pct=float((lk.mw/lk.cap_mw).max()*100) if len(lk) and lk.cap_mw.notna().all() else 0.0,
                 link_hours_at_cap=int((lk.mw >= lk.cap_mw - 1e-6).sum()) if len(lk) and lk.cap_mw.notna().all() else 0)
    for st in r["storage"]:
        k[f"{st}_throughput_mwh"] = dt*float(df[f"{st}_dis"].sum())
    th = r.get("thermal")
    if th:
        D = th["dcs"]; it = sum(x["it_mwh"] for x in D.values())
        tmax = max(x["tin_max_c"] for x in D.values())
        k.update(pue_avg=sum(x["pue_avg"]*x["it_mwh"] for x in D.values())/it if it else 0.0, pue_max=max(x["pue_max"] for x in D.values()),
                 pue_min=min(x["pue_min"] for x in D.values()), tin_max_c=tmax, tin_min_c=min(x["tin_min_c"] for x in D.values()),
                 thermal_margin_k=min(x["margin_to_allow_k"] for x in D.values()), hours_above_rec=sum(x["hours_above_rec"] for x in D.values()),
                 cooling_mwh=sum(x["cooling_mwh"] for x in D.values()), thermal_violations=len(th["violations"]),
                 free_cooling_mwh_th=sum(x["free_cooling_mwh"] for x in D.values()), tes_discharge_mwh_th=sum(x["tes_discharge_mwh"] for x in D.values()))
        from .cooling import node_is_liquid as _nl
        _liq = {d.name for d in sc.data_centers if d.thermal is not None and _nl(d.thermal)}
        _air = [x["tin_max_c"] for n, x in D.items() if n not in _liq]; _lq = [x["tin_max_c"] for n, x in D.items() if n in _liq]
        k.update(tin_air_max_c=max(_air) if _air else None, coolant_supply_max_c=max(_lq) if _lq else None)   # 风冷入口 / 液冷供液 分开统计
        h = th.get("heat") or {}
        off = float(df.heat_offset_t.sum()) if "heat_offset_t" in df else 0.0
        itm = sum(x["it_mwh"] for x in D.values()) or 1e-9
        k.update(wue_l_kwh=round(sum(x.get("water_m3", 0) for x in D.values())/itm, 3), water_m3=round(sum(x.get("water_m3", 0) for x in D.values()), 1))
        F = h.get("feasibility") or {}
        if F: k.update(heat_cost_cny_gj=F["heat_cost_cny_gj"], terminal_margin_k=F["min_margin_k"], heat_verdict=F["level"], heat_boost_mwh=F["boost_mwh"])
        k.update(heat_delivered_mwh=h.get("delivered_mwh", 0.0), heat_revenue_cny=h.get("revenue_cny", 0.0), carbon_heat_offset_tco2=off,
                 erf=(h.get("delivered_mwh", 0.0)/dcE if dcE else 0.0))   # The Green Grid ERF = 再利用能量/数据中心总能耗
        k["carbon_elec_tco2"] = float(r.get("emissions_t", 0.0)) + off
    if r.get("dr"):
        k.update(dr_delivered_mwh=sum(e["delivered_mwh"] for e in r["dr"]), dr_requested_mwh=sum(e["requested_mwh"] for e in r["dr"]),
                 dr_revenue_cny=sum(e["revenue_cny"] for e in r["dr"]))
    return {a: round(b, 3) if isinstance(b, float) else b for a, b in k.items()}

@tool("compute_kpis", "计算 KPI：成本、弃光、最大线路负载率、电压(若已校核)、数据中心用电成本等。", {
    "type": "object", "properties": {"case": {"type": "string", "default": "optimized"}}})
def compute_kpis(s: Session, case="optimized"):
    k = _kpis(_sc(s), _res(s, case))
    ac = s.state.get("ac", {}).get(case)
    if ac: k.update(ac_vmin_pu=round(ac["vmin_pu"], 4), ac_vmax_pu=round(ac["vmax_pu"], 4),
                    ac_max_branch_loading_pct=round(ac["max_branch_loading_pct"], 2))
    s.state.setdefault("kpis", {})[case] = k
    return {"ok": True, "case": case, "kpis": k}

@tool("compare_baseline", "对比优化方案与基线（自动补跑缺失的基线），输出节省比例。", {"type": "object", "properties": {}})
def compare_baseline(s: Session):
    if "baseline" not in s.state.get("results", {}): run_dispatch(s, "baseline")
    if "optimized" not in s.state.get("results", {}): run_dispatch(s, "optimized")
    kb = _kpis(_sc(s), _res(s, "baseline")); ko = _kpis(_sc(s), _res(s, "optimized"))
    cmp = {k: dict(baseline=kb.get(k), optimized=ko.get(k)) for k in ko}
    sav = (kb["total_objective_cny"]-ko["total_objective_cny"])/max(abs(kb["total_objective_cny"]), 1e-9)*100   # 基线目标可能为负（外送收入），用绝对值作分母
    s.state["compare"] = dict(table=cmp, saving_pct=round(sav, 2),
                              saving_cny=round(kb["total_objective_cny"]-ko["total_objective_cny"], 1),
                              emissions_reduction_pct=round((kb["emissions_tco2"]-ko["emissions_tco2"])/kb["emissions_tco2"]*100, 2) if kb["emissions_tco2"] else 0.0)
    with open(_art(s, "compare.json"), "w") as f: json.dump(s.state["compare"], f, indent=2, ensure_ascii=False)
    return {"ok": True, **s.state["compare"]}

@tool("make_plots", "生成图表：数据中心负荷 vs 电价/光伏、储能SOC、成本对比、小时成本曲线、碳强度与排放、任务窗口。", {"type": "object", "properties": {}})
def make_plots(s: Session):
    sc = _sc(s); od = _res(s)["df"]; bd = s.state["results"].get("baseline", {}).get("df") if "baseline" in s.state["results"] else None
    h = od.hour; files = []
    fig, ax = plt.subplots(figsize=(10, 5))
    for i, d in enumerate(sc.data_centers):
        ax.plot(h, od[f"{d.name}_grid_MW"], f"C{i}", lw=2, label=f"{d.name} 优化")
        if bd is not None: ax.plot(h, bd[f"{d.name}_grid_MW"], f"C{i}", ls="--", alpha=.6, label=f"{d.name} 基线")
    ax.fill_between(h, 0, od.pv_avail/3, color="gold", alpha=.25, label="光伏可用/3")
    ax2 = ax.twinx(); ax2.step(h, od.price, "k", where="mid", label="分时电价"); ax2.set_ylabel("电价 (元/kWh)")
    ax.set_xlabel("小时"); ax.set_ylabel("数据中心电网功率 (MW)"); ax.legend(loc="upper left", fontsize=8)
    ax.set_title("数据中心负荷 vs 电价与光伏（合成数据）"); fig.tight_layout()
    fig.savefig(_art(s, "dc_load_price_pv.png"), dpi=110); plt.close(fig); files.append("dc_load_price_pv.png")
    for st in _res(s)["storage"]:
        fig, ax = plt.subplots(figsize=(9, 4))
        ax.bar(h, od[f"{st}_ch"], color="C2", label="充电 MW"); ax.bar(h, -od[f"{st}_dis"], color="C3", label="放电 MW")
        ax2 = ax.twinx(); ax2.plot(h, od[f"{st}_soc"], "k-o", ms=3, label="SOC MWh"); ax2.set_ylabel("SOC (MWh)")
        ax.set_xlabel("小时"); ax.set_ylabel("功率 (MW)"); ax.legend(loc="upper left"); ax.set_title(f"储能 {st} 充放电（合成）")
        fig.tight_layout(); fn = f"storage_{st}.png"; fig.savefig(_art(s, fn), dpi=110); plt.close(fig); files.append(fn)
    fig, ax = plt.subplots(figsize=(8, 4))
    ax.plot(h, od.hour_cost/1e3, "g-o", label="优化")
    if bd is not None: ax.plot(h, bd.hour_cost/1e3, "-o", color="grey", label="基线")
    ax.set_xlabel("小时"); ax.set_ylabel("每步发购电费用 (千元)"); ax.legend(); ax.set_title("每步费用（已积分）")
    fig.tight_layout(); fig.savefig(_art(s, "cost_curve.png"), dpi=110); plt.close(fig); files.append("cost_curve.png")
    if "compare" in s.state:
        t = s.state["compare"]["table"]["total_objective_cny"]
        fig, ax = plt.subplots(figsize=(6, 4))
        ax.bar(["基线", "优化"], [t["baseline"]/1e6, t["optimized"]/1e6], color=["grey", "green"])
        ax.set_ylabel("日总成本 (百万元)"); ax.set_title(f"总成本对比（节省 {s.state['compare']['saving_pct']:.1f}%）")
        fig.tight_layout(); fig.savefig(_art(s, "cost_compare.png"), dpi=110); plt.close(fig); files.append("cost_compare.png")
    # 碳强度与逐时排放（Phase 1）
    from ..scenario import carbon_profile, region_of
    fig, ax = plt.subplots(figsize=(9, 4)); seen = set()
    for d in sc.data_centers:
        rg = region_of(sc, d.bus)
        if rg in seen: continue
        seen.add(rg); ax.plot(h, carbon_profile(sc, d.bus), "-o", ms=3, label=f"碳强度 {rg} (t/MWh)")
    ax2 = ax.twinx(); ax2.bar(h, od.emis_location_t if sc.carbon_accounting == "location" else od.emis_generation_t, alpha=.3, color="C3", label="优化 逐时排放 t")
    if bd is not None: ax2.step(h, bd.emis_location_t if sc.carbon_accounting == "location" else bd.emis_generation_t, "k--", where="mid", label="基线 逐时排放 t")
    ax.set_xlabel("小时"); ax.set_ylabel("碳强度 tCO2/MWh"); ax2.set_ylabel("每步排放 tCO2"); ax.legend(loc="upper left", fontsize=8); ax2.legend(loc="upper right", fontsize=8)
    ax.set_title(f"逐时碳强度（{sc.carbon_source}，合成）与排放"); fig.tight_layout()
    fig.savefig(_art(s, "carbon_emissions.png"), dpi=110); plt.close(fig); files.append("carbon_emissions.png")
    if "jobs" in _res(s):
        j = _res(s)["jobs"]
        fig, ax = plt.subplots(figsize=(10, max(3, 0.18*len(j))))
        for i, r in enumerate(j.itertuples()):
            ax.barh(i, r.deadline - r.release, left=r.release, color="C0" if r.met_deadline else "C3", alpha=.25)
            if r.finish_hour: ax.plot([r.finish_hour], [i], "k|", ms=8)
            if r.migrated_mwh > 1e-4: ax.plot([r.release], [i], "C1>", ms=5)
        ax.set_yticks(range(len(j))); ax.set_yticklabels([f"{a}@{b}" for a, b in zip(j.job, j.home)], fontsize=6)
        ax.set_xlabel("小时"); ax.set_title("任务窗口 [释放, 截止)（蓝=按期完成，红=未完成；|=完成时刻；▶=发生迁移）"); fig.tight_layout()
        fig.savefig(_art(s, "jobs_windows.png"), dpi=110); plt.close(fig); files.append("jobs_windows.png")
    s.state["plots"] = files
    return {"ok": True, "artifacts": files}

@tool("write_report", "生成 Markdown 中文分析报告（汇总场景、KPI、对比、交流校核与图表）。", {
    "type": "object", "properties": {"extra_notes": {"type": "string", "description": "LLM 补充的分析文字"}}})
def write_report(s: Session, extra_notes: str = ""):
    sc = _sc(s); k = s.state.get("kpis", {}).get("optimized") or _kpis(sc, _res(s))
    cmp = s.state.get("compare"); ac = s.state.get("ac", {}).get("optimized")
    L = [f"# 算电协同调度分析报告：{sc.name}", "", f"> ⚠️ {sc.note}", "", "## 1. 场景",
         (f"- 网络：自定义等值网络（{len(sc.network.buses)} 母线 / {len(sc.network.lines)} 线路 / {len(sc.network.trafos)} 变压器）；" if sc.network_case == "custom" and sc.network else f"- 网络：IEEE {sc.network_case[4:]} 节点；") + f"电价：{sc.price_kind}（{min(sc.price_cny_kwh)}–{max(sc.price_cny_kwh)} 元/kWh）",
         f"- 数据中心：" + "；".join(f"{d.name}@母线{d.bus}（IT {d.cap_it_mw} MW, PUE {d.pue}, 批处理 {d.batch_mwh} MWh/日）" for d in sc.data_centers),
         f"- 光伏：{sum(p.cap_mw for p in sc.pv)} MW；储能：" + ("；".join(f"{x.name}@母线{x.bus} {x.energy_mwh} MWh/{x.power_mw} MW" for x in sc.storage) or "无"),
         "", "## 2. 优化方案 KPI", "| 指标 | 数值 |", "|---|---|"] + [f"| {a} | {b} |" for a, b in k.items()]
    if cmp:
        L += ["", "## 3. 与基线对比", f"**总成本节省 {cmp['saving_pct']}%（{cmp['saving_cny']:,.0f} 元/日）**", "",
              "| 指标 | 基线 | 优化 |", "|---|---|---|"] + [f"| {a} | {v['baseline']} | {v['optimized']} |" for a, v in cmp["table"].items()]
    if ac:
        L += ["", "## 4. 交流潮流校核 (pandapower)",
              f"- 校核时刻：{ac['hour']}:00，收敛：{ac['converged']}",
              f"- 电压范围：{ac['vmin_pu']:.4f} – {ac['vmax_pu']:.4f} pu（{'满足' if ac['voltage_ok'] else '越限'} 0.94–1.10，IEEE14 发电机母线设定值达 1.09 pu）",
              f"- 最大支路负载率：{ac['max_branch_loading_pct']:.1f}%（DC-OPF 预测 {ac['dcopf_pred_loading_pct']:.1f}%），{'未过载' if ac['loading_ok'] else '存在过载'}"]
    L += ["", "## 4b. 碳排放与任务", f"- 碳核算口径：{sc.carbon_accounting}；碳强度来源：{sc.carbon_source}（默认 0.5306 kgCO₂/kWh × 合成日内形状，**合成**）；碳价 {sc.carbon_price_cny_t} 元/t，碳权重 w={sc.carbon_weight}",
          f"- 总排放 {k.get('emissions_tco2', 0):.1f} tCO₂（数据中心 location 口径 {k.get('dc_emissions_location_tco2', 0):.1f} t；系统发电侧 {k.get('system_emissions_generation_tco2', 0):.1f} t）；不含碳成本 {k.get('cost_cny', 0):,.0f} 元"]
    if cmp and "emissions_reduction_pct" in cmp: L.append(f"- 相比基线排放变化：减少 {cmp['emissions_reduction_pct']}%")
    if "jobs_n" in k:
        L.append(f"- 任务级作业 {k['jobs_n']} 个，截止前完成率 {k['jobs_deadline_met_pct']:.1f}%（未完成 {k['jobs_unserved_mwh']:.2f} MWh）；迁移任务 {k['jobs_migrated_n']} 个（其中时延敏感 {k['jobs_latency_sensitive_migrated_n']} 个，均满足链路时延上限），迁移能耗 {k['migration_energy_mwh']:.2f} MWh，链路最大利用率 {k['link_max_util_pct']:.0f}%")
    if "pareto" in s.state:
        L += ["", "### Pareto（成本-碳）", "| w | 成本(元) | 排放(t) |", "|---|---|---|"] + [f"| {p['weight']} | {p['cost_cny']:,.0f} | {p['emissions_tco2']:.1f} |" for p in s.state["pareto"]]
    L += ["", "## 5. 分析要点"]
    if cmp: L.append(f"- 批处理负荷由高价时段转移至低价/光伏充裕时段，并在数据中心间迁移 {k['migrated_mwh']:.1f} MWh，数据中心平均用电价格 {k['dc_avg_price_cny_kwh']:.3f} 元/kWh。")
    for st in sc.storage:
        if f"{st.name}_throughput_mwh" in k: L.append(f"- 储能 {st.name} 日放电量 {k[f'{st.name}_throughput_mwh']:.1f} MWh，低谷充电、高峰放电实现套利与削峰。")
    L.append(f"- 光伏利用率 {k['pv_util_pct']:.1f}%，弃光 {k['pv_curtail_mwh']:.1f} MWh。")
    if extra_notes: L += ["", extra_notes]
    L += ["", "## 6. 图表"] + [f"![{p}]({p})" for p in s.state.get("plots", [])]
    L += ["", "## 7. 局限", "- DC-OPF 线性化忽略无功与网损；交流校核仅针对单一时刻。", "- 所有数据为合成示例数据，不代表真实系统。"]
    with open(_art(s, "report.md"), "w") as f: f.write("\n".join(L))
    return {"ok": True, "artifact": "report.md", "chars": sum(map(len, L))}
