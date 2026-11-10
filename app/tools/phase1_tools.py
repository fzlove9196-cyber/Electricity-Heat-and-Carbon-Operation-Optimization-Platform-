"""Phase 1 工具：碳强度曲线、成本-碳 Pareto 扫描、任务级作业生成 / trace 加载。"""
from __future__ import annotations
import json, os
import numpy as np, pandas as pd
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
from .base import tool, Session
from .sim_tools import _art, _sc
from . import sdco_engine as eng
from ..scenario import generate_jobs as _gen, Link, DEFAULT_LINKS, carbon_profile, region_of

def _echarts(s, fname, option):
    with open(_art(s, fname), "w") as f: json.dump(option, f, ensure_ascii=False)
    return fname

@tool("get_carbon_profile", "查看当前场景各数据中心所在区域的逐时碳强度曲线（默认全国因子 0.5306 kgCO2/kWh × 合成日内形状）。"
      "适用于“碳强度/碳排放因子/碳曲线”。", {"type": "object", "properties": {}})
def get_carbon_profile(s: Session):
    sc = _sc(s); prof = {}
    for d in sc.data_centers: prof[f"{d.name}({region_of(sc, d.bus)})"] = [round(float(x), 4) for x in carbon_profile(sc, d.bus)]
    opt = {"title": {"text": "逐时碳强度 tCO2/MWh（合成）", "left": "center"}, "tooltip": {"trigger": "axis"}, "legend": {"top": 28},
           "xAxis": {"type": "category", "data": list(range(24)), "name": "小时"}, "yAxis": {"type": "value", "scale": True},
           "series": [{"name": k, "type": "line", "data": v} for k, v in prof.items()]}
    f = _echarts(s, "carbon_profile_echarts.json", opt)
    return {"ok": True, "source": sc.carbon_source, "factor": sc.carbon_factor, "shape": sc.carbon_shape,
            "profiles": prof, "daily_mean": {k: round(float(np.mean(v)), 4) for k, v in prof.items()}, "echarts": [f], "artifacts": [f]}

@tool("run_pareto_sweep", "成本-碳双目标 Pareto 扫描：改变碳权重 w（目标=成本+w×碳价×排放）多次求解优化调度，"
      "输出成本 vs 排放折线（ECharts 交互图 + PNG + CSV）。适用于“Pareto/帕累托/碳权重/成本与碳权衡/低碳调度”。", {
    "type": "object", "properties": {
        "weights": {"type": "array", "items": {"type": "number"}, "description": "碳权重列表，默认 [0,0.5,1,2,5,10,20,50]"},
        "carbon_price_cny_t": {"type": "number", "description": "碳价 元/t（可选，覆盖场景）"}}})
def run_pareto_sweep(s: Session, weights=None, carbon_price_cny_t=None):
    sc0 = _sc(s); weights = sorted(set(float(w) for w in (weights or [0, 0.5, 1, 2, 5, 10, 20, 50])))
    if any(w < 0 for w in weights): raise ValueError("weights 必须非负")
    pts = []
    for w in weights:
        sc = sc0.model_copy(deep=True); sc.carbon_weight = w
        if carbon_price_cny_t is not None: sc.carbon_price_cny_t = float(carbon_price_cny_t)
        r = eng.solve(sc, optimize=True)
        p = dict(weight=w, eff_carbon_price_cny_t=w*sc.carbon_price_cny_t, cost_cny=round(r["cost_cny"], 1), emissions_tco2=round(r["emissions_t"], 3),
                 gen_cost_cny=round(r["gen_cost"], 1), migrated_mwh=round(float(r["df"][[c for c in r["df"] if c.endswith("_mig_out")]].sum().sum()), 2))
        if "jobs" in r: p["jobs_deadline_met_pct"] = round(100*float(r["jobs"].met_deadline.mean()), 1)
        pts.append(p)
    b = eng.solve(sc0, optimize=False)
    base = dict(cost_cny=round(b["cost_cny"], 1), emissions_tco2=round(b["emissions_t"], 3))
    df = pd.DataFrame(pts); df.to_csv(_art(s, "pareto.csv"), index=False)
    fig, ax = plt.subplots(figsize=(7, 4.5))
    ax.plot(df.emissions_tco2, df.cost_cny/1e6, "-o", color="C2", label="优化（不同碳权重 w）")
    for r in pts: ax.annotate(f"w={r['weight']:g}", (r["emissions_tco2"], r["cost_cny"]/1e6), fontsize=7, xytext=(4, 4), textcoords="offset points")
    ax.plot([base["emissions_tco2"]], [base["cost_cny"]/1e6], "s", color="grey", label="基线")
    ax.set_xlabel("排放 tCO2/日"); ax.set_ylabel("成本（不含碳成本）百万元/日"); ax.set_title(f"成本-碳 Pareto 前沿（碳价 {pts and sc.carbon_price_cny_t} 元/t，合成数据）")
    ax.legend(); ax.grid(alpha=.3); fig.tight_layout(); fig.savefig(_art(s, "pareto.png"), dpi=110); plt.close(fig)
    opt = {"title": {"text": "成本-碳 Pareto 前沿（合成数据）", "left": "center"},
           "tooltip": {"trigger": "item"}, "legend": {"top": 28, "data": ["优化(w扫描)", "基线"]},
           "grid": {"left": 70, "right": 30, "top": 70, "bottom": 50},
           "xAxis": {"type": "value", "name": "排放 tCO2/日", "scale": True, "nameLocation": "middle", "nameGap": 28},
           "yAxis": {"type": "value", "name": "成本 元/日", "scale": True},
           "series": [{"name": "优化(w扫描)", "type": "line", "symbolSize": 10,
                       "data": [{"value": [p["emissions_tco2"], p["cost_cny"]], "name": f"w={p['weight']:g}"} for p in pts],
                       "label": {"show": True, "formatter": "{b}", "position": "top", "fontSize": 10}},
                      {"name": "基线", "type": "scatter", "symbol": "rect", "symbolSize": 12, "data": [{"value": [base["emissions_tco2"], base["cost_cny"]], "name": "基线"}]}]}
    _echarts(s, "pareto_echarts.json", opt)
    s.state["pareto"] = pts
    lo, hi = pts[0], pts[-1]
    return {"ok": True, "points": pts, "baseline": base,
            "tradeoff": dict(emission_reduction_pct=round((lo["emissions_tco2"]-hi["emissions_tco2"])/lo["emissions_tco2"]*100, 2),
                             cost_increase_pct=round((hi["cost_cny"]-lo["cost_cny"])/lo["cost_cny"]*100, 3),
                             abatement_cost_cny_t=round((hi["cost_cny"]-lo["cost_cny"])/max(lo["emissions_tco2"]-hi["emissions_tco2"], 1e-9), 1)),
            "echarts": ["pareto_echarts.json"], "artifacts": ["pareto.png", "pareto.csv", "pareto_echarts.json"]}

def _apply_jobs(s, sc, jobs, with_links=True, kappa=None):
    sc.jobs = jobs
    names = {d.name for d in sc.data_centers}
    if with_links and not sc.links: sc.links = [Link(**l) for l in DEFAULT_LINKS if l["a"] in names and l["b"] in names]
    if kappa is not None: sc.mig_energy_mwh_per_mwh = float(kappa)
    elif not sc.mig_energy_mwh_per_mwh: sc.mig_energy_mwh_per_mwh = 0.03
    errs = eng.validate(sc)
    if errs: raise ValueError("任务校验失败: " + "; ".join(errs[:5]))
    s.state["results"] = {}
    pd.DataFrame([j.model_dump() for j in jobs]).to_csv(_art(s, "jobs.csv"), index=False)
    with open(_art(s, "scenario.json"), "w") as f: f.write(sc.model_dump_json(indent=2))
    return {"ok": True, "n_jobs": len(jobs), "total_energy_mwh": round(sum(j.energy_mwh for j in jobs), 2),
            "latency_sensitive": sum(j.max_latency_ms is not None for j in jobs),
            "links": [(l.a, l.b, l.latency_ms, l.bw_mw) for l in sc.links], "mig_energy_mwh_per_mwh": sc.mig_energy_mwh_per_mwh,
            "sources": sorted({j.source for j in jobs}), "artifacts": ["jobs.csv", "scenario.json"]}

@tool("generate_jobs", "为当前场景生成合成任务级批处理作业（SYNTHETIC：释放时间、截止时间、能量、最大功率、时延敏感性），"
      "替代按 DC 聚合的批处理量；若无链路则加入默认链路（时延/带宽/迁移能耗）。适用于“任务/作业/截止时间/deadline”。", {
    "type": "object", "properties": {"n_jobs": {"type": "integer", "default": 30}, "seed": {"type": "integer", "default": 42},
                                     "latency_sensitive_share": {"type": "number", "default": 0.3},
                                     "mig_energy_mwh_per_mwh": {"type": "number", "description": "迁移能耗系数 κ，默认 0.03"}}})
def generate_jobs(s: Session, n_jobs=30, seed=42, latency_sensitive_share=0.3, mig_energy_mwh_per_mwh=None):
    sc = _sc(s)
    return _apply_jobs(s, sc, _gen(sc, int(n_jobs), int(seed), float(latency_sensitive_share)), kappa=mig_energy_mwh_per_mwh)

@tool("load_job_trace", "从 Alibaba cluster-trace-gpu-v2020（pai_task_table）或 Azure LLM Inference trace CSV 加载任务（按 target_mwh 缩放到场景规模）。"
      "path 为服务器上的 CSV 路径（可先上传到知识库目录 data/docs）。", {
    "type": "object", "properties": {"path": {"type": "string"}, "format": {"type": "string", "enum": ["alibaba_gpu", "azure_llm"]},
                                     "target_mwh": {"type": "number", "description": "缩放后的总 IT 能量 MWh"},
                                     "max_jobs": {"type": "integer", "default": 40}}, "required": ["path", "format"]})
def load_job_trace(s: Session, path, format, target_mwh=None, max_jobs=40):
    from .. import traces
    sc = _sc(s); names = [d.name for d in sc.data_centers]
    if not os.path.isfile(path): raise FileNotFoundError(f"找不到 trace 文件: {path}")
    if format == "alibaba_gpu": jobs = traces.load_alibaba_gpu(path, names, target_mwh or 0.8*sum(d.batch_mwh for d in sc.data_centers), int(max_jobs))
    elif format == "azure_llm": jobs = traces.load_azure_llm(path, names, target_mwh or 60.0)
    else: raise ValueError("format 必须是 alibaba_gpu 或 azure_llm")
    return _apply_jobs(s, sc, jobs)
