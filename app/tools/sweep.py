"""配置对比 / 参数扫描（1-2 参数网格）。每个点：配置构建器 → 耦合 LP 求解 → KPI 行。"""
from __future__ import annotations
import itertools, time
import numpy as np
from . import config_builder as B, sdco_engine as eng
from .cooling import MODES
from .heat_grade import TERMINALS

LABELS = {"cooling_mode": lambda v: MODES[v]["cn"].split("（")[0] if v in MODES else v, "terminal_type": lambda v: TERMINALS[v]["cn"] if v in TERMINALS else v}

def kpis(sc, r):
    th = r.get("thermal") or {}; S = th.get("dcs", {}); H = th.get("heat") or {}; df = r["df"]
    it = sum(S[d]["it_mwh"] for d in S) or 1e-9
    pue = sum(S[d]["it_mwh"]*S[d]["pue_avg"] for d in S)/it if S else None
    water = sum(S[d].get("water_m3", 0) for d in S)
    F = H.get("feasibility") or {}
    ct = r.get("cost_terms", {})
    energy = ct.get("grid_purchase", 0) + ct.get("local_gen", 0) + ct.get("export_revenue", 0) + ct.get("ppa", 0)
    cool = [S[d].get("cooling", {}) for d in S]
    return dict(pue=round(pue, 4) if pue else None, wue_l_kwh=round(water/it, 3), water_m3=round(water, 1),
                cooling_mwh=round(sum(S[d]["cooling_mwh"] for d in S), 2), dc_elec_mwh=round(sum(S[d]["elec_mwh"] for d in S), 1),
                energy_cost_cny=round(energy, 0), total_cost_cny=round(r["cost_cny"], 0), emissions_t=round(r["emissions_t"], 2),
                heat_delivered_mwh=H.get("delivered_mwh", 0.0), heat_cost_cny_gj=F.get("heat_cost_cny_gj"), terminal_margin_k=F.get("min_margin_k"),
                boost_mwh=H.get("boost_mwh", 0.0), heat_net_carbon_t=F.get("net_carbon_t"), heat_verdict=F.get("level", "—"),
                hp_cop=(f"{F['cop_min']}-{F['cop_max']}" if F else None), t_src_c=F.get("t_src_c"),
                tin_max_c=max((S[d]["tin_max_c"] for d in S), default=None), thermal_safe=th.get("safe", True),
                coolant_margin_k=min((c.get("coolant_margin_k", 99) for c in cool), default=None),
                curtail_mwh=round(r["curtail_mwh"], 1), solve_s=r["solver"]["time_s"])

def run_point(spec):
    t = time.time(); V = B.validate_spec(spec)
    if not V["ok"]: return dict(ok=False, error="；".join(V["errors"]))
    try:
        sc = B.build(spec); r = eng.solve(sc, True, levers=B.levers(spec))
        return dict(ok=True, **kpis(sc, r), warnings=V["warnings"], wall_s=round(time.time() - t, 2))
    except Exception as e:
        return dict(ok=False, error=f"{type(e).__name__}: {e}")

def _lab(path, v):
    k = path.split(".")[-1]; return LABELS.get(k, lambda x: x)(v)

def compare(base, variants):
    """variants=[{label, set:{path:value}}]"""
    rows = []
    for vv in variants:
        sp = B.full_spec(base)
        for p, x in (vv.get("set") or {}).items(): sp = B.set_path(sp, p, x)
        rows.append(dict(label=vv.get("label") or ",".join(f"{p}={x}" for p, x in vv.get("set", {}).items()), **run_point(sp)))
    return dict(ok=True, kind="compare", rows=rows)

def sweep(base, params):
    """params=[{path, values}]（1-2 个）。返回网格行。"""
    if not 1 <= len(params) <= 2: raise ValueError("扫描参数需 1-2 个")
    rows = []
    for combo in itertools.product(*[p["values"] for p in params]):
        sp = B.full_spec(base); lab = []
        for p, x in zip(params, combo): sp = B.set_path(sp, p["path"], x); lab.append(f"{p['path'].split('.')[-1]}={_lab(p['path'], x)}")
        rows.append(dict(label=" · ".join(lab), x=[_lab(p["path"], x) for p, x in zip(params, combo)], raw=list(combo), **run_point(sp)))
    return dict(ok=True, kind="sweep", params=[p["path"] for p in params], rows=rows)

COLS = [("pue", "PUE"), ("wue_l_kwh", "WUE L/kWh"), ("water_m3", "耗水 m³/日"), ("cooling_mwh", "冷却电 MWh"), ("dc_elec_mwh", "DC 用电 MWh"),
        ("energy_cost_cny", "电费 元/日"), ("total_cost_cny", "总成本(含售热/碳) 元"), ("emissions_t", "净碳 t/日"), ("heat_delivered_mwh", "供热 MWh"),
        ("t_src_c", "余热源 °C"), ("hp_cop", "热泵COP"), ("terminal_margin_k", "末端裕度 K"), ("boost_mwh", "补热 MWh"), ("heat_cost_cny_gj", "热成本 元/GJ"),
        ("heat_net_carbon_t", "供热净减碳 t"), ("heat_verdict", "余热供暖"), ("tin_max_c", "最高节点温度 °C"), ("thermal_safe", "热安全")]

def to_markdown(res):
    rows = res["rows"]; h = "| 配置 | " + " | ".join(c[1] for c in COLS) + " |\n|" + "---|"*(len(COLS) + 1) + "\n"
    for r in rows:
        h += f"| {r['label']} | " + (" | ".join(str(r.get(k, "")) for k, _ in COLS) if r.get("ok") else f"失败：{r.get('error')}" ) + " |\n"
    return h
