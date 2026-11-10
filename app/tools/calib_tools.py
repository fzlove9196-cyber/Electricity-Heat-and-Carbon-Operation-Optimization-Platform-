"""功率标定 / 年日校核 / 多节点热网辅助 工具。"""
from __future__ import annotations
import json, os
from .base import tool, Session
from .sim_tools import _art, _sc
from . import sdco_engine as eng

@tool("calibrate_power_model",
      "用本站 PDU/利用率 CSV 标定 IT 功率模型（idle_dynamic 或 pdu_pwl）。"
      "CSV 列：timestamp + (util 或 IT_kW) + PDU_kW。拟合后写入指定数据中心并标记来源【标定】；缺省 identity 不变。"
      "适用于“功率标定/PDU标定/实测标定/拟合idle”。",
      {"type": "object", "properties": {
          "csv_path": {"type": "string", "description": "服务器上 CSV 路径"},
          "csv_text": {"type": "string", "description": "直接传 CSV 文本（与 csv_path 二选一）"},
          "dc": {"type": "string", "description": "数据中心名称；缺省=第一个"},
          "mode": {"type": "string", "enum": ["idle_dynamic", "pdu_pwl"], "default": "idle_dynamic"},
          "n_seg": {"type": "integer", "default": 3},
          "n_servers": {"type": "integer", "description": "若 CSV 为单机功率则填台数换算站点"},
          "apply": {"type": "boolean", "default": True, "description": "是否写入场景"},
          "solve": {"type": "boolean", "default": False, "description": "标定后是否立即重解"}},
       "required": []})
def calibrate_power_model(s: Session, csv_path=None, csv_text=None, dc=None, mode="idle_dynamic",
                          n_seg=3, n_servers=None, apply=True, solve=False):
    from .. import calibration as CAL
    if not csv_path and not csv_text:
        raise ValueError("请提供 csv_path 或 csv_text")
    src = csv_path or csv_text
    if csv_path and not os.path.isfile(csv_path):
        # 也允许相对 artifacts
        alt = os.path.join(s.artifact_dir, csv_path)
        if os.path.isfile(alt): src = alt
        else: raise FileNotFoundError(csv_path)
    result = CAL.calibrate(src if csv_path else csv_text, mode=mode, n_seg=int(n_seg or 3),
                           n_servers=int(n_servers) if n_servers else None)
    sc = _sc(s)
    target = None
    if dc:
        target = next((d for d in sc.data_centers if d.name == dc), None)
        if target is None: raise ValueError(f"未找到数据中心 {dc}")
    else:
        target = sc.data_centers[0]
    meta = dict(dc=target.name, **{k: result[k] for k in ("fit", "apply", "n_samples", "source_tag", "util_mean", "pdu_kw_mean")})
    with open(_art(s, "power_calibration.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    arts = ["power_calibration.json"]
    if apply:
        notes = CAL.apply_to_dc(target, result["apply"])
        sc.sources = {**(sc.sources or {}), **notes}
        s.state["scenario"] = sc
        s.state["results"] = {}
        # 落盘场景
        open(os.path.join(s.artifact_dir, "scenario.json"), "w", encoding="utf-8").write(sc.model_dump_json(indent=2))
    out = dict(ok=True, dc=target.name, fit=result["fit"], apply=result["apply"],
               metrics=result["fit"]["metrics"], source="标定", artifacts=arts)
    if solve and apply:
        r = eng.solve(sc, optimize=True)
        out["solve_status"] = r["solver"]["status"]
        out["cost_cny"] = round(float(r["cost_cny"]), 2)
        out["emissions_t"] = round(float(r["emissions_t"]), 4)
    return out


@tool("check_year_days",
      "年–日物理闭环：对预置（或当前寻优方案容量）抽选典型/极端日，用完整日内引擎（DC-OPF+RC热+可选N-1）复核，"
      "报告违规、修复建议，并文档化代表日48相对8760铜板的碳/成本残差。适用于“年日校核/代表日误差/物理复核”。",
      {"type": "object", "properties": {
          "preset": {"type": "string"},
          "days": {"type": "array", "items": {"type": "string"}},
          "caps": {"type": "object"},
          "year": {"type": "integer", "default": 2024},
          "n1": {"type": "boolean", "default": True},
          "compare_rep48": {"type": "boolean", "default": True}}})
def check_year_days(s: Session, preset=None, days=None, caps=None, year=2024, n1=True, compare_rep48=True):
    from ..opt import day_check as DC
    # 若会话有寻优结果，默认用其 caps + preset
    opt = s.state.get("opt_result") or {}
    sp = s.state.get("opt_spec") or {}
    preset = preset or sp.get("preset") or (s.state.get("scenario").name if s.state.get("scenario") and getattr(s.state.get("scenario"), "name", None) else None)
    if not preset:
        preset = "zhongwei_summer_coupled"
    if caps is None:
        schemes = (opt.get("front") or opt.get("schemes") or [])
        pick = next((x for x in schemes if x.get("tag") in ("knee", "optimum", "cost_opt")), schemes[0] if schemes else None)
        caps = (pick or {}).get("kpi", {}).get("caps") or {}
    report = DC.run(preset, days=days, caps=caps, year=int(year or 2024), n1=bool(n1), compare_rep48=bool(compare_rep48))
    path = _art(s, "year_day_check.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2, default=str)
    s.state["year_day_check"] = report
    return dict(ok=True, summary=report["summary"], n_ok=report["n_ok"], n_total=report["n_total"],
                rep48_vs_8760=report.get("rep48_vs_8760"), artifacts=["year_day_check.json"])


@tool("build_multi_heat_network",
      "为当前场景构建多节点区域供热网（热母线+管段时延），保留单节点旧字段兼容。"
      "适用于“多节点热网/管网时延/余热多负荷”。",
      {"type": "object", "properties": {
          "nodes": {"type": "array", "items": {"type": "object"}, "description": "[{id,name,demand_mw_th|demand_peak_mw,storage_mwh_th?...}]"},
          "pipes": {"type": "array", "items": {"type": "object"}, "description": "[{frm,to,delay_h,loss,capacity_mw_th,name}]"},
          "inject_at": {"type": "object", "description": "{DC名: 节点id}"},
          "from_odense": {"type": "boolean", "description": "True=基于 Odense 预置拆成 plant+city 两节点示范"},
          "delay_h": {"type": "integer", "default": 1},
          "solve": {"type": "boolean", "default": True}}})
def build_multi_heat_network(s: Session, nodes=None, pipes=None, inject_at=None, from_odense=False,
                             delay_h=1, solve=True):
    from ..scenario import HeatNetwork, HeatNode, HeatPipe, load_preset
    if from_odense or ("scenario" not in s.state and not nodes):
        sc = load_preset("odense_meta_winter"); s.state["scenario"] = sc
    else:
        sc = _sc(s)
        if sc.heat_network is None and not nodes:
            sc = load_preset("odense_meta_winter"); s.state["scenario"] = sc
    hn = sc.heat_network
    if hn is None:
        raise ValueError("场景无 heat_network，请先启用余热供热或 from_odense=true")
    if from_odense or not nodes:
        dem = list(hn.demand_mw_th)
        plant_dem = [round(0.15 * x, 3) for x in dem]  # 近端园区自用
        city_dem = [round(0.85 * x, 3) for x in dem]
        nodes = [
            dict(id="plant", name="机房侧换热站", demand_mw_th=plant_dem, storage_mwh_th=max(hn.storage_mwh_th * 0.3, 0),
                 storage_p_mw_th=max(hn.storage_p_mw_th * 0.3, 0)),
            dict(id="city", name="城区负荷", demand_mw_th=city_dem, storage_mwh_th=max(hn.storage_mwh_th * 0.7, 0),
                 storage_p_mw_th=max(hn.storage_p_mw_th * 0.7, 0),
                 t_supply_min_c=hn.t_supply_min_c, t_supply_max_c=hn.t_supply_max_c),
        ]
        pipes = [dict(name="plant_to_city", frm="plant", to="city", delay_h=int(delay_h or 1),
                      loss=float(hn.pipe_loss or 0.05), capacity_mw_th=max(max(dem) * 1.2, 10))]
        dcs = hn.dcs or [d.name for d in sc.data_centers if d.thermal and d.thermal.hp_cap_mw_th > 0]
        inject_at = {n: "plant" for n in dcs}
    hn.nodes = [HeatNode.model_validate(n) for n in nodes]
    hn.pipes = [HeatPipe.model_validate(p) for p in (pipes or [])]
    hn.inject_at = dict(inject_at or {})
    # 汇总 demand 保持旧字段同步（售热上限）
    if hn.nodes:
        agg = [0.0] * 24
        for n in hn.nodes:
            for t in range(min(24, len(n.demand_mw_th))):
                agg[t] += float(n.demand_mw_th[t])
        hn.demand_mw_th = [round(x, 3) for x in agg]
    sc.heat_network = hn
    sc.sources = {**(sc.sources or {}), "多节点热网": f"【构建】{len(hn.nodes)} 节点 / {len(hn.pipes)} 管段，时延示例 delay_h={delay_h}"}
    s.state["scenario"] = sc
    open(os.path.join(s.artifact_dir, "scenario.json"), "w", encoding="utf-8").write(sc.model_dump_json(indent=2))
    out = dict(ok=True, n_nodes=len(hn.nodes), n_pipes=len(hn.pipes),
               pipes=[{"frm": p.frm, "to": p.to, "delay_h": p.delay_h, "loss": p.loss} for p in hn.pipes],
               inject_at=hn.inject_at)
    if solve:
        r = eng.solve(sc, optimize=True)
        out["solve_status"] = r["solver"]["status"]
        out["cost_cny"] = round(float(r.get("cost_cny") or 0), 2)
        out["heat_delivered_mwh"] = round(float(r["df"]["heat_delivered_MWth"].sum()), 3) if "heat_delivered_MWth" in r.get("df", {}) else None
        out["emissions_t"] = round(float(r.get("emissions_t") or 0), 4)
        th = r.get("thermal") or {}
        out["heat_multi"] = bool((th.get("info") or {}).get("_heat_multi") if isinstance(th, dict) else False)
        # info may be nested differently — probe df columns
        if hasattr(r.get("df"), "columns"):
            cols = [c for c in r["df"].columns if "hnode" in c or "hpipe" in c]
            out["multi_columns"] = cols[:12]
    return out
