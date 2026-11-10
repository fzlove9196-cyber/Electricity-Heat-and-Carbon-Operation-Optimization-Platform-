"""P0 运营沙盘真实案例验证：中卫/乌兰察布/韶关 组合，日前-日内-实时-DR-结算闭环（示范规则【假设】）。
用法: PYTHONPATH=. python cases/market_p0/run_closed_loop.py  → cases/market_p0/results/"""
import json, os, tempfile
os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="mkp0_"))
from app.market import core as M
OUT = os.path.join(os.path.dirname(__file__), "results"); os.makedirs(OUT, exist_ok=True)
rows = []
for k in ("zhongwei", "ulanqab", "shaoguan"):
    o = M.run_closed_loop("pf-" + k, seed=7)
    json.dump(o, open(os.path.join(OUT, f"{k}_loop.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1, default=float)
    kp = o["kpi"]; st = o["settlement"]; dec = o["real_time"]["decomposition"]
    rows.append({"case": k, "rule": o["rule"], "n_resources": len(M.get_portfolio("pf-" + k)["resources"]),
                 "excluded": [e["name"] for e in o["excluded"]], "da_feasible": o["day_ahead"]["check"]["feasible"],
                 "da_warnings": o["day_ahead"]["warnings"], "energy_mwh": st["energy_mwh"],
                 "net_cost_cny": kp["net_cost_cny"], "cf_cost_cny": kp["cf_net_cost_cny"], "saving_cny": kp["saving_cny"],
                 "saving_pct": kp["saving_pct"], "abs_dev_mwh": kp["abs_dev_mwh"], "abs_dev_pct": kp["abs_dev_pct"],
                 "dev_penalty_cny": kp["deviation_penalty_cny"], "cf_dev_penalty_cny": o["counterfactual"]["deviation_penalty_cny"],
                 "dr_mw": dec["instruction"]["mw"], "dr_ratio": kp["dr_ratio"], "dr_payment_cny": kp["dr_payment_cny"],
                 "tickets": sorted({t["kind"] for t in dec["tickets"]}), "rmse_mw": kp["tracking_rmse_mw"],
                 "thermal_ok": kp["thermal_ok"], "max_temp_c": kp["max_temp_c"], "max_rate_k_h": kp["max_rate_k_h"]})
json.dump(rows, open(os.path.join(OUT, "summary.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
for r in rows: print(json.dumps(r, ensure_ascii=False))
