"""三级优化工具：日前基线 / 日内滚动 / 可行域 / 实时跟踪 / 预测补丁 / 耦合报告。"""
from __future__ import annotations
import json, os, copy
from .base import tool, Session
from ..opt import tiered as T


def _sc(s: Session):
    sc = s.state.get("scenario")
    if sc is None:
        raise ValueError("尚无场景，请先 build_scenario / 加载预设")
    from ..time_axis import require_hourly
    require_hourly(sc,"三级运行")
    return sc


def _art(s: Session, name: str) -> str:
    os.makedirs(s.artifact_dir, exist_ok=True)
    path = os.path.join(s.artifact_dir, name)
    if name not in s.artifacts:
        s.artifacts.append(name)
    return path


def _tier(s: Session) -> dict:
    return s.state.setdefault("tier", {})


@tool("save_day_ahead_baseline",
      "将当前（或新求解的）优化调度保存为日前运行基线产物（含版本号）：站点关口/IT/冷却/储能/热指标。"
      "对话关键词：日前基线、定基线、保存基线、day-ahead baseline。",
      {"type": "object", "properties": {
          "case": {"type": "string", "default": "optimized"},
          "solve_first": {"type": "boolean", "default": True},
          "label": {"type": "string", "default": "day_ahead"},
          "note": {"type": "string"},
      }})
def save_day_ahead_baseline(s: Session, case="optimized", solve_first=True, label="day_ahead", note=""):
    from . import sdco_engine as eng
    sc = _sc(s)
    res = (s.state.get("results") or {}).get(case)
    if solve_first or res is None:
        res = eng.solve(sc, optimize=(case != "baseline"), levers=s.state.get("levers"))
        s.state.setdefault("results", {})[case] = res
        res["df"].to_csv(_art(s, f"dispatch_{case}.csv"), index=False)
    art = T.make_baseline(sc, res, label=label or "day_ahead", note=note or "")
    path = T.save_baseline(s.artifact_dir, art, name="baseline")
    try:
        art["artifact_version"] = int(path.rsplit("_v", 1)[-1].split(".")[0])
    except Exception:
        art["artifact_version"] = 1
    _tier(s)["baseline"] = art
    _tier(s)["baseline_path"] = path
    _tier(s)["timeline"] = _tier(s).get("timeline") or []
    _tier(s)["timeline"].append({"stage": "day_ahead", "path": path, "cost_cny": art["cost_cny"],
                                 "emissions_tco2": art["emissions_tco2"], "thermal_safe": art.get("thermal_safe")})
    with open(_art(s, "tier_state.json"), "w", encoding="utf-8") as f:
        json.dump({k: v for k, v in _tier(s).items() if k != "last_roll_result"}, f, ensure_ascii=False, indent=2, default=str)
    return {"ok": True, "stage": "day_ahead", "artifact": os.path.basename(path), "artifacts": [os.path.basename(path), "baseline.json", "tier_state.json"],
            "cost_cny": art["cost_cny"], "emissions_tco2": art["emissions_tco2"],
            "thermal_safe": art.get("thermal_safe"), "version": art.get("artifact_version"),
            "site_peak_mw": max(art["series"]["site_grid_mw"]) if art["series"].get("site_grid_mw") else None}


@tool("apply_forecast_patch",
      "应用预测/价格/碳/负荷补丁到当前场景。可传 patch JSON，或 path 文件，或中文 text（如「下午3点风电少10%」「光伏降15%」）。"
      "对话：预测补丁、风光少、风电少、负荷上涨。",
      {"type": "object", "properties": {
          "text": {"type": "string"},
          "path": {"type": "string"},
          "patch": {"type": "object"},
          "clone": {"type": "boolean", "default": False, "description": "true=深拷贝场景再改，不污染原场景"},
      }})
def apply_forecast_patch(s: Session, text="", path="", patch=None, clone=False):
    sc = _sc(s)
    p = dict(patch or {})
    if path:
        p.update(T.load_patch_file(path))
    if text:
        p.update(T.parse_forecast_nl(text))
    if clone:
        sc = copy.deepcopy(sc); s.state["scenario"] = sc
    info = T.apply_forecast_patch(sc, p)
    _tier(s)["last_patch"] = info
    with open(_art(s, "forecast_patch.json"), "w", encoding="utf-8") as f:
        json.dump(info, f, ensure_ascii=False, indent=2)
    return {"ok": True, **info, "artifacts": ["forecast_patch.json"]}


@tool("reoptimize_intraday",
      "日内滚动重调度：锁定已过去小时（来自日前/上次结果），应用预测补丁，相对日前基线关口偏离罚。"
      "可选 soc_measured / soc_measured_path / text 中的「SOC实测」按实测更新自由窗初值（默认关闭=沿用日前锁定）。"
      "对话：日内滚动、滚动校准、滚动重调度、SOC实测、reoptimize。",
      {"type": "object", "properties": {
          "from_t": {"type": "integer", "description": "从此小时起重优化，默认 8", "default": 8},
          "dev_penalty_cny_mwh": {"type": "number", "default": 80},
          "text_patch": {"type": "string", "description": "中文预测补丁；也可含 SOC实测0.42"},
          "patch": {"type": "object"},
          "case": {"type": "string", "default": "optimized", "description": "作为 prior 的结果键"},
          "soc_measured": {"type": "object", "description": "可选 {储能名: 0.42} 或 {名:{value,unit}}；unit=frac|mwh|%"},
          "soc_measured_path": {"type": "string", "description": "可选 JSON 文件路径（含 soc_measured 或直接映射）"},
          "soc_end_use_measured": {"type": "boolean", "default": False, "description": "日末 SOC 目标改用实测（默认仍用日初 soc0）"},
          "emergency": {"type": "boolean", "description": "可选；覆盖场景 emergency_mode（UPS 备用底线放开 / 应急柴发）"},
      }})
def reoptimize_intraday(s: Session, from_t=8, dev_penalty_cny_mwh=80, text_patch="", patch=None, case="optimized",
                        soc_measured=None, soc_measured_path="", soc_end_use_measured=False, emergency=None):
    sc = _sc(s)
    prior = (s.state.get("results") or {}).get(case)
    if prior is None:
        # auto day-ahead
        out0 = save_day_ahead_baseline(s, case=case, solve_first=True)
        prior = s.state["results"][case]
    bas = _tier(s).get("baseline")
    if bas is None and os.path.exists(os.path.join(s.artifact_dir, "baseline.json")):
        bas = T.load_baseline(s.artifact_dir)
        _tier(s)["baseline"] = bas
    p = dict(patch or {})
    if text_patch:
        p.update(T.parse_forecast_nl(text_patch))
    soc_raw = dict(soc_measured or {})
    if soc_measured_path:
        soc_raw.update(T.load_soc_measured_file(soc_measured_path))
    if text_patch:
        nl_soc = T.parse_soc_measured_nl(text_patch)
        if nl_soc:
            # NL 补丁与显式 API 合并；显式优先
            merged = dict(nl_soc)
            merged.update(soc_raw)
            soc_raw = merged
    r, sc2 = T.run_rolling(sc, prior, int(from_t), baseline_art=bas, patch=p,
                           dev_penalty_cny_mwh=float(dev_penalty_cny_mwh), levers=s.state.get("levers"),
                           soc_measured=soc_raw or None, soc_end_use_measured=bool(soc_end_use_measured),
                           emergency=emergency)
    # keep original scenario; store patched in tier for transparency
    s.state.setdefault("results", {})["intra_day"] = r
    r["df"].to_csv(_art(s, "dispatch_intra_day.csv"), index=False)
    # do not replace scenario by default (compat); record patched snapshot path
    with open(_art(s, "scenario_intraday_patched.json"), "w", encoding="utf-8") as f:
        json.dump(sc2.model_dump(), f, ensure_ascii=False, indent=2, default=str)
    cmp_ = T.compare_tiers(prior, r)
    with open(_art(s, "tier_compare.json"), "w", encoding="utf-8") as f:
        json.dump(cmp_, f, ensure_ascii=False, indent=2)
    soc_dev = r.get("soc_deviation") or []
    soc_src = r.get("soc_source") or "day_ahead_prior"
    with open(_art(s, "soc_measurement.json"), "w", encoding="utf-8") as f:
        json.dump({"source": soc_src, "deviation": soc_dev, "raw": soc_raw,
                   "tier": r.get("tier", {}).get("soc_measured")}, f, ensure_ascii=False, indent=2, default=str)
    _tier(s)["last_roll"] = {"from_t": from_t, "patch": p, "compare": cmp_,
                             "soc_source": soc_src, "soc_deviation": soc_dev}
    _tier(s).setdefault("timeline", []).append({
        "stage": "intra_day", "from_t": from_t, "cost_cny": float(r.get("cost_cny", r["objective"])),
        "emissions_tco2": float(r.get("emissions_t", 0)),
        "thermal_safe": (r.get("thermal") or {}).get("safe"),
        "soc_source": soc_src,
    })
    coup = T.coupling_report(sc2, r)
    with open(_art(s, "coupling_report.json"), "w", encoding="utf-8") as f:
        json.dump(coup, f, ensure_ascii=False, indent=2)
    th = r.get("thermal") or {}
    arts = ["dispatch_intra_day.csv", "tier_compare.json", "coupling_report.json",
            "scenario_intraday_patched.json", "soc_measurement.json"]
    return {"ok": True, "stage": "intra_day", "from_t": from_t,
            "objective_cny": round(float(r["objective"]), 1), "cost_cny": round(float(r.get("cost_cny", r["objective"])), 1),
            "emissions_tco2": round(float(r.get("emissions_t", 0)), 3),
            "thermal_safe": th.get("safe"), "thermal_violations": th.get("violations"),
            "compare": cmp_, "patch": p,
            "soc_source": soc_src, "soc_deviation": soc_dev,
            "ups": r.get("ups") or [], "diesel": r.get("diesel") or [],
            "artifacts": arts}


@tool("compute_flexibility_envelope",
      "计算分阶段可行响应域（逐时关口功率上/下调带宽）。stage=day_ahead|intra_day|real_time。"
      "对话：可行响应域、灵活包络、上下调范围、envelope。",
      {"type": "object", "properties": {
          "stage": {"type": "string", "enum": ["day_ahead", "intra_day", "real_time"], "default": "day_ahead"},
          "from_t": {"type": "integer", "default": 8},
          "stride": {"type": "integer", "default": 2, "description": "小时步长，2=偶数时以加速"},
          "hours": {"type": "array", "items": {"type": "integer"}},
      }})
def compute_flexibility_envelope(s: Session, stage="day_ahead", from_t=8, stride=2, hours=None):
    sc = _sc(s)
    # 日内/实时包络必须与滚动所用（可能已打补丁）的场景一致，否则硬锁 prior 会不可行
    if stage in ("intra_day", "real_time"):
        patched = os.path.join(s.artifact_dir, "scenario_intraday_patched.json")
        if os.path.exists(patched):
            from ..scenario import Scenario
            with open(patched, encoding="utf-8") as f:
                sc = Scenario.model_validate(json.load(f))
    prior = (s.state.get("results") or {}).get("intra_day") or (s.state.get("results") or {}).get("optimized")
    bas = _tier(s).get("baseline")
    if bas is None and os.path.exists(os.path.join(s.artifact_dir, "baseline.json")):
        bas = T.load_baseline(s.artifact_dir)
    env = T.compute_envelope(sc, stage=stage, from_t=int(from_t), prior_result=prior, baseline_art=bas,
                             hours=hours, stride=int(stride or 2), levers=s.state.get("levers"))
    fname = f"envelope_{stage}.json"
    with open(_art(s, fname), "w", encoding="utf-8") as f:
        json.dump(env, f, ensure_ascii=False, indent=2)
    _tier(s).setdefault("envelopes", {})[stage] = env
    # shrink vs da if available
    shrink = None
    envs = _tier(s).get("envelopes") or {}
    if "day_ahead" in envs and stage != "day_ahead":
        shrink = T.shrink_report(envs["day_ahead"], envs.get("intra_day"), envs.get("real_time"))
        with open(_art(s, "envelope_shrink.json"), "w", encoding="utf-8") as f:
            json.dump(shrink, f, ensure_ascii=False, indent=2)
    arts = [fname] + (["envelope_shrink.json"] if shrink else [])
    return {"ok": env.get("ok", False), "stage": stage, "summary": env.get("summary"),
            "n_hours": len(env.get("hours") or []), "shrink": shrink, "artifacts": arts,
            "hours_sample": (env.get("hours") or [])[:3]}


@tool("run_realtime_track",
      "实时层：规则或 MPC-lite 在 5–15 分钟步长跟踪调度信号（冷却流量+电池/UPS 走廊），含 RC 热安全。"
      "不替换主 LP。对话：实时跟踪、MPC-lite、秒级跟踪、冷却跟踪。",
      {"type": "object", "properties": {
          "mode": {"type": "string", "enum": ["rules", "mpc_lite"], "default": "mpc_lite"},
          "dt_min": {"type": "integer", "default": 10},
          "hours": {"type": "array", "items": {"type": "integer"}, "description": "取哪些小时的日前信号展开，默认 12-15"},
          "case": {"type": "string", "default": "intra_day"},
      }})
def run_realtime_track(s: Session, mode="mpc_lite", dt_min=10, hours=None, case="intra_day"):
    sc = _sc(s)
    res = (s.state.get("results") or {}).get(case) or (s.state.get("results") or {}).get("optimized")
    if res is None:
        save_day_ahead_baseline(s, solve_first=True)
        res = s.state["results"]["optimized"]
        case = "optimized"
    df = res["df"]
    site = T._site_mw(df, sc)
    hours = hours or [12, 13, 14, 15]
    # expand hourly signal to substeps
    steps = []
    it_heat = []
    tout = []
    n_sub = max(1, int(round(60 / max(int(dt_min), 1))))
    for h in hours:
        h = int(h)
        sig = float(site[h])
        # IT heat proxy
        it_cols = [f"{d.name}_IT_MW" for d in sc.data_centers if f"{d.name}_IT_MW" in df.columns]
        ith = float(df.loc[h, it_cols].sum()) if it_cols else sig * 0.7
        to = float(df.loc[h, f"{sc.data_centers[0].name}_Tout_C"]) if sc.data_centers and f"{sc.data_centers[0].name}_Tout_C" in df.columns else 30.0
        for _ in range(n_sub):
            steps.append(sig); it_heat.append(ith); tout.append(to)
    # 聚合全站冷机容量 / 热容（实时层站点级跟踪）
    d0 = sc.data_centers[0]
    tin0 = 24.0; t_allow = 32.0; t_rec = 27.0; cool_cap = 0.0; cop = 3.5
    c_air = 0.0; c_mass = 0.0; ua_am = 0.0; ua_env = 0.0
    for d in sc.data_centers:
        th = d.thermal
        if not th:
            cool_cap += float(d.cap_it_mw) * 1.2
            c_air += 0.15; c_mass += 0.8; ua_am += 0.4; ua_env += 0.05
            continue
        tin0 = float(th.t0_c); t_allow = min(t_allow, float(th.t_allow_max_c)); t_rec = min(t_rec, float(th.t_rec_max_c))
        cool_cap += float(th.chiller_cap_mw_th or d.cap_it_mw)
        c_air += float(th.c_air_mwh_k or 0.15); c_mass += float(th.c_mass_mwh_k or 0.8)
        ua_am += float(th.ua_am_mw_k or 0.4); ua_env += float(th.ua_env_mw_k or 0.05)
    cool_cap = max(cool_cap, 1.0)
    bat_p = sum(float(st.power_mw) for st in sc.storage) if sc.storage else 10.0
    bat_e = sum(float(st.energy_mwh) for st in sc.storage) if sc.storage else 40.0
    soc0 = float(sc.storage[0].soc0) if sc.storage else 0.5
    tin_col = f"{d0.name}_Tin_C"
    if tin_col in df.columns:
        tin0 = float(df.loc[int(hours[0]), tin_col])
    rt = T.realtime_track(steps, tin0_c=tin0, t_allow_max_c=t_allow, t_rec_max_c=t_rec,
                          c_air=c_air, c_mass=c_mass, ua_am=ua_am, ua_env=ua_env, tout_c=tout,
                          it_heat_mw=it_heat, cool_cap_mw=cool_cap, cool_cop=cop,
                          bat_power_mw=bat_p, bat_energy_mwh=bat_e, soc0=soc0,
                          dt_min=int(dt_min), mode=mode)
    with open(_art(s, "realtime_track.json"), "w", encoding="utf-8") as f:
        json.dump(rt, f, ensure_ascii=False, indent=2)
    _tier(s)["realtime"] = {k: rt[k] for k in rt if k != "trajectory"}
    _tier(s).setdefault("timeline", []).append({
        "stage": "real_time", "mode": mode, "dt_min": dt_min,
        "rmse_mw": rt["rmse_mw"], "max_tin_c": rt["max_tin_c"],
        "thermal_violation": rt["thermal_violation"],
    })
    return {"ok": True, "stage": "real_time", "mode": mode, "dt_min": dt_min,
            "rmse_mw": rt["rmse_mw"], "max_abs_err_mw": rt["max_abs_err_mw"],
            "max_tin_c": rt["max_tin_c"], "thermal_violation": rt["thermal_violation"],
            "n_steps": len(rt["trajectory"]), "artifacts": ["realtime_track.json"]}


@tool("report_load_cooling_coupling",
      "生成负载率↔冷却流量/关口功率耦合报告（日前经济 vs 热安全视角）。对话：负载率冷却、耦合报告、双层对照。",
      {"type": "object", "properties": {"case": {"type": "string", "default": "optimized"}}})
def report_load_cooling_coupling(s: Session, case="optimized"):
    sc = _sc(s)
    res = (s.state.get("results") or {}).get(case) or (s.state.get("results") or {}).get("intra_day")
    if res is None:
        raise ValueError("无调度结果，请先 run_dispatch / save_day_ahead_baseline")
    # use original sc for names; if intra_day may still match
    coup = T.coupling_report(sc, res)
    with open(_art(s, "coupling_report.json"), "w", encoding="utf-8") as f:
        json.dump(coup, f, ensure_ascii=False, indent=2)
    return {"ok": True, "corr_it_cool": coup.get("corr_it_cool"), "n_rows": len(coup["rows"]),
            "site_hourly_sample": coup["site_hourly"][:3], "note": coup["note"],
            "artifacts": ["coupling_report.json"]}




@tool("configure_backup_resources",
      "为当前场景配置可调度 UPS/EUPS 与柴发（默认不调用=无资源，完全向后兼容）。"
      "参数透明：效率/容量/SOC/功率/爬坡/最小出力/调度模式；未给字段用【假设】并写入 sources。"
      "对话：配置UPS、接入柴发、备用电源、断电应急。",
      {"type": "object", "properties": {
          "ups": {"description": "true=默认一套【假设】UPS；或 {energy_mwh,power_mw,eta_ch,eta_dis,soc0,soc_min,soc_max,reserve_frac,bus,name,source_note}；或列表"},
          "diesel": {"description": "true=默认一套【假设】柴发；或 {pmax_mw,pmin_mw,ramp_mw_h,cost_cny_mwh,emission_t_mwh,dispatch_mode,bus,name,source_note}"},
          "emergency_mode": {"type": "boolean", "description": "True=应急：UPS 可用至 soc_min；emergency_only 柴发放开"},
          "replace": {"type": "boolean", "default": False, "description": "先移除已有 UPS/柴发再添加"},
          "apply_to_session": {"type": "boolean", "default": True},
      }})
def configure_backup_resources(s: Session, ups=None, diesel=None, emergency_mode=None, replace=False, apply_to_session=True):
    sc = _sc(s)
    sc2, info = T.attach_backup_resources(sc, ups=ups, diesel=diesel, emergency_mode=emergency_mode, replace=bool(replace))
    if apply_to_session:
        s.state["scenario"] = sc2
    params = T.backup_resource_params(sc2)
    with open(_art(s, "backup_resources.json"), "w", encoding="utf-8") as f:
        json.dump({"attach": info, "params": params}, f, ensure_ascii=False, indent=2)
    _tier(s)["backup"] = params
    return {"ok": True, **info, "params": params, "artifacts": ["backup_resources.json"]}


@tool("list_backup_resources",
      "列出当前场景 UPS/柴发参数（值/单位/来源）。对话：备用资源、UPS参数、柴发参数。",
      {"type": "object", "properties": {}})
def list_backup_resources(s: Session):
    sc = _sc(s)
    params = T.backup_resource_params(sc)
    with open(_art(s, "backup_resources.json"), "w", encoding="utf-8") as f:
        json.dump(params, f, ensure_ascii=False, indent=2)
    return {**params, "artifacts": ["backup_resources.json"]}


@tool("set_emergency_mode",
      "开关应急模式（断电/外网受限）：UPS 备用 SOC 底线放开；dispatch_mode=emergency_only 的柴发可用。"
      "默认 False。对话：进入应急、断电模式、退出应急。",
      {"type": "object", "properties": {
          "enabled": {"type": "boolean", "default": True},
          "grid_import_max_mw": {"type": "number", "description": "可选：同时收紧所有外网 import_max_mw 模拟供电受限"},
      }})
def set_emergency_mode(s: Session, enabled=True, grid_import_max_mw=None):
    sc = _sc(s)
    sc.emergency_mode = bool(enabled)
    note = []
    if grid_import_max_mw is not None and sc.network and sc.network.ext_grids:
        for e in sc.network.ext_grids:
            note.append({"name": e.name, "old": e.import_max_mw, "new": float(grid_import_max_mw)})
            e.import_max_mw = float(grid_import_max_mw)
    s.state["scenario"] = sc
    with open(_art(s, "emergency_mode.json"), "w", encoding="utf-8") as f:
        json.dump({"emergency_mode": sc.emergency_mode, "grid_caps": note}, f, ensure_ascii=False, indent=2)
    _tier(s)["emergency_mode"] = sc.emergency_mode
    return {"ok": True, "emergency_mode": sc.emergency_mode, "grid_caps": note, "artifacts": ["emergency_mode.json"]}



@tool("get_tier_timeline",
      "返回会话内三级优化时间线（日前基线 / 日内滚动 / 实时跟踪）与包络摘要，供前端面板展示。",
      {"type": "object", "properties": {}})
def get_tier_timeline(s: Session):
    tr = _tier(s)
    # reload files if needed
    out = {
        "ok": True,
        "timeline": tr.get("timeline") or [],
        "baseline_meta": None if not tr.get("baseline") else {
            "cost_cny": tr["baseline"].get("cost_cny"),
            "emissions_tco2": tr["baseline"].get("emissions_tco2"),
            "thermal_safe": tr["baseline"].get("thermal_safe"),
            "version": tr["baseline"].get("artifact_version"),
            "site_grid_mw": tr["baseline"].get("series", {}).get("site_grid_mw"),
        },
        "envelopes": {k: v.get("summary") for k, v in (tr.get("envelopes") or {}).items()},
        "envelope_hours": {k: v.get("hours") for k, v in (tr.get("envelopes") or {}).items()},
        "realtime": tr.get("realtime"),
        "last_roll": tr.get("last_roll"),
        "last_patch": tr.get("last_patch"),
        "backup": tr.get("backup"),
        "emergency_mode": tr.get("emergency_mode"),
    }
    # attach rolling series if present
    rid = (s.state.get("results") or {}).get("intra_day")
    if rid is not None:
        out["intra_day_site_mw"] = T._site_mw(rid["df"], _sc(s))
        out["intra_day_cost_cny"] = float(rid.get("cost_cny", rid["objective"]))
    with open(_art(s, "tier_timeline.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2, default=str)
    out["artifacts"] = ["tier_timeline.json"]
    return out
