"""拓扑 / 能流可视化工具：plot_topology（单线图 + 可选峰时潮流）、plot_energy_flow（能量桑基 + 逐时堆叠）。
全部从当前场景 JSON 与调度/交流校核结果读取，不虚构元件。输出 ECharts JSON（聊天界面交互）+ matplotlib PNG。"""
from __future__ import annotations
import json
import numpy as np
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import Patch
from .base import tool, Session
from .sim_tools import _art, _sc, _res
from . import sdco_engine as eng

KV_COLOR = {750: "#c0392b", 500: "#8e44ad", 330: "#2471a3", 220: "#16a085", 110: "#27ae60"}
def kv_color(kv): return KV_COLOR.get(int(round(kv)), "#7f8c8d")

# 中卫案例来源标注（按元件名）：S=来源公开报道，T=拓扑来源报道但参数假设，A=假设/等值
ZW_PROV = {"沙坡头750kV": "T", "天都山750kV": "T", "塞上330kV": "T", "大唐光伏升压站330kV": "T", "110kV开关站A": "T", "110kV开关站B": "T",
           "风电330kV升压站(3座等值)": "T", "光伏直供110kV母线": "A", "存量DC 110kV": "A", "沙坡头330kV侧": "A", "上海DC 110kV(华东)": "A",
           "沙坡头-天都山750": "A", "光伏站-沙坡头330(π接)": "T", "光伏站-塞上330(π接)": "T", "直供110kV-开关站A(2回)": "T", "直供110kV-开关站B(2回)": "T",
           "沙坡头750/330": "A", "天都山750/330(风电)": "T", "光伏站330/110": "A", "塞上330/110(存量DC)": "A",
           "ZW_EXIST": "S", "ZW_NEW_A": "S", "ZW_NEW_B": "S", "SH_EAST": "A", "ESS_ZW": "A", "西北电网(宁夏)": "T", "华东电网(上海)": "A"}
PROV_TXT = {"S": "来源报道", "T": "拓扑来源/参数假设", "A": "假设/等值", "?": "未标注"}
PROV_MARK = {"S": "", "T": "‡", "A": "†", "?": ""}
ZW_POS = {"沙坡头750kV": (2.0, 3.0), "天都山750kV": (6.5, 3.0), "沙坡头330kV侧": (1.0, 2.0), "大唐光伏升压站330kV": (2.8, 2.0),
          "塞上330kV": (4.6, 2.0), "风电330kV升压站(3座等值)": (6.5, 2.0), "光伏直供110kV母线": (2.8, 1.1), "110kV开关站A": (1.8, 0.3),
          "110kV开关站B": (3.8, 0.3), "存量DC 110kV": (4.6, 1.1), "上海DC 110kV(华东)": (9.0, 1.1)}

def _prov(name): return ZW_PROV.get(name, "?")

def _is_wind(p):
    if getattr(p, "kind", None): return p.kind == "wind"
    pr = p.profile or []
    return bool(pr) and pr[0] > 0.01 and pr[12] > 0.01      # 夜间有出力 → 风电

def bus_pos(sc):
    B = sc.network.buses
    if all(b.name in ZW_POS for b in B): return [ZW_POS[b.name] for b in B]
    lv = sorted({b.vn_kv for b in B}, reverse=True); pos, cnt = [], {}
    for b in B:
        k = cnt.get(b.vn_kv, 0); cnt[b.vn_kv] = k + 1; pos.append((1.6*k, 3.0 - 1.0*lv.index(b.vn_kv)))
    return pos

def topology_elements(sc):
    """返回 buses / branches / devices（含参数与来源标注），全部取自场景。"""
    if sc.network is None: raise RuntimeError("plot_topology 需要 network_case='custom' 的场景（含 network.buses/lines/trafos）")
    nw = sc.network; pos = bus_pos(sc)
    buses = [dict(i=i, name=b.name, kv=b.vn_kv, pos=pos[i], prov=_prov(b.name)) for i, b in enumerate(nw.buses)]
    br = []
    for l in nw.lines:
        z = complex(l.r_ohm_per_km, l.x_ohm_per_km)*l.length_km/l.parallel
        br.append(dict(kind="line", name=l.name, a=l.from_bus, b=l.to_bus, kv=nw.buses[l.from_bus].vn_kv, parallel=l.parallel, prov=_prov(l.name),
                       label=f"{l.length_km:g}km {l.parallel}×{l.rating_mva:g}MVA Z={z.real:.2f}+j{z.imag:.2f}Ω"))
    for t in nw.trafos:
        br.append(dict(kind="trafo", name=t.name, a=t.hv_bus, b=t.lv_bus, kv=nw.buses[t.hv_bus].vn_kv, parallel=t.parallel, prov=_prov(t.name),
                       label=f"{t.parallel}×{t.sn_mva:g}MVA uk={t.vk_percent:g}%"))
    dev = []
    for e in nw.ext_grids:
        dev.append(dict(kind="ext", name=e.name, bus=e.bus, prov=_prov(e.name), dx=0.0, dy=0.55,
                        label=f"{e.name} V={e.vm_pu}pu" + (f" 外送≤{e.export_max_mw:g}MW" if e.export_max_mw else "")))
    for p in sc.pv:
        w = _is_wind(p); nm = "风电" if w else "光伏"
        dev.append(dict(kind="wind" if w else "pv", name=f"{nm}{p.cap_mw:g}MW", bus=p.bus, prov="S" if sc.network.buses[p.bus].name in ZW_POS else "?",
                        dx=0.9 if w else -0.9, dy=0.35 if w else 0.0, label=f"{nm} {p.cap_mw:g} MW"))
    for s in sc.storage:
        dev.append(dict(kind="ess", name=s.name, bus=s.bus, prov=_prov(s.name), dx=0.9, dy=0.0, label=f"储能 {s.power_mw:g}MW/{s.energy_mwh:g}MWh"))
    nd = {}
    for d in sc.data_centers:
        k = nd.get(d.bus, 0); nd[d.bus] = k + 1
        dev.append(dict(kind="dc", name=d.name, bus=d.bus, prov=_prov(d.name), dx=0.0 + 0.9*k, dy=-0.6,
                        label=f"{d.name} 装机上限{d.cap_it_mw*d.pue:.0f}MW (IT{d.cap_it_mw:g}×PUE{d.pue:g})"))
    links = [dict(a=l.a, b=l.b, latency_ms=l.latency_ms, bw_mw=l.bw_mw) for l in sc.links]
    return buses, br, dev, links

DEV_STYLE = {"ext": ("s", "#34495e", "外部电网"), "pv": ("o", "#f1c40f", "光伏"), "wind": ("^", "#1abc9c", "风电"),
             "ess": ("D", "#9b59b6", "储能"), "dc": ("h", "#e67e22", "数据中心")}

def draw_topology(sc, path, ac=None, title=None):
    buses, br, dev, links = topology_elements(sc)
    fig, ax = plt.subplots(figsize=(17, 10.5)); P = {b["i"]: b["pos"] for b in buses}
    for e in br:
        (x1, y1), (x2, y2) = P[e["a"]], P[e["b"]]
        c = kv_color(e["kv"]); lw = 1.6 + 1.2*e["parallel"]
        ls = "-" if e["prov"] != "A" else (0, (6, 2))
        ax.plot([x1, x2], [y1, y2], color=c, lw=lw, ls=ls, zorder=1, solid_capstyle="butt")
        if e["kind"] == "trafo":
            mx, my = (x1+x2)/2, (y1+y2)/2
            for dy, cc in ((0.07, c), (-0.07, kv_color(sc.network.buses[e["b"]].vn_kv))):
                ax.add_patch(plt.Circle((mx, my+dy), 0.1, fill=False, ec=cc, lw=2, zorder=3))
        fr = 0.62 if e["kind"] == "line" and abs(y1-y2) > 0.3 else 0.5
        mx, my = x1+(x2-x1)*fr, y1+(y2-y1)*fr
        txt = f"{e['name']}{PROV_MARK[e['prov']]}\n{e['label']}"
        if ac is not None:
            pm = (ac.get("line_p_from_mw") if e["kind"] == "line" else ac.get("trafo_p_hv_mw", {})).get(e["name"])
            ld = (ac.get("line_loading_pct") if e["kind"] == "line" else ac.get("trafo_loading_pct", {})).get(e["name"])
            if pm is not None:
                sx, sy, tx, ty = (x1, y1, x2, y2) if pm >= 0 else (x2, y2, x1, y1)
                f0, f1 = 0.30, 0.70
                ax.annotate("", xy=(sx+(tx-sx)*f1, sy+(ty-sy)*f1), xytext=(sx+(tx-sx)*f0, sy+(ty-sy)*f0),
                            arrowprops=dict(arrowstyle="-|>", color="k", lw=2.2, mutation_scale=22), zorder=5)
                lc = "#c0392b" if ld and ld > 80 else "#d35400" if ld and ld > 50 else "#1e8449"
                txt = f"{e['name']}\n{abs(pm):.0f} MW  负载率 {ld:.1f}%"
                ax.text(mx+0.08, my+0.08, txt, fontsize=9, color=lc, fontweight="bold", zorder=6,
                        bbox=dict(fc="white", ec=lc, alpha=.9, boxstyle="round,pad=0.2")); continue
        ax.text(mx+0.06, my+0.06, txt, fontsize=7.5, color="#222", zorder=6, bbox=dict(fc="white", ec="none", alpha=.75, pad=1))
    for b in buses:
        x, y = b["pos"]; c = kv_color(b["kv"])
        ax.plot([x-0.45, x+0.45], [y, y], color=c, lw=7, solid_capstyle="butt", zorder=4)
        vm = f"  {ac['bus_vm_pu'][b['name']]:.3f}pu" if ac and b["name"] in ac.get("bus_vm_pu", {}) else ""
        ax.text(x, y-0.13, f"[{b['i']}] {b['name']}{PROV_MARK[b['prov']]}{vm}", ha="center", va="top", fontsize=8.5, fontweight="bold", color=c, zorder=6)
    for d in dev:
        x, y = P[d["bus"]]; dx, dy = d["dx"], d["dy"]; m, c, _ = DEV_STYLE[d["kind"]]
        ax.plot([x+dx*0.5, x+dx], [y, y+dy], color="#555", lw=1, zorder=2); ax.plot([x, x+dx*0.5], [y, y], color="#555", lw=1, zorder=2)
        ax.plot(x+dx, y+dy, marker=m, ms=17, color=c, mec="k" if d["prov"] != "A" else "#c0392b", mew=1.2 if d["prov"] != "A" else 2.2, zorder=7)
        lab = d["label"] + PROV_MARK[d["prov"]]
        if ac is not None and d["kind"] == "ext" and d["name"] in ac.get("ext_grid_p_mw", {}):
            pe = ac["ext_grid_p_mw"][d["name"]]; lab += f"\n{'受入' if pe >= 0 else '送出'} {abs(pe):.0f} MW"
        ax.text(x+dx, y+dy+(0.2 if dy >= 0 else -0.22), lab, ha="center", va="bottom" if dy >= 0 else "top", fontsize=8, zorder=8)
    dcpos = {d["name"]: (P[d["bus"]][0]+d["dx"], P[d["bus"]][1]+d["dy"]) for d in dev if d["kind"] == "dc"}
    for k, l in enumerate(links):
        if l["a"] in dcpos and l["b"] in dcpos:
            (x1, y1), (x2, y2) = dcpos[l["a"]], dcpos[l["b"]]
            rad = 0.25 if abs(x1-x2) > 3 else 0.35
            ax.annotate("", xy=(x2, y2), xytext=(x1, y1), arrowprops=dict(arrowstyle="<->", color="#8e44ad", ls="--", lw=1.3,
                        connectionstyle=f"arc3,rad={rad}"), zorder=2)
            t = 0.5; mx, my = (x1+x2)/2, (y1+y2)/2 - rad*abs(x2-x1)*0.5 - 0.02*k
            ax.text(mx, my, f"{l['latency_ms']:g}ms/{l['bw_mw']:g}MW", fontsize=7, color="#8e44ad", ha="center",
                    bbox=dict(fc="white", ec="none", alpha=.7, pad=0.5))
    xs = [p[0] for p in P.values()]; ys = [p[1] for p in P.values()]
    ax.set_xlim(min(xs)-1.6, max(xs)+1.8); ax.set_ylim(min(ys)-1.9, max(ys)+1.0); ax.set_aspect("equal"); ax.axis("off")
    kvs = sorted({b["kv"] for b in buses}, reverse=True)
    hd = [Line2D([], [], color=kv_color(k), lw=5, label=f"{k:g} kV") for k in kvs]
    hd += [Line2D([], [], color="k", lw=1.5, ls="-", label="实线=拓扑来源报道 ‡"), Line2D([], [], color="k", lw=1.5, ls=(0, (6, 2)), label="虚线=假设/等值支路 †"),
           Line2D([], [], color="#8e44ad", ls="--", label="算力迁移链路(时延/带宽, 假设)")]
    hd += [Line2D([], [], marker=m, color="w", mfc=c, mec="k", ms=12, label=n) for m, c, n in DEV_STYLE.values()]
    hd += [Line2D([], [], marker="o", color="w", mfc="w", mec="#c0392b", mew=2.2, ms=12, label="红框=假设设备 †")]
    ax.legend(handles=hd, loc="lower left", fontsize=8.5, ncol=4, framealpha=.95)
    ax.set_title(title or f"{sc.name} 系统拓扑（单线图）  † 假设/等值  ‡ 拓扑来源报道、参数假设  线宽∝并联回数", fontsize=13)
    fig.tight_layout(); fig.savefig(path, dpi=120); plt.close(fig); return path

def echarts_topology(sc, ac=None, title=None):
    buses, br, dev, links = topology_elements(sc); P = {b["i"]: b["pos"] for b in buses}
    sx = 110; nodes, edges = [], []
    kvs = sorted({b["kv"] for b in buses}, reverse=True); cats = [f"{k:g}kV" for k in kvs] + [v[2] for v in DEV_STYLE.values()]
    sym = {"ext": "rect", "pv": "circle", "wind": "triangle", "ess": "diamond", "dc": "roundRect"}
    for b in buses:
        x, y = b["pos"]; vm = f"<br/>V={ac['bus_vm_pu'][b['name']]:.4f} pu" if ac and b["name"] in ac.get("bus_vm_pu", {}) else ""
        nodes.append({"id": f"b{b['i']}", "name": f"{b['name']}{PROV_MARK[b['prov']]}", "x": x*sx, "y": -y*sx, "symbol": "rect", "symbolSize": [70, 8],
                      "category": cats.index(f"{b['kv']:g}kV"), "itemStyle": {"color": kv_color(b["kv"])},
                      "label": {"show": True, "position": "bottom", "fontSize": 10},
                      "tip": f"母线[{b['i']}] {b['name']}<br/>{b['kv']:g} kV<br/>{PROV_TXT[b['prov']]}{vm}"})
    for d in dev:
        x, y = P[d["bus"]]; n = f"{d['kind']}:{d['name']}"
        nodes.append({"id": n, "name": d["label"] + PROV_MARK[d["prov"]], "x": (x+d["dx"])*sx, "y": -(y+d["dy"])*sx, "symbol": sym[d["kind"]], "symbolSize": 18,
                      "category": cats.index(DEV_STYLE[d["kind"]][2]), "itemStyle": {"color": DEV_STYLE[d["kind"]][1], "borderColor": "#c0392b" if d["prov"] == "A" else "#333", "borderWidth": 2},
                      "label": {"show": True, "position": "bottom" if d["dy"] < 0 else "top", "fontSize": 9}, "tip": f"{d['label']}<br/>{PROV_TXT[d['prov']]}"})
        edges.append({"source": n, "target": f"b{d['bus']}", "label": {"show": False}, "lineStyle": {"color": "#888", "width": 1}})
    for e in br:
        lbl, tip, arrow = e["name"], f"{e['name']}<br/>{e['label']}<br/>{PROV_TXT[e['prov']]}", None
        src, dst = f"b{e['a']}", f"b{e['b']}"
        if ac is not None:
            pm = (ac.get("line_p_from_mw") if e["kind"] == "line" else ac.get("trafo_p_hv_mw", {})).get(e["name"])
            ld = (ac.get("line_loading_pct") if e["kind"] == "line" else ac.get("trafo_loading_pct", {})).get(e["name"])
            if pm is not None:
                if pm < 0: src, dst = dst, src
                lbl = f"{abs(pm):.0f}MW {ld:.0f}%"; tip += f"<br/>潮流 {abs(pm):.1f} MW, 负载率 {ld:.1f}%"; arrow = True
        edges.append({"source": src, "target": dst, "value": lbl, "symbol": ["none", "arrow"] if arrow else ["none", "none"], "symbolSize": 12,
                      "label": {"show": True, "formatter": lbl, "fontSize": 9},
                      "lineStyle": {"color": kv_color(e["kv"]), "width": 1.5 + 1.5*e["parallel"], "type": "dashed" if e["prov"] == "A" else "solid"}, "tip": tip})
    for l in links:
        edges.append({"source": f"dc:{l['a']}", "target": f"dc:{l['b']}", "label": {"show": True, "formatter": f"{l['latency_ms']:g}ms/{l['bw_mw']:g}MW", "fontSize": 8, "color": "#8e44ad"},
                      "lineStyle": {"color": "#8e44ad", "type": "dashed", "width": 1, "curveness": 0.3}, "tip": f"算力迁移链路 {l['a']}↔{l['b']}<br/>时延 {l['latency_ms']} ms 带宽 {l['bw_mw']} MW（假设）"})
    return {"_height": 620, "title": {"text": title or f"{sc.name} 系统拓扑", "subtext": "† 假设/等值  ‡ 拓扑来源报道、参数假设；虚线=假设支路；紫虚线=算力迁移链路", "left": "center"},
            "tooltip": {"trigger": "item"}, "legend": {"data": cats, "bottom": 0, "type": "scroll"},
            "series": [{"type": "graph", "layout": "none", "roam": True, "edgeLabel": {"show": True},
                        "top": 90, "bottom": 50, "left": 110, "right": 110, "categories": [{"name": c, "itemStyle": {"color": kv_color(kvs[i]) if i < len(kvs) else list(DEV_STYLE.values())[i-len(kvs)][1]}} for i, c in enumerate(cats)], "data": nodes, "links": edges, "lineStyle": {"opacity": 0.9}}]}

# ---------------- 能量平衡 ----------------
def energy_balance(sc, r):
    """一日（24h）能量流（MWh），按区域汇集节点组织：新能源/外网购电/储能放电 → 区域汇集 → DC/储能充电/外送/弃电。"""
    dt=r.get("solver",{}).get("resolution_h",1)
    df = r["df"]; reg = lambda b: str(sc.bus_region.get(b, sc.bus_region.get(str(b), "main"))) if sc.bus_region else "main"
    pv_av = np.zeros(len(df)); rows = []
    for p in sc.pv:
        a = p.cap_mw*np.array(p.profile if p.profile else np.repeat(eng.pv_shape(),int(round(1/dt)))); pv_av += a; rows.append((p, a))
    share = df.pv_used.values/np.maximum(pv_av, 1e-9)
    F, hub = {}, lambda rg: f"{'西北' if rg == 'northwest' else '华东(上海)' if rg == 'shanghai' else rg}汇集"
    def add(a, b, v):
        if v > 1e-6: F[(a, b)] = F.get((a, b), 0) + float(v)
    for p, a in rows:
        nm = f"{'风电' if _is_wind(p) else '光伏'}{p.cap_mw:g}MW"
        add(nm, hub(reg(p.bus)), (a*share).sum()); add(nm, "弃电", (a*(1-share)).sum())
    exts = sc.network.ext_grids if sc.network else []
    for g, gi in enumerate(r["gens"]):
        col = f"gen{g}_MW"
        if col not in df: continue
        if g < len(exts):
            e = exts[g]; add(f"{e.name}购电", hub(reg(e.bus)), df[col].sum())
            if f"gen{g}_export_MW" in df: add(hub(reg(e.bus)), f"外送{e.name}", df[f"gen{g}_export_MW"].sum())
        else: add(gi.get("name") if gi.get("kind") else "常规机组", hub(reg(gi.get("bus", 0))), df[col].sum())
    for s in sc.storage:
        if s.name in r["storage"]:
            add(hub(reg(s.bus)), f"{s.name}充电", df[f"{s.name}_ch"].sum()); add(f"{s.name}放电", hub(reg(s.bus)), df[f"{s.name}_dis"].sum())
    for d in sc.data_centers: add(hub(reg(d.bus)), f"DC {d.name}", df[f"{d.name}_grid_MW"].sum())
    if df.base_load_MW.sum() > 1e-6: add(hub("main"), "其他负荷", df.base_load_MW.sum())
    th = r.get("thermal")
    if th:   # 电 → IT → 热 → 冷却/余热利用（热/冷流节点以 ♨/❄ 前缀，前端用不同颜色）
        for d in sc.data_centers:
            if f"{d.name}_Tin_C" not in df: continue
            t = d.thermal; S = lambda c: float(df[f"{d.name}_{c}"].sum())
            it, cool, oth, hpe = S("IT_MW"), S("cool_MW"), S("other_MW"), S("hp_MW")
            add(f"DC {d.name}", "IT 设备(电)", it); add(f"DC {d.name}", "冷却系统(电)", cool); add(f"DC {d.name}", "配电/UPS 损耗(电)", oth)
            add(f"DC {d.name}", "余热热泵(电)", hpe)
            add("IT 设备(电)", "♨ 机房热量", it); add("配电/UPS 损耗(电)", "♨ 机房热量", oth*0.5); add("配电/UPS 损耗(电)", "♨ 配电间散热", oth*0.5)
            evap = S("hp_heat_MWth")*(1 - 1/t.hp_cop); ch_room = S("chiller_MWth") - S("tes_ch_MWth")
            add("♨ 机房热量", "❄ 冷机排热→冷却塔", ch_room); add("♨ 机房热量", "❄ 自然冷却排热", S("free_MWth"))
            add("♨ 机房热量", "❄ 蓄冷罐放冷", S("tes_dis_MWth")); add("♨ 机房热量", "♨ 余热回收(热泵蒸发侧)", evap)
            add("冷却系统(电)", "❄ 冷机排热→冷却塔", cool)
            add("❄ 冷机排热→冷却塔", "❄ 蓄冷罐充冷", S("tes_ch_MWth"))
            add("♨ 余热回收(热泵蒸发侧)", "♨ 热泵供热", evap); add("余热热泵(电)", "♨ 热泵供热", hpe)
        if th.get("heat"):
            hn = sc.heat_network; hp = sum(float(df[f"{d.name}_hp_heat_MWth"].sum()) for d in sc.data_centers if f"{d.name}_hp_heat_MWth" in df)
            add("♨ 热泵供热", "♨ 区域供热(售热)", float(df.heat_delivered_MWth.sum())); add("♨ 热泵供热", "♨ 管网热损", hn.pipe_loss*hp)
            rest = (1 - hn.pipe_loss)*hp - float(df.heat_delivered_MWth.sum())
            if rest > 1e-6: add("♨ 热泵供热", "♨ 热网蓄热(净)", rest)
    mig = float(df[[c for c in df if c.endswith("_mig_out")]].sum().sum())
    return {key:dt*value for key,value in F.items()}, dict(migrated_mwh=dt*mig, curtail_mwh=float(r["curtail_mwh"]))

def scale_flows(F, k): return {a: v*k for a, v in F.items()}
def sum_flows(Fs):
    out = {}
    for F in Fs:
        for a, v in F.items(): out[a] = out.get(a, 0) + v
    return out

def echarts_sankey(F, title, unit="MWh", sub=""):
    names = sorted({n for ab in F for n in ab})
    col = lambda n: "#f1c40f" if "光伏" in n else "#1abc9c" if "风电" in n else "#34495e" if "购电" in n else "#9b59b6" if "储能" in n or "ESS" in n \
        else "#e67e22" if n.startswith("DC") else "#e03131" if n.startswith("♨") else "#1c7ed6" if n.startswith("❄") else "#2980b9" if "外送" in n else "#e74c3c" if "弃电" in n else "#95a5a6"
    return {"_height": 460, "title": {"text": title, "subtext": sub, "left": "center"}, "tooltip": {"trigger": "item", "valueFormatter": f"__FMT__{unit}"},
            "series": [{"type": "sankey", "top": 70, "bottom": 20, "left": 20, "right": 140, "nodeGap": 14, "emphasis": {"focus": "adjacency"},
                        "data": [{"name": n, "itemStyle": {"color": col(n)}} for n in names],
                        "links": [{"source": a, "target": b, "value": round(v, 2)} for (a, b), v in F.items()],
                        "lineStyle": {"color": "gradient", "curveness": 0.5, "opacity": 0.45},
                        "label": {"fontSize": 11}}]}

def _fix(opt):  # valueFormatter 不能是函数（JSON）→ 去掉占位
    opt["tooltip"].pop("valueFormatter", None); return opt

def echarts_hourly(sc, r, title, rb=None):
    df = r["df"]; h = list(range(24)); ser = []
    pv_av = np.zeros(24); parts = []
    for p in sc.pv:
        a = p.cap_mw*np.array(p.profile if p.profile else eng.pv_shape()); pv_av += a; parts.append((p, a))
    share = df.pv_used.values/np.maximum(pv_av, 1e-9)
    stack = lambda n, v, c, st="s": {"name": n, "type": "bar", "stack": st, "data": [round(float(x), 1) for x in v], "itemStyle": {"color": c}}
    for p, a in parts: ser.append(stack(f"{'风电' if _is_wind(p) else '光伏'}{p.cap_mw:g}MW", a*share, "#1abc9c" if _is_wind(p) else "#f1c40f"))
    exts = sc.network.ext_grids if sc.network else []
    for g, e in enumerate(exts):
        if f"gen{g}_MW" in df: ser.append(stack(f"{e.name}购电", df[f"gen{g}_MW"], "#34495e" if g == 0 else "#7f8c8d"))
        if f"gen{g}_export_MW" in df: ser.append(stack(f"外送{e.name}", -df[f"gen{g}_export_MW"], "#2980b9"))
    for s in r["storage"]:
        ser.append(stack(f"{s}放电", df[f"{s}_dis"], "#9b59b6")); ser.append(stack(f"{s}充电", -df[f"{s}_ch"], "#d2b4de"))
    ser.append(stack("弃电", -(pv_av - df.pv_used.values), "#e74c3c"))
    dcs = [c for c in df if c.endswith("_grid_MW")]
    ser.append({"name": "DC总负荷(优化)", "type": "line", "data": [round(float(x), 1) for x in df[dcs].sum(axis=1)], "lineStyle": {"width": 3, "color": "#e67e22"}, "itemStyle": {"color": "#e67e22"}})
    if rb is not None:
        ser.append({"name": "DC总负荷(基线)", "type": "line", "data": [round(float(x), 1) for x in rb["df"][dcs].sum(axis=1)], "lineStyle": {"type": "dashed", "color": "#7f8c8d"}, "itemStyle": {"color": "#7f8c8d"}})
    return {"_height": 460, "title": {"text": title, "left": "center"}, "tooltip": {"trigger": "axis"}, "legend": {"top": 28, "type": "scroll"},
            "grid": {"left": 60, "right": 30, "top": 80, "bottom": 40}, "xAxis": {"type": "category", "data": h, "name": "时"},
            "yAxis": {"type": "value", "name": "MW（负=外送/充电/弃电）", "nameLocation": "middle", "nameGap": 45}, "series": ser}

@tool("plot_topology", "绘制当前（自定义网络）场景的系统拓扑单线图：母线(按电压等级着色)/线路/变压器(容量、阻抗、并联回数)/新能源/储能/数据中心/外部电网/算力迁移链路，"
      "标注假设与来源元件；with_flows=true 时叠加交流潮流（箭头+MW+负载率，需先 run_dispatch）。输出交互 ECharts 关系图 + PNG。适用于“拓扑/单线图/网络结构/潮流图”。", {
    "type": "object", "properties": {"with_flows": {"type": "boolean", "default": False},
                                     "case": {"type": "string", "default": "optimized"}, "hour": {"type": "integer", "description": "潮流时刻 0-23，缺省=峰值时刻"}}})
def plot_topology(s: Session, with_flows=False, case="optimized", hour=None):
    sc = _sc(s); ac = None
    if with_flows:
        ac = eng.ac_check(sc, _res(s, case), hour)
    tt = f"{sc.name} 系统拓扑" + (f"（{case} {ac['hour']}:00 交流潮流）" if ac else "")
    tag = "_flow" if ac else ""
    draw_topology(sc, _art(s, f"topology{tag}.png"), ac, title=tt + "  † 假设/等值  ‡ 拓扑来源、参数假设")
    with open(_art(s, f"topology{tag}_echarts.json"), "w") as f: json.dump(echarts_topology(sc, ac, tt), f, ensure_ascii=False)
    buses, br, dev, links = topology_elements(sc)
    out = {"ok": True, "n_buses": len(buses), "voltage_levels_kv": sorted({b["kv"] for b in buses}, reverse=True),
           "branches": [(e["name"], e["kind"], sc.network.buses[e["a"]].name, sc.network.buses[e["b"]].name) for e in br],
           "devices": [(d["kind"], d["label"], sc.network.buses[d["bus"]].name, PROV_TXT[d["prov"]]) for d in dev],
           "assumed": [x["name"] for x in buses + br + dev if x["prov"] == "A"],
           "echarts": [f"topology{tag}_echarts.json"], "artifacts": [f"topology{tag}.png", f"topology{tag}_echarts.json"]}
    if ac: out["ac"] = {k: ac[k] for k in ("hour", "converged", "vmin_pu", "vmax_pu", "max_line_loading_pct", "max_trafo_loading_pct", "losses_mw", "line_p_from_mw", "line_loading_pct")}
    return out

@tool("plot_energy_flow", "能流可视化：基线 vs 优化 的日能量桑基图（新能源/外网购电/储能放电 → 区域汇集 → 数据中心/储能充电/外送/弃电，MWh）"
      "+ 逐时供需堆叠图（MW）。需先 run_dispatch（缺失时自动运行）。输出交互 ECharts。适用于“能流/桑基/能量平衡/电量去向”。", {
    "type": "object", "properties": {"annualize_days": {"type": "number", "description": "乘以该天数换算（如 365 → GWh/年口径），默认 1（日）"}}})
def plot_energy_flow(s: Session, annualize_days=1):
    from .sim_tools import run_dispatch
    sc = _sc(s)
    for c in ("baseline", "optimized"):
        if c not in s.state.get("results", {}): run_dispatch(s, c)
    k = float(annualize_days or 1); unit = "MWh" if k == 1 else f"MWh×{k:g}天"
    files, summ = [], {}
    for c, cn in (("baseline", "基线"), ("optimized", "优化")):
        F, ex = energy_balance(sc, _res(s, c)); F = scale_flows(F, k)
        opt = _fix(echarts_sankey(F, f"{sc.name} 能量桑基图（{cn}，{unit}）", sub=f"迁移 {ex['migrated_mwh']*k:.0f} MWh；DC-OPF 无损（网损未计）"))
        fn = f"energy_sankey_{c}_echarts.json"
        with open(_art(s, fn), "w") as f: json.dump(opt, f, ensure_ascii=False)
        files.append(fn); summ[c] = {f"{a}→{b}": round(v, 1) for (a, b), v in F.items()}
    fn = "energy_hourly_echarts.json"
    with open(_art(s, fn), "w") as f: json.dump(echarts_hourly(sc, _res(s), f"{sc.name} 逐时供需（优化）", _res(s, "baseline")), f, ensure_ascii=False)
    files.append(fn)
    return {"ok": True, "unit": unit, "flows": summ, "echarts": files, "artifacts": files}
