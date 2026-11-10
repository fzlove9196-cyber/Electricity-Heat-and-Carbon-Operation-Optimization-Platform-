"""智能体工具：散热方式库、配置构建器、配置对比/参数扫描、余热供暖可行性研究。"""
from __future__ import annotations
import json, os, re
from .base import Session, tool
from . import cooling as CL, config_builder as B, sweep as SW
from .heat_grade import TERMINALS

def _save(s, name, obj):
    os.makedirs(s.artifact_dir, exist_ok=True); p = os.path.join(s.artifact_dir, name)
    with open(p, "w", encoding="utf-8") as f:
        (f.write(obj) if isinstance(obj, str) else json.dump(obj, f, ensure_ascii=False, indent=1, default=str))
    if name not in s.artifacts: s.artifacts.append(name)
    return name

def _plot(s, res, fname, title):
    try:
        import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
        plt.rcParams["font.sans-serif"] = ["Noto Sans CJK SC", "WenQuanYi Zen Hei", "SimHei", "DejaVu Sans"]; plt.rcParams["axes.unicode_minus"] = False
        rows = [r for r in res["rows"] if r.get("ok")]
        if not rows: return None
        ks = [("pue", "PUE"), ("wue_l_kwh", "WUE L/kWh"), ("energy_cost_cny", "电费 元/日"), ("emissions_t", "净碳 tCO2/日"), ("heat_cost_cny_gj", "热成本 元/GJ"), ("terminal_margin_k", "末端裕度 K")]
        fig, ax = plt.subplots(2, 3, figsize=(14, 7)); lab = [r["label"] for r in rows]
        for a, (k, n) in zip(ax.flat, ks):
            a.bar(range(len(rows)), [r.get(k) or 0 for r in rows], color="#3b82f6"); a.set_title(n); a.set_xticks(range(len(rows))); a.set_xticklabels(lab, rotation=30, ha="right", fontsize=7)
        fig.suptitle(title); fig.tight_layout(); p = os.path.join(s.artifact_dir, fname); fig.savefig(p, dpi=110); plt.close(fig)
        if fname not in s.artifacts: s.artifacts.append(fname)
        return fname
    except Exception:
        return None

@tool("list_cooling_modes", "列出散热方式库（风冷冷冻水/间接蒸发/直接蒸发/冷板液冷/浸没液冷/混合）及其送回水温度、COP 曲线、自然冷却阈值、WUE、余热源温度、热安全边界与文献来源。", {"type": "object", "properties": {}})
def list_cooling_modes(s: Session):
    return dict(ok=True, modes=CL.library(), terminals=TERMINALS)

def _spec(s, spec):
    return B.full_spec(spec if spec else s.state.get("config_spec") or {})

@tool("build_config", "配置构建器：从空白模板（或在当前配置基础上修改）生成完整仿真场景并校验。可配置：数据中心数量/IT 容量/机柜/利用率/可调比例/散热方式/液冷比例、"
      "电池储能、蓄冷罐(水/冰)、蓄热罐、虚拟储冷/储热开关、热泵(常规/高温)、风/光/火/水/燃气/外网/PPA 电源规模、供热末端/管线长度/补热方式。", {
    "type": "object", "properties": {"spec": {"type": "object", "description": "配置 spec（见 config_builder.TEMPLATE）；缺省字段取模板"},
                                     "set": {"type": "object", "description": "在当前配置上做点路径修改，如 {'dcs.*.cooling_mode':'liquid_cold_plate','battery.energy_mwh':200}"}}})
def build_config(s: Session, spec=None, set=None):
    sp = _spec(s, spec)
    for p, v in (set or {}).items(): sp = B.set_path(sp, p, v)
    V = B.validate_spec(sp)
    if not V["ok"]: return dict(ok=False, errors=V["errors"], warnings=V["warnings"])
    sc = B.build(sp); s.state["scenario"] = sc; s.state["config_spec"] = V["spec"]; s.state["levers"] = B.levers(sp)
    s.state["origin"] = {"kind": "user", "name": "配置构建器"}; s.state["build_actor"] = "用户"
    s.state.pop("results", None); s.state["params_confirmed"] = False
    _save(s, "config_spec.json", V["spec"])
    return dict(ok=True, scenario=sc.name, warnings=V["warnings"], n_dc=len(sc.data_centers),
                dcs=[dict(name=d.name, cap_it_mw=d.cap_it_mw, cooling=CL.MODES[d.thermal.cooling_mode]["cn"], liquid_frac=CL.liquid_fraction(d.thermal),
                          tes_mwh=d.thermal.tes_mwh_th, hp_mw=d.thermal.hp_cap_mw_th) for d in sc.data_centers],
                battery_mwh=sum(x.energy_mwh for x in sc.storage), heat=(sc.heat_network.name if sc.heat_network else "无"), artifacts=["config_spec.json"])

@tool("set_cooling_mode", "为当前会话场景中的数据中心切换散热方式（适用于预设或构建器场景）。dc 为空=全部。", {
    "type": "object", "properties": {"mode": {"type": "string", "enum": list(CL.MODES)}, "dc": {"type": "string"}, "liquid_frac": {"type": "number"}}, "required": ["mode"]})
def set_cooling_mode(s: Session, mode, dc=None, liquid_frac=None):
    sc = s.state.get("scenario")
    if sc is None: return dict(ok=False, error="当前无场景，请先建模或 build_config")
    from ..scenario import DCThermal
    import sys; sys.path.insert(0, os.path.join(B.ROOT, "cases", "common")); from thermal_params import thermal_for
    sc.thermal_mode = "coupled"; ch = []
    for d in sc.data_centers:
        if dc and d.name != dc: continue
        if d.thermal is None: d.thermal = DCThermal(**thermal_for(d.cap_it_mw))
        CL.apply_mode(d.thermal, mode, liquid_frac, cap_it=d.cap_it_mw); ch.append(d.name)
    if s.state.get("config_spec"):
        sp = s.state["config_spec"]
        for x in sp["dcs"]:
            if x["name"] in ch: x["cooling_mode"] = mode; x["liquid_frac"] = liquid_frac
    s.state.pop("results", None)
    return dict(ok=True, changed=ch, mode=CL.MODES[mode]["cn"])

@tool("run_config_sweep", "配置对比 / 参数扫描：variants=[{label,set:{路径:值}}] 做并列对比；或 params=[{path,values}]（1-2 个参数网格扫描，如储能容量×散热方式）。"
      "每个点独立构建+求解耦合 LP，输出 KPI 表（PUE/WUE/电费/碳/供热量/末端温度裕度/热成本/余热供暖判定）与图。基准为当前会话配置（或 base）。", {
    "type": "object", "properties": {"base": {"type": "object"}, "variants": {"type": "array", "items": {"type": "object"}},
                                     "params": {"type": "array", "items": {"type": "object"}}, "title": {"type": "string"}}})
def run_config_sweep(s: Session, base=None, variants=None, params=None, title=None):
    b = _spec(s, base)
    res = SW.compare(b, variants) if variants else SW.sweep(b, params or [{"path": "dcs.*.cooling_mode", "values": ["air_chw", "air_iec", "liquid_cold_plate", "liquid_immersion"]}])
    k = len([x for x in s.artifacts if x.startswith("cfg_sweep_")])//3
    res["title"] = title or ("配置对比" if variants else "参数扫描")
    res["markdown"] = SW.to_markdown(res); res["columns"] = SW.COLS
    _save(s, f"cfg_sweep_{k}.json", res); _save(s, f"cfg_sweep_{k}.md", f"# {res['title']}\n\n" + res["markdown"])
    png = _plot(s, res, f"cfg_sweep_{k}.png", res["title"])
    s.state["last_sweep"] = res
    return dict(ok=True, kind=res["kind"], n=len(res["rows"]), rows=res["rows"], markdown=res["markdown"], artifacts=[f"cfg_sweep_{k}.json", f"cfg_sweep_{k}.md"] + ([png] if png else []))

@tool("heat_feasibility_study", "余热供暖可行性研究：对指定散热方式 × 末端类型(地暖/风机盘管/散热器/一次网) × 管线长度做网格，判定技术(末端供水温度是否满足)、经济(元/GJ)、碳(净减排)。", {
    "type": "object", "properties": {"modes": {"type": "array", "items": {"type": "string"}}, "terminals": {"type": "array", "items": {"type": "string"}},
                                     "lengths_km": {"type": "array", "items": {"type": "number"}}, "base": {"type": "object"}}})
def heat_feasibility_study(s: Session, modes=None, terminals=None, lengths_km=None, base=None):
    b = _spec(s, base); b["season"] = "winter"; b["heat"]["enabled"] = True
    if not any(d["hp_mw"] > 0 for d in b["dcs"]): b["dcs"][0]["hp_mw"] = round(0.3*b["dcs"][0]["cap_it_mw"], 1)
    modes = modes or ["air_chw", "liquid_cold_plate", "liquid_immersion"]; terminals = terminals or ["floor", "radiator", "primary"]; lengths_km = lengths_km or [1, 5, 10]
    out = []
    for m in modes:
        r = SW.sweep(B.set_path(b, "dcs.*.cooling_mode", m), [{"path": "heat.terminal_type", "values": terminals}, {"path": "heat.pipe_length_km", "values": lengths_km}])
        for x in r["rows"]: x["label"] = f"{CL.MODES[m]['cn'].split('（')[0]} · {x['label']}"; x["mode"] = m
        out += r["rows"]
    res = dict(ok=True, kind="heat_grid", rows=out, title="余热供暖可行性（散热方式×末端×距离）")
    res["markdown"] = SW.to_markdown(res); _save(s, "cfg_heat_feasibility.json", res); _save(s, "cfg_heat_feasibility.md", "# 余热供暖可行性\n\n" + res["markdown"])
    s.state["last_sweep"] = res
    return dict(ok=True, n=len(out), rows=out,
                artifacts=["cfg_heat_feasibility.json", "cfg_heat_feasibility.md"])

def parse_cfg_text(text):
    """中文 → spec 修改（mock 路由用）。"""
    st = {}
    for k, m in [("浸没", "liquid_immersion"), ("冷板", "liquid_cold_plate"), ("间接蒸发", "air_iec"), ("直接蒸发", "air_dec"), ("冷冻水", "air_chw"), ("混合", "hybrid")]:
        if k in text: st["dcs.*.cooling_mode"] = m; break
    if (x := re.search(r"(\d+(?:\.\d+)?)\s*MW\s*(?:IT|的?数据中心)", text, re.I)): st["dcs.*.cap_it_mw"] = float(x.group(1))
    if (x := re.search(r"储能\s*(\d+(?:\.\d+)?)\s*MWh", text, re.I)): st["battery.energy_mwh"] = float(x.group(1)); st["battery.power_mw"] = float(x.group(1))/2
    if (x := re.search(r"(\d+(?:\.\d+)?)\s*(?:km|公里)", text, re.I)): st["heat.pipe_length_km"] = float(x.group(1))
    for k, m in [("地暖", "floor"), ("风机盘管", "fcu"), ("散热器", "radiator"), ("一次网", "primary")]:
        if k in text: st["heat.terminal_type"] = m
    if "夏" in text: st["season"] = "summer"
    return st
