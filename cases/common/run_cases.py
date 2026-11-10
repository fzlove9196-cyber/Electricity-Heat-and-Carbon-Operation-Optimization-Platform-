"""多公开项目案例批量测试：每个预设 基线 vs 优化 调度 + 交流校核 + 模型拓扑图。通过 app 工具层运行（与对话同一套）。
用法: python cases/common/run_cases.py [case_dir ...]   -> cases/<case>/results/{summary.json,kpi.csv,*.png}"""
import json, os, sys, glob, time, traceback, warnings, shutil; warnings.filterwarnings("ignore")
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."); sys.path.insert(0, ROOT)
import pandas as pd
from app.tools.base import Session
from app.tools import call_tool
from app.tools.sim_tools import _kpis
from app.tools.model_edit import metrics
CASES = os.path.join(ROOT, "cases")
KEEP = ["cost_cny", "energy_cost_cny", "grid_import_mwh", "grid_export_mwh", "green_share_pct", "renewable_avail_mwh", "renewable_used_mwh",
        "renewable_curtail_pct", "pv_curtail_mwh", "emissions_tco2", "max_line_loading_pct", "migrated_mwh", "dc_energy_mwh", "dc_peak_mw"]

def run_preset(name, outdir):
    s = Session(id=name, artifact_dir=os.path.join(outdir, "art", name)); rec = dict(preset=name)
    t0 = time.time()
    try:
        call_tool(s, "build_scenario", {"preset": name}); sc = s.state["scenario"]
        rec["model"] = {k: v for k, v in s.state["model_graph"]["summary"].items()}
        shutil.copy(os.path.join(s.artifact_dir, "model_topology.png"), os.path.join(outdir, f"{name}_topology.png"))
    except Exception as e:
        rec["error"] = f"建模失败: {e}"; return rec
    for case in ("baseline", "optimized"):
        try:
            call_tool(s, "run_dispatch", {"case": case}); r = s.state["results"][case]
            k = _kpis(sc, r); rec[case] = {x: k.get(x) for x in KEEP}; rec[case]["metrics"] = metrics(sc, r)
            rec[case]["ppa_cost_cny"] = round(r.get("ppa_cost_cny", 0), 0); rec[case]["demand_charge_cny"] = round(r.get("demand_charge_cny", 0), 0)
            if "jobs" in r: rec[case]["jobs_deadline_met_pct"] = k.get("jobs_deadline_met_pct"); rec[case]["jobs_migrated_n"] = k.get("jobs_migrated_n")
        except Exception as e:
            rec[case] = {"error": str(e)[:300]}; continue
        try:
            ac = call_tool(s, "run_ac_check", {"case": case})
            rec[case]["ac"] = {x: (round(ac[x], 4) if isinstance(ac[x], float) else ac[x]) for x in ("hour", "converged", "vmin_pu", "vmax_pu", "max_branch_loading_pct", "dcopf_pred_loading_pct", "voltage_ok", "loading_ok", "losses_mw")}
        except Exception as e:
            rec[case]["ac"] = {"converged": False, "error": f"{type(e).__name__}: {str(e)[:200]}"}
    try:
        shutil.copy(os.path.join(s.artifact_dir, "model_topology.png"), os.path.join(outdir, f"{name}_energyflow.png"))
    except Exception: pass
    rec["seconds"] = round(time.time() - t0, 1)
    return rec

def main(dirs):
    allrec = {}
    for d in dirs:
        out = os.path.join(CASES, d, "results"); os.makedirs(out, exist_ok=True)
        names = sorted(os.path.splitext(os.path.basename(f))[0] for f in glob.glob(os.path.join(CASES, d, "*.json")))
        recs = [run_preset(n, out) for n in names]; allrec[d] = recs
        json.dump(recs, open(os.path.join(out, "summary.json"), "w"), ensure_ascii=False, indent=1, default=str)
        rows = []
        for r in recs:
            for c in ("baseline", "optimized"):
                x = r.get(c, {}); rows.append(dict(preset=r["preset"], case=c, error=x.get("error") or r.get("error"), **(x.get("metrics") or {}),
                                                   ac_converged=(x.get("ac") or {}).get("converged"), ac_vmin=(x.get("ac") or {}).get("vmin_pu"),
                                                   ac_max_load=(x.get("ac") or {}).get("max_branch_loading_pct"), ppa_cny=x.get("ppa_cost_cny"), demand_cny=x.get("demand_charge_cny")))
        pd.DataFrame(rows).to_csv(os.path.join(out, "kpi.csv"), index=False)
        print(d); print(pd.DataFrame(rows).drop(columns=["error"]).to_string()); print([(r["preset"], r.get("error"), r.get("optimized", {}).get("error")) for r in recs if r.get("error") or r.get("optimized", {}).get("error") or r.get("baseline", {}).get("error")])
    return allrec

if __name__ == "__main__":
    main(sys.argv[1:] or ["helinger", "qingyang", "qinghai_hainan", "zhangbei"])
