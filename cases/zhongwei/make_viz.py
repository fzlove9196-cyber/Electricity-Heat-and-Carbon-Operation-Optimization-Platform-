"""中卫案例可视化：拓扑单线图、年化能量桑基（基线 B0' vs 优化 O3）、典型日逐时供需、峰时潮流图。
数据全部来自 build_zhongwei 场景 JSON + sdco_engine 重新求解。输出 cases/zhongwei/viz/*.png|html"""
import json, os, sys, warnings; warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
import numpy as np
import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
plt.rcParams["font.sans-serif"] = ["Noto Sans CJK SC", "DejaVu Sans"]; plt.rcParams["axes.unicode_minus"] = False
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from app.scenario import load_preset
from app.tools import sdco_engine as eng, viz_tools as vz
D = os.path.dirname(os.path.abspath(__file__)); OUT = os.path.join(D, "viz"); os.makedirs(OUT, exist_ok=True)
DAYS = ["summer_highwind", "summer_lowwind", "winter_highwind", "winter_lowwind"]
DN = {"summer_highwind": "夏季大风日", "summer_lowwind": "夏季小风日", "winter_highwind": "冬季大风日", "winter_lowwind": "冬季小风日"}

def sc_of(d): return load_preset(f"zhongwei_{d}")

res = {}
for d in DAYS:
    sc = sc_of(d); res[d] = dict(sc=sc, B=eng.solve(sc, optimize=False), O=eng.solve(sc, optimize=True))
sc0 = res["summer_highwind"]["sc"]

# 1) 拓扑
vz.draw_topology(sc0, os.path.join(OUT, "01_topology.png"), title="大唐中卫云基地 绿电直供 + 上海算力节点 系统拓扑（单线图，等值网络）  † 假设/等值  ‡ 拓扑来源报道、参数假设  线宽∝并联回数")
opt = vz.echarts_topology(sc0)
open(os.path.join(OUT, "01_topology_echarts.json"), "w").write(json.dumps(opt, ensure_ascii=False))

def plotly_topo(sc, ac, fn, title):
    buses, br, dev, links = vz.topology_elements(sc); P = {b["i"]: b["pos"] for b in buses}; fig = go.Figure()
    for e in br:
        (x1, y1), (x2, y2) = P[e["a"]], P[e["b"]]; txt = f"{e['name']}<br>{e['label']}<br>{vz.PROV_TXT[e['prov']]}"
        if ac:
            pm = (ac["line_p_from_mw"] if e["kind"] == "line" else ac["trafo_p_hv_mw"]).get(e["name"]); ld = (ac["line_loading_pct"] if e["kind"] == "line" else ac["trafo_loading_pct"]).get(e["name"])
            txt += f"<br>潮流 {pm:+.1f} MW（+为{sc.network.buses[e['a']].name}→{sc.network.buses[e['b']].name}）负载率 {ld:.1f}%"
            if pm < 0: x1, y1, x2, y2 = x2, y2, x1, y1
            fig.add_annotation(x=x1+(x2-x1)*.65, y=y1+(y2-y1)*.65, ax=x1+(x2-x1)*.35, ay=y1+(y2-y1)*.35, xref="x", yref="y", axref="x", ayref="y",
                               showarrow=True, arrowhead=3, arrowsize=1.5, arrowwidth=2, text=f"{abs(pm):.0f}MW {ld:.0f}%")
        fig.add_trace(go.Scatter(x=[x1, (x1+x2)/2, x2], y=[y1, (y1+y2)/2, y2], mode="lines", hoverinfo="text", hovertext=txt, showlegend=False,
                                 line=dict(color=vz.kv_color(e["kv"]), width=2+1.5*e["parallel"], dash="dash" if e["prov"] == "A" else "solid")))
    for b in buses:
        x, y = b["pos"]
        fig.add_trace(go.Scatter(x=[x-.45, x+.45], y=[y, y], mode="lines", line=dict(color=vz.kv_color(b["kv"]), width=9), showlegend=False,
                                 hoverinfo="text", hovertext=f"[{b['i']}] {b['name']} {b['kv']:g}kV {vz.PROV_TXT[b['prov']]}" + (f" V={ac['bus_vm_pu'][b['name']]:.4f}pu" if ac else "")))
        fig.add_annotation(x=x, y=y-.15, text=f"{b['name']}{vz.PROV_MARK[b['prov']]}", showarrow=False, font=dict(size=10, color=vz.kv_color(b["kv"])))
    sym = {"ext": "square", "pv": "circle", "wind": "triangle-up", "ess": "diamond", "dc": "hexagon"}
    for d in dev:
        x, y = P[d["bus"]]; X, Y = x+d["dx"], y+d["dy"]
        fig.add_trace(go.Scatter(x=[x, X], y=[y, Y], mode="lines", line=dict(color="#888", width=1), showlegend=False, hoverinfo="skip"))
        fig.add_trace(go.Scatter(x=[X], y=[Y], mode="markers+text", text=[d["label"]+vz.PROV_MARK[d["prov"]]], textposition="bottom center" if d["dy"] < 0 else "top center",
                                 marker=dict(symbol=sym[d["kind"]], size=18, color=vz.DEV_STYLE[d["kind"]][1], line=dict(color="#c0392b" if d["prov"] == "A" else "#333", width=2)),
                                 name=vz.DEV_STYLE[d["kind"]][2], hovertext=vz.PROV_TXT[d["prov"]], showlegend=False))
    dp = {d["name"]: (P[d["bus"]][0]+d["dx"], P[d["bus"]][1]+d["dy"]) for d in dev if d["kind"] == "dc"}
    for l in links:
        (x1, y1), (x2, y2) = dp[l["a"]], dp[l["b"]]; my = min(y1, y2) - .3 - .05*abs(x2-x1)
        fig.add_trace(go.Scatter(x=[x1, (x1+x2)/2, x2], y=[y1, my, y2], mode="lines", line=dict(color="#8e44ad", dash="dot", shape="spline"), showlegend=False,
                                 hoverinfo="text", hovertext=f"迁移链路 {l['a']}↔{l['b']} {l['latency_ms']}ms {l['bw_mw']}MW（假设）"))
    fig.update_layout(title=title, template="plotly_white", height=800, xaxis=dict(visible=False), yaxis=dict(visible=False, scaleanchor="x"))
    fig.write_html(os.path.join(OUT, fn), include_plotlyjs="cdn")
plotly_topo(sc0, None, "01_topology.html", "中卫云基地 系统拓扑（† 假设/等值 ‡ 拓扑来源、参数假设）")

# 2a) 年化 Sankey（4 典型日等权 × 365/4，GWh/年）
ann = {}
for c in ("B", "O"):
    Fs, mig = [], 0
    for d in DAYS:
        F, ex = vz.energy_balance(res[d]["sc"], res[d][c]); Fs.append(F); mig += ex["migrated_mwh"]
    ann[c] = (vz.scale_flows(vz.sum_flows(Fs), 365/4/1000), mig*365/4/1000)
fig = make_subplots(rows=1, cols=2, specs=[[{"type": "sankey"}]*2], subplot_titles=[f"基线 B0'（无灵活/无储能）", f"优化 O3（时移+储能+跨区迁移，迁移 {ann['O'][1]:.1f} GWh/年）"])
for k, (c, _) in enumerate([("B", 0), ("O", 1)]):
    F = ann[c][0]; names = sorted({n for ab in F for n in ab}); ix = {n: i for i, n in enumerate(names)}
    col = [vz.echarts_sankey({}, "")["series"][0] and ("#f1c40f" if "光伏" in n else "#1abc9c" if "风电" in n else "#34495e" if "购电" in n else "#9b59b6" if "ESS" in n
            else "#e67e22" if n.startswith("DC") else "#2980b9" if "外送" in n else "#e74c3c" if "弃电" in n else "#95a5a6") for n in names]
    fig.add_trace(go.Sankey(node=dict(label=[f"{n} {sum(v for (a, b), v in F.items() if n in (a, b))/ (2 if '汇集' in n else 1):.0f}" for n in names], color=col, pad=14),
                            link=dict(source=[ix[a] for a, b in F], target=[ix[b] for a, b in F], value=list(F.values()),
                                      hovertemplate="%{source.label} → %{target.label}: %{value:.1f} GWh/年<extra></extra>"),
                            domain=dict(x=[0, .48] if k == 0 else [.52, 1])), 1, k+1)
fig.update_layout(title="中卫云基地 年化能量流 GWh/年（4 典型日等权×365；DC-OPF 无损，网损未计；弃电=0）", height=650, font=dict(size=11))
fig.write_html(os.path.join(OUT, "02a_energy_sankey.html"), include_plotlyjs="cdn")
# matplotlib 版：并排水平条形“流向”图（Sankey PNG 用 plotly 静态导出依赖 kaleido，这里用 matplotlib 实现两级 Sankey）
def mpl_sankey(ax, F, title):
    src = [n for n in {a for a, b in F} if "汇集" not in n]; hubs = sorted({n for ab in F for n in ab if "汇集" in n}); snk = [n for n in {b for a, b in F} if "汇集" not in n]
    order = lambda L: sorted(L, key=lambda n: (("风电" not in n), ("光伏" not in n), ("ESS" in n), n))
    hubs = sorted(hubs, key=lambda n: "华东" in n)
    hub_of = lambda n: next((hubs.index(b if a == n else a) for (a, b) in F if n in (a, b) and ("汇集" in a or "汇集" in b)), 9)
    src = sorted(src, key=lambda n: (hub_of(n), "风电" not in n, "光伏" not in n, "ESS" in n, n))
    snk = sorted(snk, key=lambda n: (hub_of(n), not n.startswith("DC"), n))
    tot = sum(v for (a, b), v in F.items() if b in hubs) or 1; gap = 0.02*tot; H = tot*1.0
    def stackpos(L, x, key):
        y, pos = 0, {}
        for n in L:
            v = sum(val for ab, val in F.items() if ab[key] == n); pos[n] = [y, y+v]; y += v + gap
        return pos
    ps, pk = stackpos(src, 0, 0), stackpos(snk, 2, 1)
    yh, ph = 0, {}
    for hb in hubs:
        v = sum(val for (a, b), val in F.items() if b == hb); ph[hb] = [yh, yh+v]; yh += v + gap*3
    colr = lambda n: "#f1c40f" if "光伏" in n else "#1abc9c" if "风电" in n else "#34495e" if "西北" in n and "购电" in n else "#7f8c8d" if "购电" in n else "#9b59b6" if "ESS" in n \
        else "#e67e22" if n.startswith("DC") else "#2980b9" if "外送" in n else "#e74c3c" if "弃电" in n else "#95a5a6"
    def band(x0, y0a, y0b, x1, y1a, y1b, c):
        t = np.linspace(0, 1, 50); s = 3*t**2 - 2*t**3; xs = x0 + (x1-x0)*t
        ax.fill_between(xs, y0a + (y1a-y0a)*s, y0b + (y1b-y0b)*s, color=c, alpha=.45, lw=0)
    off_h_in = {h: ph[h][0] for h in hubs}; off_h_out = {h: ph[h][0] for h in hubs}
    for n in src:
        y = ps[n][0]
        for (a, b), v in F.items():
            if a == n and b in hubs: band(0.05, y, y+v, 0.95, off_h_in[b], off_h_in[b]+v, colr(n)); y += v; off_h_in[b] += v
            elif a == n:  # 直接到汇（弃电）
                band(0.05, y, y+v, 1.95, pk[b][0], pk[b][0]+v, colr(b)); y += v
    off_k = {n: pk[n][0] for n in snk}
    for hb in hubs:
        for (a, b), v in F.items():
            if a == hb: band(1.05, off_h_out[hb], off_h_out[hb]+v, 1.95, off_k[b], off_k[b]+v, colr(b)); off_h_out[hb] += v; off_k[b] += v
    for n, (y0, y1) in ps.items(): ax.add_patch(plt.Rectangle((0, y0), .05, y1-y0, color=colr(n))); ax.text(-.02, (y0+y1)/2, f"{n}\n{y1-y0:,.0f}", ha="right", va="center", fontsize=9)
    for n, (y0, y1) in ph.items(): ax.add_patch(plt.Rectangle((.95, y0), .1, y1-y0, color="#95a5a6")); ax.text(1.0, y1+gap*.5, f"{n} {y1-y0:,.0f}", ha="center", va="bottom", fontsize=9, fontweight="bold")
    for n, (y0, y1) in pk.items(): ax.add_patch(plt.Rectangle((1.95, y0), .05, max(y1-y0, tot*.002), color=colr(n))); ax.text(2.03, (y0+y1)/2, f"{n} {y1-y0:,.0f}", ha="left", va="center", fontsize=9)
    ax.set_xlim(-.55, 2.75); ax.set_ylim(max(max(v[1] for v in pk.values()), yh, max(v[1] for v in ps.values()))*1.03, -tot*.03); ax.axis("off"); ax.set_title(title, fontsize=12)
fig2, axs = plt.subplots(1, 2, figsize=(20, 9))
mpl_sankey(axs[0], ann["B"][0], "基线 B0'（无灵活/无储能）GWh/年"); mpl_sankey(axs[1], ann["O"][0], f"优化 O3（时移+储能+跨区迁移）GWh/年\n跨区/站间算力迁移 {ann['O'][1]:.1f} GWh/年")
fig2.suptitle("中卫云基地 年化能量流（4 典型日等权×365；DC-OPF 无损，网损未计；4 典型日均无弃电）", fontsize=14)
fig2.tight_layout(); fig2.savefig(os.path.join(OUT, "02a_energy_sankey.png"), dpi=110); plt.close(fig2)
json.dump({c: {f"{a}→{b}": round(v, 2) for (a, b), v in ann[c][0].items()} for c in ann}, open(os.path.join(OUT, "02a_energy_sankey_gwh.json"), "w"), ensure_ascii=False, indent=1)

# 2b) 典型日逐时堆叠（夏季大风 / 冬季小风；基线 vs 优化）
def hourly_parts(sc, r):
    df = r["df"]; parts = {}
    av = {}; tot = np.zeros(24)
    for p in sc.pv: a = p.cap_mw*np.array(p.profile); av[("风电" if vz._is_wind(p) else "光伏")+f"{p.cap_mw:g}MW"] = a; tot += a
    sh = df.pv_used.values/np.maximum(tot, 1e-9)
    for n, a in av.items(): parts[n] = a*sh
    parts["西北电网购电"] = df.gen0_MW.values; parts["ESS放电"] = df.ESS_ZW_dis.values if "ESS_ZW_dis" in df else np.zeros(24)
    neg = {"外送西北": -df.gen0_export_MW.values, "ESS充电": -(df.ESS_ZW_ch.values if "ESS_ZW_ch" in df else np.zeros(24)), "弃电": -(tot - df.pv_used.values)}
    zw = df[[f"{d.name}_grid_MW" for d in sc.data_centers if not d.name.startswith("SH")]].sum(axis=1).values
    return parts, neg, zw, df.SH_EAST_grid_MW.values, df.gen1_MW.values
C = {"风电1500MW": "#1abc9c", "光伏500MW": "#f1c40f", "西北电网购电": "#34495e", "ESS放电": "#9b59b6", "外送西北": "#2980b9", "ESS充电": "#d2b4de", "弃电": "#e74c3c"}
fig, axs = plt.subplots(2, 2, figsize=(18, 11), sharex=True); pf = make_subplots(rows=2, cols=2, subplot_titles=[f"{DN[d]} {c}" for d in ("summer_highwind", "winter_lowwind") for c in ("基线 B0'", "优化 O3")], shared_xaxes=True)
for i, d in enumerate(["summer_highwind", "winter_lowwind"]):
    for j, (c, cn) in enumerate([("B", "基线 B0'"), ("O", "优化 O3")]):
        sc, r = res[d]["sc"], res[d][c]; parts, neg, zw, shd, shi = hourly_parts(sc, r); ax = axs[i, j]; h = np.arange(24)
        b = np.zeros(24)
        for n, v in parts.items(): ax.bar(h, v, bottom=b, color=C[n], label=n, width=.85); pf.add_trace(go.Bar(x=h, y=v, name=n, marker_color=C[n], legendgroup=n, showlegend=(i+j == 0)), i+1, j+1); b += v
        b = np.zeros(24)
        for n, v in neg.items(): ax.bar(h, v, bottom=b, color=C[n], label=n, width=.85); pf.add_trace(go.Bar(x=h, y=v, name=n, marker_color=C[n], legendgroup=n, showlegend=(i+j == 0)), i+1, j+1); b += v
        zb = hourly_parts(sc, res[d]["B"])[2]
        ax.plot(h, zw, "-o", color="#e67e22", lw=2.5, ms=4, label="中卫DC总负荷"); pf.add_trace(go.Scatter(x=h, y=zw, name="中卫DC总负荷", line=dict(color="#e67e22", width=3), legendgroup="zw", showlegend=(i+j == 0)), i+1, j+1)
        if c == "O": ax.plot(h, zb, "--", color="#7f8c8d", lw=1.5, label="中卫DC负荷(基线)")
        ax.plot(h, shd, ":", color="#c0392b", lw=2, label="上海DC负荷(华东购电)"); pf.add_trace(go.Scatter(x=h, y=shd, name="上海DC负荷", line=dict(color="#c0392b", dash="dot"), legendgroup="sh", showlegend=(i+j == 0)), i+1, j+1)
        ax.axhline(0, color="k", lw=.8); ax.set_title(f"{DN[d]}  {cn}（中卫汇集节点功率平衡）", fontsize=12); ax.grid(alpha=.3); ax.set_ylabel("MW  (正=供给, 负=外送/充电/弃电)")
        if i == 1: ax.set_xlabel("小时（北京时间）")
        ax.set_xticks(range(0, 24, 2))
axs[0, 0].legend(loc="upper center", ncol=5, fontsize=8.5, bbox_to_anchor=(1.05, 1.22))
fig.suptitle("典型日逐时供需（风/光/西北购电/储能 vs 数据中心负荷；外送为负）", fontsize=14, y=.995); fig.tight_layout(); fig.savefig(os.path.join(OUT, "02b_typical_day_hourly.png"), dpi=110); plt.close(fig)
pf.update_layout(barmode="relative", height=850, title="典型日逐时供需（MW）", template="plotly_white"); pf.write_html(os.path.join(OUT, "02b_typical_day_hourly.html"), include_plotlyjs="cdn")

# 2c) 峰时交流潮流图（O3，各典型日总负荷峰值时刻 → 取最大负载率者 + 冬季小风日）
acs = {d: eng.ac_check(res[d]["sc"], res[d]["O"]) for d in DAYS}
json.dump({d: {k: v for k, v in a.items()} for d, a in acs.items()}, open(os.path.join(OUT, "02c_ac_peak.json"), "w"), ensure_ascii=False, indent=1, default=float)
for d in ("summer_highwind", "winter_lowwind"):
    a = acs[d]; t = f"中卫 {DN[d]} 优化O3 峰时 {a['hour']}:00 交流潮流（pandapower；网损 {a['losses_mw']:.1f} MW，V {a['vmin_pu']:.3f}–{a['vmax_pu']:.3f} pu）"
    vz.draw_topology(res[d]["sc"], os.path.join(OUT, f"02c_peak_flow_{d}.png"), a, title=t)
    plotly_topo(res[d]["sc"], a, f"02c_peak_flow_{d}.html", t)
print(json.dumps({d: dict(hour=a["hour"], loss=a["losses_mw"], lines=a["line_p_from_mw"], trafo=a["trafo_p_hv_mw"], ext=a["ext_grid_p_mw"]) for d, a in acs.items()}, ensure_ascii=False, indent=0))
print({c: {f"{a}→{b}": round(v, 1) for (a, b), v in ann[c][0].items()} for c in ann})
