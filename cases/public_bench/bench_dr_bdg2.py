"""B4: Building Data Genome 2 (BDG2, CC-BY-4.0, https://github.com/buds-lab/building-data-genome-project-2)
公开逐时电表数据 验证 app.market.core.dr_baseline / dr_assess 的基线精度与响应考核判定。
做法：无真实 DR 事件 → '伪事件' 反事实检验：选 2017-06~08 工作日 14-17 时为事件，实际负荷=真值，
基线误差 = 基线 - 真值；再注入已知削减(10%/20%)，看 dr_assess 判定有效/考核是否正确。
不涉及任何官方交易/补偿收益。"""
import os, sys, json, hashlib
import numpy as np, pandas as pd
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))
from app.market import core as C
R = os.path.join(os.path.dirname(__file__), "raw"); OUT = os.path.join(os.path.dirname(__file__), "results")
f = f"{R}/bdg2_electricity_cleaned.csv"
df = pd.read_csv(f, index_col=0, parse_dates=True)
df = df["2017-04-01":"2017-08-31 23:00"]
ok = [c for c in df.columns if df[c].notna().mean() > 0.995 and df[c].mean() > 20]   # 完整且非微小负荷 (kWh/h)
rng = np.random.default_rng(2017); B = sorted(rng.choice(ok, size=min(120, len(ok)), replace=False).tolist())
rule = C.get_rule("demo_ningxia"); EV = [14, 15, 16]
days = pd.date_range("2017-06-01", "2017-08-31"); wdays = [d for d in days if d.weekday() < 5]
rows = []
for b in B:
    s = df[b].interpolate(limit=3)
    for d in rng.choice(wdays, size=8, replace=False):
        d = pd.Timestamp(d); hist_days = [d - pd.Timedelta(days=k) for k in range(15, 0, -1)]
        H = [s[x: x + pd.Timedelta(hours=23)].values for x in hist_days]
        act = s[d: d + pd.Timedelta(hours=23)].values
        if any(len(h) != 24 or np.isnan(h).any() for h in H) or len(act) != 24 or np.isnan(act).any(): continue
        types = ["workday" if x.weekday() < 5 else "weekend" for x in hist_days]
        for meth in ("prior_n_days", "similar_days_avg", "adjusted_similar_days"):
            for dt in (False, True):
                kw = dict(history_day_types=types, event_day_type="workday") if dt else {}
                bl = np.array(C.dr_baseline([h.tolist() for h in H], meth, EV, actual=act.tolist(), n_days=rule["dr"]["n_days"],
                                            adjust_window_h=rule["dr"]["adjust_window_h"], adjust_cap_pct=rule["dr"]["adjust_cap_pct"], **kw)["baseline_mw"])
                tru = act[EV]; est = bl[EV]
                r = dict(building=b, day=str(d.date()), method=meth, day_type_filter=dt, mae=float(np.mean(np.abs(est - tru))),
                         ape=float(np.mean(np.abs(est - tru)/tru)*100), bias_pct=float((est.sum() - tru.sum())/tru.sum()*100))
                for cut in (0.10, 0.20):   # 注入真实削减: 实际 = 真值×(1-cut)；申报 = 真实削减均值
                    a2 = act.copy(); a2[EV] = act[EV]*(1 - cut); decl = float(np.mean(act[EV]*cut))
                    a = C.dr_assess(rule, bl.tolist(), a2.tolist(), EV, decl)
                    r[f"ratio_{int(cut*100)}"] = a["ratio"]; r[f"valid_{int(cut*100)}"] = a["valid"]; r[f"penalized_{int(cut*100)}"] = a["penalty_cny"] > 0
                rows.append(r)
R_ = pd.DataFrame(rows); R_.to_csv(f"{OUT}/b4_dr_bdg2_events.csv", index=False)
g = R_.groupby(["method", "day_type_filter"]).agg(n=("mae", "size"), mape_median=("ape", "median"), mape_mean=("ape", "mean"),
        bias_median_pct=("bias_pct", "median"), ratio20_median=("ratio_20", "median"), false_invalid_20=("valid_20", lambda x: 1 - x.mean()),
        false_invalid_10=("valid_10", lambda x: 1 - x.mean()), false_penalty_20=("penalized_20", "mean")).reset_index()
print(g.round(3).to_string())
crit = {}
for _, x in g.iterrows():
    crit[f"{x.method}|dtf={x.day_type_filter}"] = dict(mape_median_le_10=bool(x.mape_median <= 10), abs_bias_le_3=bool(abs(x.bias_median_pct) <= 3),
                                                         false_invalid_20_le_10pct=bool(x.false_invalid_20 <= 0.10))
json.dump(dict(source=dict(url="https://media.githubusercontent.com/media/buds-lab/building-data-genome-project-2/master/data/meters/cleaned/electricity_cleaned.csv",
                           license="CC-BY-4.0 (BDG2)", sha256=hashlib.sha256(open(f, "rb").read()).hexdigest()),
               n_buildings=len(B), n_events=int(len(R_)/6), summary=g.to_dict("records"), criteria=crit), open(f"{OUT}/b4_dr_bdg2.json", "w"), indent=1)
print(json.dumps(crit, indent=0))
