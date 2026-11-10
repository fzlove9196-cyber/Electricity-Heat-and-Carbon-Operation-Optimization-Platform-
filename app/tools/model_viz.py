"""通用“建模拓扑 + 能流”视图：从任意场景（IEEE14 / 自定义网络 / 中卫等预设）自动生成模型图数据。
build_model_graph(sc, result) -> 纯 JSON（母线/支路/设备/算力链路/电气岛/装机汇总/逐时潮流/能量桑基）。
前端 app/static/model_viz.js 负责渲染（同一份脚本也用于导出的独立 HTML）。"""
from __future__ import annotations
import json, os
import numpy as np
import networkx as nx
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
from .base import tool, Session
from . import sdco_engine as eng
from ..scenario import Scenario, pv_shape

STATIC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static")
KIND_CN = {"wind": "风电", "pv": "光伏", "thermal": "火电/常规机组", "hydro": "水电/可调度清洁电源", "grid": "外部电网购电", "ess": "储能", "dc": "数据中心", "load": "常规负荷",
           "cool": "冷却系统(冷机/自然冷却)", "tes": "蓄冷罐(虚拟储冷)", "hp": "余热热泵", "heatnet": "区域供热网(虚拟储热)", "pipe": "输热管线", "terminal": "供热末端用户"}
KIND_COLOR = {"wind": "#1abc9c", "pv": "#f1c40f", "thermal": "#7f5539", "hydro": "#2980b9", "grid": "#34495e", "ess": "#9b59b6", "dc": "#e67e22", "load": "#95a5a6",
              "cool": "#1c7ed6", "tes": "#74c0fc", "hp": "#e03131", "heatnet": "#c2255c", "pipe": "#f08c00", "terminal": "#d6336c"}
GEN_KIND_CN = {"hydro": "水电", "thermal": "火电", "gas": "燃气", "csp": "光热", "other": "其它"}
KV_COLOR = {750: "#c0392b", 500: "#8e44ad", 345: "#2471a3", 330: "#2471a3", 220: "#16a085", 138: "#2e86c1", 110: "#27ae60", 35: "#d4ac0d", 10: "#7f8c8d"}

_EXTRA = ["#2471a3", "#16a085", "#d35400", "#8e44ad", "#b7950b", "#7f8c8d"]

def kv_color(kv, levels=None):
    k = int(round(kv))
    if k in KV_COLOR: return KV_COLOR[k]
    if levels:   # 非标准电压等级：按等级高低分配区分色
        return _EXTRA[sorted(set(levels), reverse=True).index(kv) % len(_EXTRA)]
    return "#566573"

def is_wind(p) -> bool:
    if getattr(p, "kind", None): return p.kind == "wind"
    pr = p.profile or []
    return bool(pr) and len(pr) > 12 and pr[0] > 0.01 and pr[12] > 0.01 and min(pr) > 0.0     # 夜间有出力 → 风电

def _f(x, n=2):
    x = float(x); return None if not np.isfinite(x) else round(x, n)

def _layout(sc, nb, edges, names):
    """母线坐标（0..1）：中卫预设沿用人工布局；其它网络用 Kamada-Kawai（确定性），按电压等级分层微调。"""
    try:
        from .viz_tools import ZW_POS
        if all(n in ZW_POS for n in names):
            P = [ZW_POS[n] for n in names]; return _norm([(x, -y) for x, y in P])
    except Exception: pass
    G = nx.Graph(); G.add_nodes_from(range(nb)); G.add_edges_from(edges)
    pos = {}
    comps = sorted(nx.connected_components(G), key=len, reverse=True); off = 0.0
    for comp in comps:
        sub = G.subgraph(comp)
        p = nx.kamada_kawai_layout(sub) if len(comp) > 2 else {n: (i*0.5, 0.0) for i, n in enumerate(sorted(comp))}
        xs = [v[0] for v in p.values()]; w = (max(xs) - min(xs)) or 1
        for n, (x, y) in p.items(): pos[n] = (x - min(xs) + off, y)
        off += w + 0.6
    return _norm([pos[i] for i in range(nb)])

def _apply_layout(sc, pos, edges=()):
    """已保存布局优先；未保存的新母线放在已定位邻居附近（避免整体重排）。"""
    L = getattr(sc, "layout", None) or {}
    if not any(f"b{i}" in L for i in range(len(pos))): return pos
    out = [tuple(L[f"b{i}"]) if f"b{i}" in L else None for i in range(len(pos))]
    for _ in range(3):
        for i in range(len(out)):
            if out[i] is not None: continue
            nb = [out[b if a == i else a] for a, b in edges if i in (a, b) and out[b if a == i else a] is not None]
            if nb: out[i] = (float(np.mean([p[0] for p in nb])) + 0.07, float(np.mean([p[1] for p in nb])) + 0.10)
    k = 0
    for i in range(len(out)):
        if out[i] is None: out[i] = (0.05 + 0.12*k, 1.05); k += 1
    return out

def _norm(P):
    xs, ys = [p[0] for p in P], [p[1] for p in P]
    dx, dy = (max(xs) - min(xs)) or 1, (max(ys) - min(ys)) or 1
    return [((x - min(xs))/dx, (y - min(ys))/dy) for x, y in P]

def build_model_graph(sc: Scenario, result: dict | None = None, title: str | None = None) -> dict:
    N = eng.prepare_network(sc); net = N["net"]; nb, nl = N["nb"], N["nl"]
    custom = sc.network_case == "custom" and sc.network is not None
    names = [str(n) if isinstance(n, str) and n else f"Bus {i}" for i, n in enumerate(net.bus.name)]
    kv = [float(v) for v in net.bus.vn_kv]
    # ---- 支路 ----
    branches = []
    for i, r in net.line.iterrows():
        k = len(branches); nm = str(r["name"]) if isinstance(r["name"], str) and r["name"] else f"L{i}"
        branches.append(dict(id=f"br{k}", kind="line", name=nm, a=int(r.from_bus), b=int(r.to_bus), kv=kv[int(r.from_bus)],
                             rating_mw=_f(N["rating"][k], 1), parallel=int(r.get("parallel", 1) or 1),
                             params={"长度 km": _f(r.length_km), "r Ω/km": _f(r.r_ohm_per_km, 4), "x Ω/km": _f(r.x_ohm_per_km, 4),
                                     "并联回数": int(r.get("parallel", 1) or 1), "额定 MW(DC-OPF 约束)": _f(N["rating"][k], 1)}))
    for i, r in net.trafo.iterrows():
        k = len(branches); nm = str(r["name"]) if isinstance(r["name"], str) and r["name"] else f"T{i}"
        branches.append(dict(id=f"br{k}", kind="trafo", name=nm, a=int(r.hv_bus), b=int(r.lv_bus), kv=kv[int(r.hv_bus)],
                             rating_mw=_f(N["rating"][k], 1), parallel=int(r.get("parallel", 1) or 1),
                             params={"容量 MVA": _f(r.sn_mva, 1), "变比 kV": f"{_f(r.vn_hv_kv,1)}/{_f(r.vn_lv_kv,1)}", "uk %": _f(r.vk_percent),
                                     "并联台数": int(r.get("parallel", 1) or 1), "额定 MW(DC-OPF 约束)": _f(N["rating"][k], 1)}))
    # ---- 电气岛 ----
    G = nx.Graph(); G.add_nodes_from(range(nb)); G.add_edges_from((e["a"], e["b"]) for e in branches)
    comps = sorted(nx.connected_components(G), key=lambda c: min(c)); island = {}
    for k, c in enumerate(comps):
        for b in c: island[b] = k
    E = [(e["a"], e["b"]) for e in branches]
    pos = _apply_layout(sc, _layout(sc, nb, E, names), E)
    lp = eng.load_profile(sc)*sc.load_scale
    base = {b: float(net.load[net.load.bus == b].p_mw.sum()) for b in range(nb)}
    buses = [dict(id=f"b{i}", i=i, name=names[i], kv=kv[i], island=island[i], x=_f(pos[i][0], 4), y=_f(pos[i][1], 4),
                  base_load_mw=_f(base[i]*lp.max(), 1)) for i in range(nb)]
    # ---- 设备 ----
    dev = []
    egs = sc.network.ext_grids if custom else []
    for i, r in net.ext_grid.iterrows():
        e = egs[i] if i < len(egs) else None; cap = _f(r.max_p_mw, 1) if np.isfinite(r.max_p_mw) else None
        if cap is not None and cap >= 1e4: cap = None
        p = {"购电上限 MW": cap if cap is not None else "不限", "电压设定 pu": _f(r.vm_pu, 3)}
        if e and e.export_max_mw: p["外送上限 MW"] = e.export_max_mw
        if e and e.demand_charge_cny_mw_day: p["需量电费 元/MW·日"] = e.demand_charge_cny_mw_day
        dev.append(dict(id=f"grid{i}", kind="grid", name=str(r["name"] or f"外网{i}"), bus=int(r.bus), cap_mw=cap, params=p, gen_index=len(dev)))
    ng = len(dev)
    for i, r in net.gen.iterrows():
        dev.append(dict(id=f"gen{i}", kind="thermal", name=f"G{i}@Bus{int(r.bus)}", bus=int(r.bus), cap_mw=_f(r.max_p_mw, 1),
                        params={"Pmax MW": _f(r.max_p_mw, 1), "Pmin MW": _f(sc.gen_min_share*float(r.max_p_mw), 1),
                                "成本 元/MWh": sc.gen_cost[i % len(sc.gen_cost)]}, gen_index=ng + i))
    for i, gg in enumerate(sc.network.gens if custom else []):
        dev.append(dict(id=f"ngen{i}", kind="hydro" if gg.emission_t_mwh <= 0 else "thermal", name=gg.name, bus=gg.bus, cap_mw=gg.pmax_mw,
                        params={"类型": GEN_KIND_CN.get(gg.kind, gg.kind), "Pmax MW": gg.pmax_mw, "Pmin MW": gg.pmin_mw, "成本 元/MWh": gg.cost_cny_mwh,
                                "排放 t/MWh": gg.emission_t_mwh, "日电量上限 MWh": gg.energy_mwh_day if gg.energy_mwh_day is not None else "不限"},
                        gen_index=len(dev)))
    for i, p in enumerate(sc.pv):
        w = is_wind(p); prof = np.array(p.profile) if p.profile else np.repeat(pv_shape(),int(round(1/sc.dt_hours)))
        pr = {"装机 MW": p.cap_mw, "日可发电量 MWh": _f(sc.dt_hours*p.cap_mw*prof.sum(), 1), "利用小时(日)": _f(sc.dt_hours*prof.sum(), 2),
              "出力曲线": "自定义" if p.profile else "合成正弦"}
        if p.ppa_price_cny_kwh is not None: pr["PPA/直供价 元/kWh"] = p.ppa_price_cny_kwh
        dev.append(dict(id=f"re{i}", kind="wind" if w else "pv", name=p.name or f"{'风电' if w else '光伏'}{i+1}", bus=p.bus, cap_mw=p.cap_mw, params=pr))
    for s in sc.storage:
        dev.append(dict(id=f"ess:{s.name}", kind="ess", name=s.name, bus=s.bus, cap_mw=s.power_mw,
                        params={"功率 MW": s.power_mw, "容量 MWh": s.energy_mwh, "时长 h": _f(s.energy_mwh/max(s.power_mw, 1e-9), 2),
                                "效率 充/放": f"{s.eta_ch}/{s.eta_dis}", "SOC 范围": f"{s.soc_min}–{s.soc_max}", "初始 SOC": s.soc0}))
    for d in sc.data_centers:
        dev.append(dict(id=f"dc:{d.name}", kind="dc", name=d.name, bus=d.bus, cap_mw=_f(d.cap_it_mw*d.pue, 1),
                        params={"IT 容量 MW": d.cap_it_mw, "PUE": d.pue, "装机电网负荷上限（非实际峰值） MW": _f(d.cap_it_mw*d.pue, 1),
                                "交互负载 IT MW(均值)": _f(np.mean(d.interactive_mw), 2), "批处理 MWh/日": d.batch_mwh,
                                "区域": str(sc.bus_region.get(d.bus, "national"))}))
    thl = []   # 热/冷流连接（不同颜色）：DC → 冷却系统（冷）/ 蓄冷罐（冷）/ 热泵 → 供热网（热）
    for d in sc.data_centers:
        th = d.thermal
        if th is None: continue
        dim = "" if sc.thermal_mode == "coupled" else "（当前常数 PUE 模式，未启用）"
        from .cooling import MODES as _CM, source_temp as _st, liquid_fraction as _lf
        _md = _CM.get(th.cooling_mode or "")
        dev.append(dict(id=f"cool:{d.name}", kind="cool", name=(f"{_md['icon']}{_md['cn'].split('（')[0]} {d.name}" if _md else f"冷却 {d.name}"), bus=d.bus, cap_mw=th.chiller_cap_mw_th, thermal=True,
                        cooling_mode=th.cooling_mode,
                        params={**({"散热方式": _md["cn"], "送/回温度 °C": f"{_md['supply_c']}/{_md['return_c']}", "液冷比例": round(_lf(th), 2), "余热源 °C": _st(th),
                                    "WUE L/kWh": th.wue_l_kwh if th.wue_l_kwh is not None else _md["wue_l_kwh"], "典型 PUE": _md["pue_typical"]} if _md else {}),"冷机冷量 MW_th": th.chiller_cap_mw_th, "台数(N+1)": f"{th.chiller_units}({'是' if th.redundancy_n1 else '否'})", "COP_ref": th.cop_ref,
                                "自然冷却 MW_th": th.free_cap_mw_th, "入口温度 °C": f"{th.t_min_c}–{th.t_rec_max_c}(推荐)/{th.t_allow_max_c}(允许)", "热容 MWh/K": f"{th.c_air_mwh_k}+{th.c_mass_mwh_k}", "说明": "热安全硬约束" + dim}))
        thl.append(dict(a=f"dc:{d.name}", b=f"cool:{d.name}", kind="cold", label=(f"排热 回{_md['return_c']:g}/供{_md['supply_c']:g}°C" if _md else "排热")))
        if th.tes_mwh_th > 0:
            dev.append(dict(id=f"tes:{d.name}", kind="tes", name=f"蓄冷 {d.name}", bus=d.bus, cap_mw=th.tes_p_mw_th, thermal=True,
                            params={"容量 MWh_th": th.tes_mwh_th, "功率 MW_th": th.tes_p_mw_th, "自损失 /h": th.tes_loss_h}))
            thl.append(dict(a=f"tes:{d.name}", b=f"cool:{d.name}", kind="cold", label="蓄/放冷"))
        if th.hp_cap_mw_th > 0:
            dev.append(dict(id=f"hp:{d.name}", kind="hp", name=f"热泵 {d.name}", bus=d.bus, cap_mw=th.hp_cap_mw_th, thermal=True,
                            params={"供热 MW_th": th.hp_cap_mw_th, "COP": th.hp_cop, "可回收比例": th.hr_max_frac}))
            thl.append(dict(a=f"dc:{d.name}", b=f"hp:{d.name}", kind="heat", label=f"余热 {_st(th):.0f}°C"))
            if sc.heat_network is not None: thl.append(dict(a=f"hp:{d.name}", b="heatnet", kind="heat", label="供热"))
    if sc.heat_network is not None:
        hn = sc.heat_network; hb = next((d.bus for d in sc.data_centers if d.thermal and d.thermal.hp_cap_mw_th > 0), sc.data_centers[0].bus if sc.data_centers else 0)
        dev.append(dict(id="heatnet", kind="heatnet", name=hn.name, bus=hb, cap_mw=_f(max(hn.demand_mw_th), 1), thermal=True,
                        params={"峰值可接纳热负荷 MW_th": _f(max(hn.demand_mw_th), 1), "售热价 元/MWh_th": hn.price_cny_mwh_th, "替代锅炉 tCO2/MWh_th": hn.boiler_ef_t_mwh_th,
                                "蓄热 MWh_th": hn.storage_mwh_th, "管网热损": hn.pipe_loss}))
        if hn.terminal_type:
            from .heat_grade import terminal as _term, pipe as _pipe
            T_ = _term(hn); dT, ls = _pipe(hn)
            dev.append(dict(id="pipe", kind="pipe", name=f"输热管线 {hn.pipe_length_km:g}km", bus=hb, cap_mw=None, thermal=True,
                            params={"长度 km": hn.pipe_length_km, "沿程温降 K": round(dT, 2), "热损": round(ls, 3), "K/km": hn.pipe_dt_k_per_km}))
            dev.append(dict(id="terminal", kind="terminal", name=f"末端 {T_['cn']}", bus=hb, cap_mw=None, thermal=True,
                            params={"要求供水 °C": f"{T_['t_min']:g}-{T_['t_max']:g}", "回水 °C": T_["t_ret"], "补热方式": hn.booster}))
            thl.append(dict(a="heatnet", b="pipe", kind="heat", label=f"站出口≥{T_['t_max'] + dT:.0f}°C"))
            thl.append(dict(a="pipe", b="terminal", kind="heat", label=f"末端要求 {T_['t_min']:g}-{T_['t_max']:g}°C/回{T_['t_ret']:g}"))
    for i, ld in enumerate(sc.network.loads if custom else []):
        dev.append(dict(id=f"nload{i}", kind="load", name=ld.name, bus=ld.bus, cap_mw=_f(ld.p_mw*lp.max(), 1),
                        params={"峰值 MW": _f(ld.p_mw*lp.max(), 1), "基准 MW": ld.p_mw, "无功 Mvar": ld.q_mvar}))
    for b in range(nb):
        if base[b] > 1e-6 and not custom:
            dev.append(dict(id=f"load{b}", kind="load", name=f"负荷@{names[b]}", bus=b, cap_mw=_f(base[b]*lp.max(), 1),
                            params={"峰值 MW": _f(base[b]*lp.max(), 1), "基准 MW": _f(base[b], 2)}))
    links = [dict(a=l.a, b=l.b, latency_ms=l.latency_ms, bw_mw=l.bw_mw) for l in sc.links]
    if not links and len(sc.data_centers) > 1 and sc.mig_max_mw > 0:     # 未定义链路 = 全连接（仅受 mig_max_mw）
        D = [d.name for d in sc.data_centers]
        links = [dict(a=D[i], b=D[j], latency_ms=None, bw_mw=sc.mig_max_mw, implicit=True) for i in range(len(D)) for j in range(i+1, len(D))]
    # ---- 装机汇总 ----
    L = getattr(sc, "layout", None) or {}
    for x in dev:
        if f"dev:{x['id']}" in L: x["x"], x["y"] = L[f"dev:{x['id']}"]
    sm = lambda k: _f(sum((x["cap_mw"] or 0) for x in dev if x["kind"] == k), 1)
    grid_caps = [x["cap_mw"] for x in dev if x["kind"] == "grid"]
    summary = {"风电 MW": sm("wind"), "光伏 MW": sm("pv"), "火电/常规机组 MW": sm("thermal"), "水电/清洁可调 MW": sm("hydro"),
               "外网购电上限 MW": "不限" if any(c is None for c in grid_caps) else _f(sum(grid_caps), 1),
               "储能 MW": _f(sum(s.power_mw for s in sc.storage), 1), "储能 MWh": _f(sum(s.energy_mwh for s in sc.storage), 1),
               "数据中心装机负荷上限 MW": sm("dc"), "常规负荷峰值 MW": sm("load"),
               "母线数": nb, "线路数": nl, "变压器数": len(branches) - nl, "电气岛数": len(comps),
               "电压等级 kV": "/".join(f"{v:g}" for v in sorted(set(kv), reverse=True))}
    islands = []
    for k, c in enumerate(comps):
        islands.append(dict(id=k, buses=sorted(c), n_bus=len(c), has_grid=any(x["bus"] in c for x in dev if x["kind"] == "grid"),
                            gen_mw=_f(sum((x["cap_mw"] or 0) for x in dev if x["bus"] in c and x["kind"] in ("wind", "pv", "thermal", "hydro")), 1),
                            load_mw=_f(sum((x["cap_mw"] or 0) for x in dev if x["bus"] in c and x["kind"] in ("dc", "load")), 1)))
    g = dict(title=title or sc.name, network=("自定义等值网络" if custom else f"IEEE {sc.network_case[4:]} 节点"), synthetic=sc.synthetic,
             buses=buses, branches=branches, devices=dev, links=links, thermal_links=thl, thermal_mode=sc.thermal_mode, islands=islands, summary=summary,
             kv_colors={f"{v:g}": kv_color(v, kv) for v in sorted(set(kv), reverse=True)}, kind_cn=KIND_CN, kind_color=KIND_COLOR, solved=False)
    if result is not None: _add_flows(g, sc, N, result, base, lp)
    return g

def _add_flows(g, sc, N, r, base, lp):
    """由调度结果（逐时）重建母线注入 → DC 潮流（B-θ，与调度模型同口径），得到 24h 支路有功潮流。"""
    dt=r.get("solver",{}).get("resolution_h",1)
    g["dt_hours"]=dt;g["n_steps"]=len(r["df"])
    df = r["df"]; nb = N["nb"]; fb, tb, xb = N["fb"], N["tb"], N["xb"]; T = len(df)
    inj = np.zeros((nb, T)); dev = {d["id"]: d for d in g["devices"]}; dflow = {}
    for gi, ge in enumerate(r["gens"]):
        if f"gen{gi}_MW" in df:
            p = df[f"gen{gi}_MW"].values - (df[f"gen{gi}_export_MW"].values if f"gen{gi}_export_MW" in df else 0)
            inj[ge["bus"]] += p
            d = next((x for x in g["devices"] if x.get("gen_index") == gi), None)
            if d: dflow[d["id"]] = p
    share = df.pv_used.values/np.maximum(df.pv_avail.values, 1e-9)
    for i, p in enumerate(sc.pv):
        a = p.cap_mw*(np.array(p.profile) if p.profile else np.repeat(pv_shape(),int(round(1/sc.dt_hours))))[:T]*share; inj[p.bus] += a; dflow[f"re{i}"] = a
    for s in sc.storage:
        if s.name in r["storage"]:
            p = df[f"{s.name}_dis"].values - df[f"{s.name}_ch"].values; inj[s.bus] += p; dflow[f"ess:{s.name}"] = p
    for d in sc.data_centers:
        p = df[f"{d.name}_grid_MW"].values; inj[d.bus] -= p; dflow[f"dc:{d.name}"] = -p
    custom = sc.network_case == "custom" and sc.network is not None
    for b in range(nb):
        if base[b] > 1e-6: p = base[b]*lp[:T]; inj[b] -= p; dflow[f"load{b}"] = -p
    for i, ld in enumerate(sc.network.loads if custom else []): dflow[f"nload{i}"] = -ld.p_mw*lp[:T]
    Bm = np.zeros((nb, nb))
    for f, t, x in zip(fb, tb, xb):
        y = 1/x; Bm[f, f] += y; Bm[t, t] += y; Bm[f, t] -= y; Bm[t, f] -= y
    th = np.zeros((nb, T)); refs = set(N["refs"]); keep = [b for b in range(nb) if b not in refs]
    if keep:
        th[keep] = np.linalg.lstsq(Bm[np.ix_(keep, keep)], inj[keep]/eng.BASE_MVA, rcond=None)[0]
    flow = (th[fb] - th[tb])/xb[:, None]*eng.BASE_MVA
    for k, e in enumerate(g["branches"]):
        e["flow_mw"] = [round(float(v), 2) for v in flow[k]]
        e["max_loading_pct"] = _f(np.abs(flow[k]).max()/max(e["rating_mw"] or 1e-9, 1e-9)*100, 1)
        e["energy_mwh"] = _f(dt*np.abs(flow[k]).sum(), 1)
    if r.get("thermal"):
        for d in sc.data_centers:
            if f"{d.name}_chiller_MWth" in df:
                dflow[f"cool:{d.name}"] = df[f"{d.name}_chiller_MWth"].values + df[f"{d.name}_free_MWth"].values
                dflow[f"tes:{d.name}"] = df[f"{d.name}_tes_dis_MWth"].values - df[f"{d.name}_tes_ch_MWth"].values
                dflow[f"hp:{d.name}"] = df[f"{d.name}_hp_heat_MWth"].values
        if "heat_delivered_MWth" in df: dflow["heatnet"] = df["heat_delivered_MWth"].values; dflow["terminal"] = df["heat_delivered_MWth"].values
        if "heat_T_deliver_C" in df:
            for l in g.get("thermal_links", []):
                if l["a"] == "heatnet" and l["b"] == "pipe": l["label"] = f"站出口 {df['heat_T_plant_C'].max():.0f}°C(峰)"
                if l["a"] == "pipe" and l["b"] == "terminal":
                    l["label"] = f"末端供水 {df['heat_T_deliver_C'].min():.0f}~{df['heat_T_deliver_C'].max():.0f}°C / 要求≤{df['heat_T_req_C'].max():.0f}°C · 裕度 {df['heat_margin_K'].min():+.1f}K"
    for d in g["devices"]:
        if d["id"] in dflow: d["p_mw"] = [round(float(v), 2) for v in dflow[d["id"]]]
    tot = df.base_load_MW.values + df[[c for c in df if c.endswith("_grid_MW")]].sum(axis=1).values
    g["peak_physical_hour"]=dt*int(np.argmax(tot));g["peak_hour"] = int(np.argmax(tot)); g["solved"] = True; g["case"] = "optimized" if r.get("optimize") else "baseline"
    try:
        from .viz_tools import energy_balance
        F, ex = energy_balance(sc, r)
        if r.get("thermal") and "heat_delivered_MWth" in df:
            hp = dt*sum(df[f"{d.name}_hp_heat_MWth"].sum() for d in sc.data_centers if f"{d.name}_hp_heat_MWth" in df)
            hpe = dt*sum(df[f"{d.name}_hp_MW"].sum() for d in sc.data_centers if f"{d.name}_hp_MW" in df)
            if hp > 1e-6:
                F[("IT 余热", "热泵/换热站")] = float(hp - hpe); F[("热泵用电", "热泵/换热站")] = float(hpe)
                bst = dt*float(df["heat_boost_MWth"].sum()) if "heat_boost_MWth" in df else 0.0
                if bst > 1e-6: F[("调峰补热", "热泵/换热站")] = bst
                dl = dt*float(df["heat_delivered_MWth"].sum()); F[("热泵/换热站", "末端用户供热")] = dl; F[("热泵/换热站", "管网热损/蓄热")] = max(float(hp + bst - dl), 0.0)
        g["sankey"] = [dict(source=a, target=b, value=round(v, 2)) for (a, b), v in F.items()]
        g["sankey_note"] = f"日能量 MWh；迁移 {ex['migrated_mwh']:.1f} MWh，弃电 {ex['curtail_mwh']:.1f} MWh（DC-OPF 无损；热/在途存量详见审计，桑基仅展示）"
    except Exception as e:   # 能量平衡失败不影响拓扑
        g["sankey"] = []; g["sankey_note"] = f"桑基图生成失败：{e}"
    g["kpi"] = {"成本 元": _f(r.get("cost_cny", r["objective"]), 0), "弃电 MWh": _f(r["curtail_mwh"], 1),
                "新能源利用 MWh": _f(dt*df.pv_used.sum(), 1), "外网购电 MWh": _f(dt*df.grid_import_MW.sum(), 1) if "grid_import_MW" in df else None,
                "最大支路负载率 %": _f(max([e["max_loading_pct"] or 0 for e in g["branches"]] or [0]), 1)}

# ---------------- 静态 PNG（matplotlib） ----------------
MK = {"grid": "s", "thermal": "p", "hydro": "P", "wind": "^", "pv": "o", "ess": "D", "dc": "h", "load": "v", "cool": "*", "tes": "d", "hp": "X", "heatnet": "H", "pipe": "_", "terminal": "8"}

def draw_png(g, path, hour=None):
    fig, ax = plt.subplots(figsize=(15, 9.5)); W, H = 12.0, 7.0
    P = {b["i"]: (b["x"]*W, (1-b["y"])*H) for b in g["buses"]}  # JSON 中 y 向下
    hr = g.get("peak_hour") if hour is None else hour
    for e in g["branches"]:
        (x1, y1), (x2, y2) = P[e["a"]], P[e["b"]]
        ax.plot([x1, x2], [y1, y2], color=g["kv_colors"].get(f"{e['kv']:g}", "#566573"), lw=1.2 + e["parallel"], ls="-" if e["kind"] == "line" else "--", zorder=1)
        if g["solved"] and "flow_mw" in e:
            f = e["flow_mw"][hr]; sx, sy, tx, ty = (x1, y1, x2, y2) if f >= 0 else (x2, y2, x1, y1)
            if abs(f) > 0.05:
                ax.annotate("", xy=(sx+(tx-sx)*.62, sy+(ty-sy)*.62), xytext=(sx+(tx-sx)*.38, sy+(ty-sy)*.38),
                            arrowprops=dict(arrowstyle="-|>", color="#c0392b", lw=1.5, mutation_scale=14), zorder=4)
            ax.text((x1+x2)/2, (y1+y2)/2, f"{abs(f):.0f}MW", fontsize=7, color="#c0392b", zorder=5, bbox=dict(fc="white", ec="none", alpha=.7, pad=.5))
    nd = {}
    for d in g["devices"]:
        x, y = P[d["bus"]]; k = nd.get(d["bus"], 0); nd[d["bus"]] = k + 1
        ang = np.pi/2 + k*0.9; dx, dy = 0.55*np.cos(ang), 0.55*np.sin(ang)
        ax.plot([x, x+dx], [y, y+dy], color="#888", lw=.8, zorder=2)
        ax.plot(x+dx, y+dy, marker=MK[d["kind"]], ms=11, color=KIND_COLOR[d["kind"]], mec="k", zorder=6)
        cap = f"{d['cap_mw']:g}MW" if d["cap_mw"] is not None else "∞"
        ax.text(x+dx, y+dy+0.17, f"{d['name']} {cap}" if d["kind"] not in ("load",) else cap, fontsize=6.5, ha="center", zorder=7)
    for b in g["buses"]:
        x, y = P[b["i"]]; bc = g["kv_colors"].get(f"{b['kv']:g}", "#566573"); ax.plot(x, y, "s", ms=9, color=bc, zorder=5)
        ax.text(x, y-0.22, f"{b['name']} ({b['kv']:g}kV)", fontsize=7.5, ha="center", va="top", color=bc, fontweight="bold", zorder=7)
    ax.set_xlim(-1.2, W+1.2); ax.set_ylim(-1.2, H+1.2); ax.set_aspect("equal"); ax.axis("off")
    from matplotlib.lines import Line2D
    hd = [Line2D([], [], color=c, lw=4, label=f"{k} kV") for k, c in g["kv_colors"].items()]
    hd += [Line2D([], [], marker=MK[k], color="w", mfc=KIND_COLOR[k], mec="k", ms=10, label=KIND_CN[k]) for k in MK if k in {d["kind"] for d in g["devices"]} or k in ("grid", "wind", "pv", "dc")]
    ax.legend(handles=hd, loc="lower left", fontsize=8, ncol=5, framealpha=.95)
    s = g["summary"]
    txt = "  ".join(f"{k}:{v}" for k, v in s.items() if k in ("风电 MW", "光伏 MW", "火电/常规机组 MW", "储能 MW", "储能 MWh", "数据中心装机负荷上限 MW", "常规负荷峰值 MW"))
    ax.set_title(f"{g['title']} 模型拓扑（{g['network']}）" + (f" — {hr}:00 有功潮流" if g["solved"] else " — 建模视图（未求解，仅容量）") + "\n" + txt, fontsize=11)
    fig.tight_layout(); fig.savefig(path, dpi=110); plt.close(fig); return path

def export_html(g, path):
    ech = open(os.path.join(STATIC, "vendor", "echarts.min.js"), encoding="utf-8").read()
    mv = open(os.path.join(STATIC, "model_viz.js"), encoding="utf-8").read()
    data = json.dumps(g, ensure_ascii=False).replace("</", "<\\/")
    html = f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><title>{g['title']} 模型拓扑</title>
<style>body{{font:14px "Noto Sans CJK SC","Microsoft YaHei",sans-serif;margin:16px;background:#f5f7fb}}</style>
<script>{ech}</script><script>{mv}</script></head><body><div id="mv"></div>
<script>ModelViz.render(document.getElementById("mv"), {data}, {{standalone: true}});</script></body></html>"""
    with open(path, "w", encoding="utf-8") as f: f.write(html)
    return path

def refresh(s: Session, write_files: bool = True) -> dict:
    """依据会话当前场景（及已有优化/基线结果）重建模型图并写出 artifacts。"""
    from .sim_tools import _art
    sc = s.state.get("scenario")
    if sc is None: raise RuntimeError("尚未构建场景，请先调用 build_scenario")
    res = s.state.get("results", {}); r = res.get("optimized") or res.get("baseline")
    g = build_model_graph(sc, r); s.state["model_graph"] = g
    files = ["model_topology.json", "model_topology.png", "model_topology.html"]
    if write_files:
        with open(_art(s, files[0]), "w", encoding="utf-8") as f: json.dump(g, f, ensure_ascii=False)
        draw_png(g, _art(s, files[1])); export_html(g, _art(s, files[2]))
    return g

def brief(g):
    return {"network": g["network"], "solved": g["solved"], "summary": g["summary"],
            "islands": [(i["id"], i["n_bus"], "含外网" if i["has_grid"] else "孤岛") for i in g["islands"]],
            "devices": [(KIND_CN[d["kind"]], d["name"], g["buses"][d["bus"]]["name"], d["cap_mw"]) for d in g["devices"] if d["kind"] != "load"]}

@tool("show_model_topology", "通用建模视图：从当前场景自动生成“模型拓扑 + 能流”图（母线/电压等级、线路/变压器、每台电源类型与装机[风/光/火/外网]、储能功率/容量及接入母线、"
      "数据中心负荷与算力迁移链路、电气岛）与装机汇总表；已求解时叠加逐时支路潮流方向/大小与能量桑基图。适用于任意网络（IEEE14/自定义/预设）。"
      "build_scenario 与 run_dispatch 会自动刷新，用户想核对模型、问“模型怎么建的/装机多少/母线怎么接/能流”时调用。输出 PNG + 可交互 HTML。", {
    "type": "object", "properties": {}})
def show_model_topology(s: Session):
    g = refresh(s)
    return {"ok": True, "model_view": "model_topology.json", **brief(g),
            "artifacts": ["model_topology.png", "model_topology.html", "model_topology.json"]}
