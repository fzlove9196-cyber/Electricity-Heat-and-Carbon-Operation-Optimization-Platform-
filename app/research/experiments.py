"""实验执行：在基准场景上施加修改(mods)→求解→KPI→紧约束→诊断，结果登记为 run（R1, R2 …）。全部确定性。"""
from __future__ import annotations
import copy, json, os, time
import numpy as np
from ..scenario import Scenario
from ..tools import sdco_engine as eng
from ..tools.sim_tools import _kpis

KEY_KPIS = ["cost_cny", "emissions_tco2", "pue_avg", "pue_max", "pue_min", "tin_max_c", "tin_air_max_c", "coolant_supply_max_c", "thermal_margin_k", "hours_above_rec", "thermal_violations",
            "heat_delivered_mwh", "heat_revenue_cny", "carbon_heat_offset_tco2", "heat_verdict", "terminal_margin_k", "heat_cost_cny_gj", "heat_boost_mwh",
            "dr_delivered_mwh", "dr_requested_mwh", "dr_revenue_cny", "cooling_mwh", "tes_discharge_mwh_th", "free_cooling_mwh_th",
            "grid_import_mwh", "grid_export_mwh", "dc_energy_mwh", "renewable_curtail_pct", "max_line_loading_pct", "erf", "water_m3"]
KPI_CN = {"cost_cny": "日净成本(元)", "emissions_tco2": "排放(tCO2)", "pue_avg": "平均PUE", "pue_max": "最大PUE", "pue_min": "最小PUE", "tin_max_c": "最高入口温度(°C)", "tin_air_max_c": "风冷最高入口(°C)", "coolant_supply_max_c": "液冷最高供液(°C)",
          "thermal_margin_k": "距允许上限裕度(K)", "hours_above_rec": "超推荐温度小时", "thermal_violations": "热安全违规数", "heat_delivered_mwh": "供热量(MWh_th)",
          "heat_revenue_cny": "售热收入(元)", "carbon_heat_offset_tco2": "供热抵扣碳(tCO2)", "heat_verdict": "余热供暖判定", "terminal_margin_k": "末端温度裕度(K)",
          "heat_cost_cny_gj": "余热热成本(元/GJ)", "heat_boost_mwh": "调峰补热(MWh_th)", "dr_delivered_mwh": "DR 实际响应(MWh)", "dr_requested_mwh": "DR 请求(MWh)",
          "dr_revenue_cny": "DR 收入(元)", "cooling_mwh": "冷却用电(MWh)", "tes_discharge_mwh_th": "蓄冷放冷(MWh_th)", "free_cooling_mwh_th": "自然冷却(MWh_th)",
          "grid_import_mwh": "外网购电(MWh)", "grid_export_mwh": "外网送出(MWh)", "dc_energy_mwh": "数据中心用电(MWh)", "renewable_curtail_pct": "弃电率(%)",
          "max_line_loading_pct": "最大线路负载率(%)", "erf": "能量再利用系数ERF", "water_m3": "耗水(m³)"}

# ---------------- 路径修改 ----------------
def _resolve(obj, keys):
    """返回 [(parent, key)] 列表，支持 * 通配与整数下标。"""
    cur = [(None, None, obj)]
    for k in keys:
        nxt = []
        for _, _, o in cur:
            if o is None: continue
            if k == "*":
                items = list(enumerate(o)) if isinstance(o, list) else list(o.items()) if isinstance(o, dict) else []
                nxt += [(o, i, v) for i, v in items]
            elif isinstance(o, list): nxt.append((o, int(k), o[int(k)]))
            elif isinstance(o, dict): nxt.append((o, k, o.get(k)))
            else:
                if not hasattr(o, k): raise ValueError(f"参数路径不存在：{'.'.join(keys)}（{k}）")
                nxt.append((o, k, getattr(o, k)))
        cur = nxt
    return cur

def _setv(parent, key, val):
    if isinstance(parent, (list, dict)): parent[key] = val
    else: setattr(parent, key, val)

AIR_INLET_KEYS = ("t_allow_max_c", "t_rec_max_c", "t_min_c")

def apply_mod(sc: Scenario, path: str, value):
    """value 可为常量或 {"op": "add"|"mul"|"set", "value": x}；对列表值（如 outdoor_temp_c）逐元素运算。"""
    op = value.get("op", "set") if isinstance(value, dict) and "op" in value else "set"
    x = value["value"] if isinstance(value, dict) and "op" in value else value
    n = 0
    from ..tools.cooling import node_is_liquid
    air_std = op == "set" and "*" in path and path.split(".")[-1] in AIR_INLET_KEYS
    for parent, key, cur in _resolve(sc, path.split(".")):
        if parent is None: continue
        if air_std and node_is_liquid(parent): continue   # 风冷入口温度标准不施加到液冷供液节点（否则 32°C < 供液 40°C 必然不可行）
        if op == "set": new = x
        elif isinstance(cur, list): new = [round(c + x, 4) if op == "add" else round(c*x, 4) for c in cur]
        elif cur is None: continue
        else: new = cur + x if op == "add" else cur*x
        _setv(parent, key, new); n += 1
    if n == 0 and "*" not in path: raise ValueError(f"路径 {path} 未匹配到任何参数")
    return n

def apply_mods(sc: Scenario, mods: dict) -> Scenario:
    sc = copy.deepcopy(sc)
    for p, v in (mods or {}).items():
        if p == "__remove_heat__":
            sc.heat_network = None
            for d in sc.data_centers:
                if d.thermal: d.thermal.hp_cap_mw_th = 0.0
        elif p == "__no_dr__": sc.dr_events = []
        else:
            if p == "heat_network.terminal_type" and sc.heat_network is not None and v != sc.heat_network.terminal_type \
                    and not any(k in (mods or {}) for k in ("heat_network.t_supply_min_c", "heat_network.t_supply_max_c", "heat_network.t_return_c")):
                sc.heat_network.t_supply_min_c = sc.heat_network.t_supply_max_c = sc.heat_network.t_return_c = None   # 换末端：清除原末端的供回水覆盖值
            apply_mod(sc, p, v)
    return Scenario.model_validate(sc.model_dump())

def describe_mods(mods):
    D = {"__remove_heat__": "不回收余热（热泵=0，无供热网）", "__no_dr__": "不参与需求响应"}
    out = []
    for p, v in (mods or {}).items():
        if p in D: out.append(D[p]); continue
        if isinstance(v, dict) and "op" in v: out.append(f"{p} {'+' if v['op'] == 'add' else '×'}{v['value']}")
        else: out.append(f"{p}={v}")
    return "；".join(out) or "基准模型（无修改）"

# ---------------- 运行登记 ----------------
def _hourly(sc, r):
    df = r["df"]; dcs = [d.name for d in sc.data_centers if f"{d.name}_Tin_C" in df]
    H = dict(hour=list(range(len(df))), price=df.price.round(3).tolist())
    if dcs:
        H["tin_max_c"] = df[[f"{d}_Tin_C" for d in dcs]].max(axis=1).round(2).tolist()
        H["tout_c"] = df[f"{dcs[0]}_Tout_C"].round(2).tolist()
        H["pue"] = df[[f"{d}_PUE" for d in dcs]].mean(axis=1).round(3).tolist()
        H["it_mw"] = df[[f"{d}_IT_MW" for d in dcs]].sum(axis=1).round(2).tolist()
    for c in ("grid_import_MW", "grid_export_MW", "heat_del_MWth", "heat_delivered_MWth"):
        if c in df: H[c] = df[c].round(2).tolist()
    hp = [c for c in df if c.endswith("_hp_heat_MWth")]
    if hp: H["hp_heat_mwth"] = df[hp].sum(axis=1).round(2).tolist()
    return H

def run_variant(study: dict, base: Scenario, label: str, mods: dict | None = None, purpose: str = "", step_id: str | None = None,
                artifact_dir: str | None = None, optimize: bool = True) -> dict:
    from .diagnostics import diagnose
    rid = f"R{len(study.setdefault('runs', {})) + 1}"
    t0 = time.time(); run = dict(id=rid, label=label, mods=mods or {}, mods_desc=describe_mods(mods), purpose=purpose, step=step_id,
                                 ts=time.strftime("%H:%M:%S"), optimize=optimize)
    try:
        sc = apply_mods(base, mods)
        errs = eng.validate(sc)
        if errs: raise ValueError("场景校验失败: " + "; ".join(errs))
        r = eng.solve(sc, optimize=optimize)
        k = _kpis(sc, r)
        run.update(status="optimal", kpis={x: k[x] for x in KEY_KPIS if x in k}, binding=(r.get("binding") or [])[:6],
                   cost_terms={a: round(b, 1) for a, b in (r.get("cost_terms") or {}).items()},
                   solver={x: r["solver"][x] for x in ("status", "time_s", "n_vars", "n_constraints", "gap_pct")},
                   dr=[{x: e.get(x) for x in ("name", "kind", "requested_mwh", "delivered_mwh", "revenue_cny")} for e in (r.get("dr") or [])],
                   hourly=_hourly(sc, r), _r=r, _sc=sc)
        if artifact_dir:
            os.makedirs(artifact_dir, exist_ok=True); r["df"].to_csv(os.path.join(artifact_dir, f"study_{rid}.csv"), index=False)
            run["artifact"] = f"study_{rid}.csv"
    except Exception as e:
        msg = f"{type(e).__name__}: {e}"
        run.update(status="infeasible" if "infeasible" in msg.lower() or "求解失败" in msg else "error", error=msg, kpis={}, binding=[], _sc=locals().get("sc"))
    run["elapsed_s"] = round(time.time() - t0, 2)
    run["findings"] = diagnose(run)
    study["runs"][rid] = run
    return run

def public_run(run):
    return {k: v for k, v in run.items() if not k.startswith("_")}

def delta(a: dict, b: dict, keys=None):
    """b − a，数值 KPI 差。"""
    out = {}
    for k in keys or KEY_KPIS:
        x, y = a.get(k), b.get(k)
        if isinstance(x, (int, float)) and isinstance(y, (int, float)): out[k] = round(y - x, 3)
    return out
