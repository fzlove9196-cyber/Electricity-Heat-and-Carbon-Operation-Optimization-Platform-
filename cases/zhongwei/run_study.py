"""中卫项目研究脚本：通过 app 工具层（与对话同一套 build_scenario/run_dispatch/run_ac_check/run_pareto_sweep）批量运行。
输出 cases/zhongwei/results/*.json|csv|png"""
import json, os, sys, warnings; warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
import numpy as np, pandas as pd
from app.tools.base import Session
from app.tools import sim_tools as st, phase1_tools as p1
from app.tools import sdco_engine as eng
from app.scenario import load_preset
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")
DAYS = ["summer_highwind", "summer_lowwind", "winter_highwind", "winter_lowwind"]

def zw_kpi(sc, r, label):
    df = r["df"]; zw = [d for d in sc.data_centers if not d.name.startswith("SH")]
    zwE = float(sum(df[f"{d.name}_grid_MW"].sum() for d in zw))
    imp = float(df["gen0_MW"].sum()); exp_ = float(df["grid_export_MW"].sum())
    sto = sum(float((df[f"{s}_ch"] - df[f"{s}_dis"]).sum()) for s in r["storage"])
    price = np.array(sc.network.ext_grids[0].price_cny_kwh)*1000; xp = np.array(sc.network.ext_grids[0].export_price_cny_kwh)*1000
    out = dict(case=label, zw_dc_energy_mwh=zwE, zw_grid_import_mwh=imp, zw_export_mwh=exp_,
               zw_green_share_pct=100*(1 - imp/(zwE + max(sto, 0))), re_avail_mwh=float(df.pv_avail.sum()),
               re_curtail_mwh=float((df.pv_avail - df.pv_used).sum()), zw_import_cost_cny=float((df.gen0_MW*price).sum()),
               export_revenue_cny=float((df.grid_export_MW*xp).sum()), system_energy_cost_cny=float(df.hour_cost.sum()),
               emissions_t=float(r["emissions_t"]), max_line_loading_pct=float(df.max_line_loading_pct.max()),
               storage_dis_mwh=float(sum(df[f"{s}_dis"].sum() for s in r["storage"])),
               migrated_mwh=float(df[[c for c in df if c.endswith("_mig_out")]].sum().sum()),
               zw_peak_import_mw=float(df.gen0_MW.max()))
    if len(sc.network.ext_grids) > 1:
        out.update(sh_dc_energy_mwh=float(df["SH_EAST_grid_MW"].sum()), sh_import_mwh=float(df["gen1_MW"].sum()),
                   sh_import_cost_cny=float((df.gen1_MW*np.array(sc.network.ext_grids[1].price_cny_kwh)*1000).sum()))
    if "jobs" in r:
        j = r["jobs"]; out.update(jobs_met_pct=100*float(j.met_deadline.mean()), jobs_unserved_mwh=float(j.unserved_mwh.sum()),
                                  jobs_migrated_n=int((j.migrated_mwh > 1e-4).sum()), unserved_penalty_cny=r["unserved_penalty_cny"])
    return out

def run(preset, label, case, use_storage=None, sess=None, **kw):
    s = sess or Session(id=label, artifact_dir=os.path.join(OUT, "art", label))
    st.build_scenario(s, preset=preset, **kw); sc = s.state["scenario"]
    r = eng.solve(sc, optimize=(case == "optimized"), use_storage=use_storage)
    s.state.setdefault("results", {})[case] = r
    return s, sc, r

def main():
    rows, ac_rows, profiles = [], [], {}
    for d in DAYS:
        s, sc, r = run(f"zhongwei_{d}_noSH", f"{d}_B0", "baseline"); rows.append(dict(day=d, **zw_kpi(sc, r, "B0 基线(无灵活/无储能)")))
        profiles[d] = dict(pv=[x*500 for x in sc.pv[0].profile], wind=[x*1500 for x in sc.pv[1].profile], base=r["df"].filter(like="_grid_MW").sum(axis=1).tolist())
        s, sc, r = run(f"zhongwei_{d}_noSH", f"{d}_O1", "optimized", use_storage=False); rows.append(dict(day=d, **zw_kpi(sc, r, "O1 负荷时移")))
        s, sc, r = run(f"zhongwei_{d}_noSH", f"{d}_O2", "optimized"); rows.append(dict(day=d, **zw_kpi(sc, r, "O2 时移+储能")))
        profiles[d]["opt"] = r["df"].filter(like="_grid_MW").sum(axis=1).tolist(); profiles[d]["soc"] = r["df"]["ESS_ZW_soc"].tolist()
        profiles[d]["import_b"] = None
        ac = eng.ac_check(sc, r); ac_rows.append(dict(day=d, case="O2", **{k: ac[k] for k in ["hour", "converged", "vmin_pu", "vmax_pu", "max_line_loading_pct", "max_trafo_loading_pct", "dcopf_pred_loading_pct"]}))
        s, sc, r = run(f"zhongwei_{d}", f"{d}_B0SH", "baseline"); rows.append(dict(day=d, **zw_kpi(sc, r, "B0' 基线(含上海DC)")))
        s, sc, r = run(f"zhongwei_{d}", f"{d}_O3", "optimized"); rows.append(dict(day=d, **zw_kpi(sc, r, "O3 时移+储能+跨区迁移")))
        profiles[d]["mig"] = r["df"][[c for c in r["df"] if c.endswith("_mig_out")]].sum(axis=1).tolist()
        ac = eng.ac_check(sc, r); ac_rows.append(dict(day=d, case="O3", **{k: ac[k] for k in ["hour", "converged", "vmin_pu", "vmax_pu", "max_line_loading_pct", "max_trafo_loading_pct", "dcopf_pred_loading_pct"]}))
        # 交流校核：最高送出时刻（午间）
        hh = int(np.argmax(r["df"].grid_export_MW.values)); ac = eng.ac_check(sc, r, hh)
        ac_rows.append(dict(day=d, case=f"O3@最大外送{hh}时", **{k: ac[k] for k in ["hour", "converged", "vmin_pu", "vmax_pu", "max_line_loading_pct", "max_trafo_loading_pct", "dcopf_pred_loading_pct"]}, lines=ac["line_loading_pct"]))
    df = pd.DataFrame(rows); df.to_csv(os.path.join(OUT, "kpi_typical_days.csv"), index=False)
    pd.DataFrame(ac_rows).to_csv(os.path.join(OUT, "ac_check.csv"), index=False)
    # 年化（4 典型日等权 × 365）
    ann = df.groupby("case").mean(numeric_only=True)*365
    ann.to_csv(os.path.join(OUT, "annualized.csv"))
    # Pareto（含上海、冬季小风日）
    s = Session(id="pareto", artifact_dir=os.path.join(OUT, "art", "pareto")); st.build_scenario(s, preset="zhongwei_winter_lowwind")
    par = p1.run_pareto_sweep(s, weights=[0, 1, 2, 5, 10, 20, 50, 100])
    # 任务级：夏季大风日 40 任务
    s, sc, rb = run("zhongwei_summer_highwind_jobs40", "jobs_B", "baseline"); jb = zw_kpi(sc, rb, "任务基线(本地均匀)")
    s, sc, ro = run("zhongwei_summer_highwind_jobs40", "jobs_O", "optimized", sess=s); jo = zw_kpi(sc, ro, "任务优化(时移+迁移+储能)")
    ro["jobs"].to_csv(os.path.join(OUT, "jobs_optimized.csv"), index=False); rb["jobs"].to_csv(os.path.join(OUT, "jobs_baseline.csv"), index=False)
    ro["links"].to_csv(os.path.join(OUT, "migration_optimized.csv"), index=False)
    json.dump(dict(pareto=par["points"], pareto_baseline=par["baseline"], tradeoff=par["tradeoff"], jobs=[jb, jo], profiles=profiles,
                   lat_sensitive_migrated=int(((ro["jobs"].migrated_mwh > 1e-4) & ro["jobs"].latency_sensitive).sum())),
              open(os.path.join(OUT, "study.json"), "w"), ensure_ascii=False, indent=1, default=float)
    pd.set_option("display.width", 250); pd.set_option("display.max_columns", 30)
    print(df.round(1).to_string()); print(ann.round(0).to_string()); print(pd.DataFrame(ac_rows).drop(columns=["lines"], errors="ignore").round(3).to_string())
    print(json.dumps(par["points"], ensure_ascii=False)); print(par["baseline"], par["tradeoff"]); print(jb); print(jo)


if __name__ == "__main__":
    main()
