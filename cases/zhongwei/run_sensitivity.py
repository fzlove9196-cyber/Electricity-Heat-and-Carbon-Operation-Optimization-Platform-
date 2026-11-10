"""敏感性：外送上限（消纳受限）与储能规模。"""
import os, sys, json, warnings; warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from app.scenario import load_preset
from app.tools import sdco_engine as eng
from run_study import zw_kpi, OUT
res = []
for cap in [1200, 800, 500]:
    for d in ["summer_highwind", "winter_highwind"]:
        sc = load_preset(f"zhongwei_{d}_noSH"); sc.network.ext_grids[0].export_max_mw = cap
        for lab, opt, us in [("B0", False, False), ("O1", True, False), ("O2", True, True)]:
            r = eng.solve(sc, opt, us); k = zw_kpi(sc, r, lab); res.append(dict(kind="export_cap", cap=cap, day=d, **{"case": lab, **{x: round(k[x], 1) for x in ["re_curtail_mwh", "zw_grid_import_mwh", "system_energy_cost_cny", "storage_dis_mwh"]}}))
for e in [0, 100, 150, 200]:
    sc = load_preset("zhongwei_winter_lowwind_noSH")
    if e: sc.storage[0].energy_mwh = e; sc.storage[0].power_mw = e/2
    r = eng.solve(sc, True, bool(e)); k = zw_kpi(sc, r, "O2")
    res.append(dict(kind="storage", cap=e, day="winter_lowwind", **{"case": "O2", **{x: round(k[x], 1) for x in ["zw_grid_import_mwh", "zw_green_share_pct", "zw_import_cost_cny", "system_energy_cost_cny", "storage_dis_mwh"]}}))
json.dump(res, open(os.path.join(OUT, "sensitivity.json"), "w"), ensure_ascii=False, indent=1)
for x in res: print(x)
