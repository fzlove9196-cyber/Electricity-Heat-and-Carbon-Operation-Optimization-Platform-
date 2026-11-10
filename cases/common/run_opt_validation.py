"""寻优/全年/边际碳 验证：4+ 个真实案例。输出 cases/validation/out/opt_validation.json。"""
import sys, os, json, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
import numpy as np
from app.opt import annual as A, engine as E
OUT = os.path.join(os.path.dirname(__file__), "..", "validation", "out", "opt_validation.json")
CASES = ["zhongwei_summer_coupled", "ulanqab_cicdata_summer", "shaoguan_summer", "odense_meta_winter"]
R = json.load(open(OUT)) if os.path.exists(OUT) else {}
def save(): json.dump(R, open(OUT, "w"), ensure_ascii=False, indent=1, default=float)
K5 = lambda K: {k: round(float(K[k]), 4) for k in ("cost_total", "carbon_net_t", "emis_marg_t", "emis_avg_t", "grid_mwh", "green_share", "pue", "heat_mwh", "peak_mw", "wind_used_mwh", "pv_used_mwh")}
part = sys.argv[1] if len(sys.argv) > 1 else "all"

if part in ("all", "acc"):
    R["accuracy"] = {}
    for p in CASES:
        c = A.build_case(p); rows = []
        for k, how in [(None, "full"), (12, "medoid"), (24, "medoid"), (48, "medoid"), (48, "centroid"), (96, "medoid")]:
            M = A.build(c, k=k, how=how if how != "full" else "medoid"); r = A.solve(M, A.objective_vec(M, "cost"))
            rows.append(dict(k=k or 365, how=how, n_var=M["lp"].n, n_row=M["lp"].m["le"] + M["lp"].m["eq"], solve_s=round(r["time"], 2), kpi=K5(A.kpis(M, r["x"]))))
        R["accuracy"][p] = dict(rows=rows, carbon_stats=c["carbon_stats"], source=c["source"]); print("acc", p, [(x["k"], x["how"], x["solve_s"], x["kpi"]["cost_total"]) for x in rows]); save()

if part in ("all", "cprice"):
    R["carbon_price"] = {}
    for p in ["odense_meta_winter", "ulanqab_cicdata_summer", "zhongwei_summer_coupled"]:
        rows = []
        for basis in ("marginal", "average"):
            for cp in (0, 100, 300, 1000):
                c = A.build_case(p, carbon_basis=basis, carbon_price=cp); M = A.build(c)
                r = A.solve(M, A.objective_vec(M, "cost")); K = A.kpis(M, r["x"]); g = r["x"][M["g"]]
                rows.append(dict(basis=basis, cp=cp, grid=round(K["grid_mwh"]), emis_marg=round(K["emis_marg_t"]), intensity_marg=round(K["emis_marg_t"]/K["grid_mwh"], 4),
                                 corr_grid_mef=round(float(np.corrcoef(g, c["ef_marg"])[0, 1]), 3), heat=round(K["heat_mwh"]), energy_cost=round(K["energy_cost"]), net=round(K["carbon_net_t"])))
        R["carbon_price"][p] = rows; print("cp", p, rows); save()

if part in ("all", "pareto"):
    R.setdefault("pareto", {})
    jobs = [(p, dict(resolution=48)) for p in CASES] + [("shaoguan_summer", dict(resolution=48, pareto=dict(x="cost", y="thermal_margin", n=6), decisions_chiller=True, tag="shaoguan_margin"))]
    for p, o in jobs:
        sp = E.default_spec(p); sp["resolution"] = o["resolution"]
        if "pareto" in o: sp["pareto"] = o["pareto"]; sp["objectives"] = [dict(key="cost"), dict(key="thermal_margin")]
        if o.get("decisions_chiller"): sp["decisions"]["chiller"] = True
        t0 = time.time(); r = E.run(sp, progress=lambda a, b: print("  ", b, flush=True))
        ab = E.abatement(r, 0.10) if sp["pareto"]["y"] == "carbon" and len(r["front"]) > 1 else None
        R["pareto"][o.get("tag", p)] = json.loads(json.dumps(dict(result=r, abate=ab), default=float)); print("pareto", p, round(time.time() - t0, 1)); save()

if part in ("full_front",):
    sp = E.default_spec("zhongwei_summer_coupled"); sp["resolution"] = "full"; sp["pareto"]["n"] = 5
    t0 = time.time(); r = E.run(sp, progress=lambda a, b: print("  ", b, flush=True))
    R["full_front_zhongwei"] = json.loads(json.dumps(dict(result=r), default=float)); print("full", round(time.time() - t0, 1)); save()

if part in ("all", "ulq"):
    out = []
    for ws in (1.0, 2.4):
        c = A.build_case("ulanqab_cicdata_summer", wind_scale=ws); M = A.build(c); r = A.solve(M, A.objective_vec(M, "cost")); K = A.kpis(M, r["x"])
        out.append(dict(wind_scale=ws, wind_avail_mwh=round(float(c["wind_cf"].sum()*c["wind0"])), pv_avail_mwh=round(float(c["pv_cf"].sum()*c["pv0"])),
                        wind_used=round(K["wind_used_mwh"]), pv_used=round(K["pv_used_mwh"]), green=round(K["green_share"], 4), load=round(K["load_mwh"]), self_green_yi=round((K["wind_used_mwh"] + K["pv_used_mwh"])/1e5, 3)))
    R["ulanqab_annual"] = out; print(out); save()
