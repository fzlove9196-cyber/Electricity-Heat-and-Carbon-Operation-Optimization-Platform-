"""第二轮真实项目验证：通过 app 工具层（build_scenario → run_dispatch 基线/优化 → run_ac_check）运行 cases/validation/presets.json 中全部预设，
并做物理合理性检查（求解状态、热/电/热网平衡残差、PUE 区间、入口/供液温度、末端温度、DR 履约），输出 cases/validation/results.json。"""
import json, os, sys, time, warnings, shutil, traceback; warnings.filterwarnings("ignore")
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."); sys.path.insert(0, ROOT)
import numpy as np
from app.tools.base import Session
from app.tools import call_tool
from app.tools.sim_tools import _kpis
OUTD = os.path.join(ROOT, "cases", "validation", "out")
PUB = {  # 公开对标值（PUE 为年均/设计值；典型日结果只作量级比较）
    "ulanqab_cicdata": dict(pue=1.147, green_share_pct=(35.0, 38.74)), "ulanqab_21vianet": dict(pue=None),
    "shaoguan": dict(pue={"华南数谷_液冷": 1.15, "华南数谷_风冷": 1.25}), "guian_huawei": dict(pue=1.12), "renhe_alibaba": dict(pue=1.09),
    "wuhu_telecom": dict(pue=1.25), "lingang_dr": dict(dr_mw=22.84, dr_req=23.0), "odense_meta": dict(hp_mw=45.0, cop=(4.5, 5.0), heat_mwh_y=165000)}

def run(proj, name):
    s = Session(id="val_" + name, artifact_dir=os.path.join(OUTD, "art", name)); rec = dict(project=proj, preset=name); t0 = time.time()
    call_tool(s, "build_scenario", {"preset": name}); sc = s.state["scenario"]
    for case in ("baseline", "optimized"):
        try:
            call_tool(s, "run_dispatch", {"case": case}); r = s.state["results"][case]; k = _kpis(sc, r)
            x = {a: (round(float(b), 4) if isinstance(b, (int, float, np.floating)) else b) for a, b in k.items() if not isinstance(b, (list, dict))}
            th = r.get("thermal") or {}
            if th:
                x["bal_thermal"] = max(v["thermal_balance_max_residual"] for v in th["dcs"].values())
                x["bal_elec"] = max(v["elec_balance_max_residual"] for v in th["dcs"].values())
                x["bal_heat"] = (th.get("heat") or {}).get("balance_max_residual")
                x["dc"] = {}
                for d in sc.data_centers:
                    df = r["df"]; it = df[f"{d.name}_IT_MW"].values; g = df[f"{d.name}_grid_MW"].values
                    x["dc"][d.name] = dict(pue_day=round(float(g.sum()/it.sum()), 4), pue_min=round(float((g/it).min()), 4), pue_max=round(float((g/it).max()), 4),
                                           tin_min=round(float(df[f"{d.name}_Tin_C"].min()), 2), tin_max=round(float(df[f"{d.name}_Tin_C"].max()), 2),
                                           t_allow=d.thermal.t_allow_max_c, t_min=d.thermal.t_min_c, mode=d.thermal.cooling_mode, safety=th["dcs"][d.name].get("safety"))
                    if f"{d.name}_hp_heat_MWth" in df: x["dc"][d.name]["hp_mwh"] = round(float(df[f"{d.name}_hp_heat_MWth"].sum()), 1)
                if th.get("heat"): x["heat"] = {a: b for a, b in th["heat"].items() if not isinstance(b, list) or len(b) <= 24}
            if r.get("dr"): x["dr"] = r["dr"]
            x["status"] = r.get("status", "optimal"); rec[case] = x
        except Exception as e:
            rec[case] = dict(error=f"{type(e).__name__}: {str(e)[:300]}", tb=traceback.format_exc()[-600:])
            continue
        try:
            ac = call_tool(s, "run_ac_check", {"case": case})
            rec[case]["ac"] = {a: (round(ac[a], 4) if isinstance(ac[a], float) else ac[a]) for a in ("converged", "vmin_pu", "vmax_pu", "max_branch_loading_pct", "voltage_ok", "loading_ok")}
        except Exception as e: rec[case]["ac"] = dict(converged=False, error=str(e)[:200])
    rec["seconds"] = round(time.time() - t0, 1); return rec

if __name__ == "__main__":
    P = json.load(open(os.path.join(OUTD, "presets.json"))); only = sys.argv[1:]
    R = []
    for proj, names in P.items():
        if only and proj not in only: continue
        for n in names:
            r = run(proj, n); R.append(r); o = r.get("optimized", {})
            print(n, r["seconds"], "s", o.get("error") or {k: o.get(k) for k in ("cost_cny", "pue_avg", "green_share_pct", "tin_max_c", "bal_thermal", "bal_heat")},
                  {d: (v["pue_day"], v["tin_max"]) for d, v in (o.get("dc") or {}).items()}, (o.get("ac") or {}).get("converged"), flush=True)
    p = os.path.join(OUTD, "results.json" if not only else f"results_{'_'.join(only)}.json")
    json.dump(dict(results=R, published=PUB), open(p, "w"), ensure_ascii=False, indent=1, default=str); print("wrote", p)
