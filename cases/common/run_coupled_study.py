"""算-电-热-碳耦合案例研究：基线(常数PUE) vs 耦合优化、有/无 DR、热浪压力测试、冬季余热供热。
输出 cases/zhongwei/results/coupled_study.json 与 .md"""
import json, os, sys, time
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(os.path.dirname(HERE)); sys.path.insert(0, ROOT)
from app.scenario import load_preset
from app.tools import sdco_engine as eng
from app.tools.sim_tools import _kpis
from app import transparency as tr

def row(tag, sc, r):
    k = _kpis(sc, r)
    out = dict(case=tag, objective=round(r["objective"]), cost=round(r["cost_cny"]), emis_t=round(r["emissions_t"], 1), dc_mwh=round(k["dc_energy_mwh"], 1),
               dc_peak_mw=round(k["dc_peak_mw"], 1))
    if r.get("thermal"):
        out.update(pue_avg=round(k["pue_avg"], 4), pue_min=k["pue_min"], pue_max=k["pue_max"], tin_min=k["tin_min_c"], tin_max=k["tin_max_c"],
                   margin_k=k["thermal_margin_k"], h_above_rec=k["hours_above_rec"], cooling_mwh=round(k["cooling_mwh"], 1), violations=k["thermal_violations"],
                   heat_mwh=k.get("heat_delivered_mwh", 0), heat_rev=k.get("heat_revenue_cny", 0), heat_offset_t=round(k.get("carbon_heat_offset_tco2", 0), 1),
                   binding={d: x["binding_hours"] for d, x in r["thermal"]["dcs"].items()},
                   bal=dict(thermal=max(x["thermal_balance_max_residual"] for x in r["thermal"]["dcs"].values()),
                            elec=max(x["elec_balance_max_residual"] for x in r["thermal"]["dcs"].values()),
                            heat=(r["thermal"].get("heat") or {}).get("balance_max_residual")))
    else: out.update(pue_avg=round(k["dc_energy_mwh"]/sum(r["df"][f"{d.name}_IT_MW"].sum() for d in sc.data_centers), 4))
    if r.get("dr"): out["dr"] = [dict(name=e["name"], req=e["requested_mwh"], got=e["delivered_mwh"], rev=e["revenue_cny"]) for e in r["dr"]]
    return out

R = {}; t0 = time.time()
s = load_preset("zhongwei_summer_coupled"); c = s.model_copy(deep=True); c.thermal_mode = "constant_pue"
R["summer"] = [row("常数PUE 基线(无协同)", c, eng.solve(c, False)), row("常数PUE 优化", c, eng.solve(c, True)),
               row("耦合 基线(定送风24°C)", s, eng.solve(s, False)), row("耦合 优化(预冷+蓄冷)", s, ro := eng.solve(s, True))]
sd = load_preset("zhongwei_summer_coupled_dr"); rd = eng.solve(sd, True); R["summer"].append(row("耦合 优化 + DR", sd, rd))
R["summer_attr"] = tr.attribution(sd, eng.solve(sd, False), rd)
h = load_preset("zhongwei_heatwave_stress"); hb = eng.solve(h, False); ho = eng.solve(h, True)
ht = h.model_copy(deep=True)
for d in ht.data_centers: d.thermal.t_allow_max_c = 27.0
hn = h.model_copy(deep=True); hn.dr_events = []
R["heatwave"] = [row("热浪 基线", h, hb), row("热浪 优化(含DR)", h, ho), row("热浪 优化 无DR", hn, eng.solve(hn, True)), row("热浪 优化 允许上限收紧至27°C", ht, eng.solve(ht, True))]
R["heatwave_tin"] = {d.name: [round(x, 2) for x in ho["df"][f"{d.name}_Tin_C"]] for d in h.data_centers}
w = load_preset("zhongwei_winter_coupled_heat"); wc = w.model_copy(deep=True); wc.thermal_mode = "constant_pue"
wo = eng.solve(w, True)
R["winter"] = [row("常数PUE 基线", wc, eng.solve(wc, False)), row("耦合 基线", w, eng.solve(w, False)),
               row("耦合 优化 无余热", w, eng.solve(w, True, levers=dict(heat=False))), row("耦合 优化 +余热+DR", w, wo)]
R["winter_attr"] = tr.attribution(w, eng.solve(w, False), wo)
g = load_preset("helinger_winter_coupled_heat"); gc = g.model_copy(deep=True); gc.thermal_mode = "constant_pue"
R["helinger"] = [row("常数PUE 基线", gc, eng.solve(gc, False)), row("耦合 基线", g, eng.solve(g, False)),
                 row("耦合 优化 无余热", g, eng.solve(g, True, levers=dict(heat=False))), row("耦合 优化 +余热", g, eng.solve(g, True))]
R["elapsed_s"] = round(time.time() - t0, 1)
os.makedirs(os.path.join(ROOT, "cases", "zhongwei", "results"), exist_ok=True)
p = os.path.join(ROOT, "cases", "zhongwei", "results", "coupled_study.json")
json.dump(R, open(p, "w"), ensure_ascii=False, indent=1, default=str); print("wrote", p, R["elapsed_s"], "s")
for k in ("summer", "heatwave", "winter", "helinger"):
    print("\n##", k)
    for x in R[k]: print({a: b for a, b in x.items() if a not in ("binding", "bal")})
for k in ("summer_attr", "winter_attr"):
    print(k, [(p["name"], p["saving"]) for p in R[k]["parts"]], R[k]["total_saving"])
