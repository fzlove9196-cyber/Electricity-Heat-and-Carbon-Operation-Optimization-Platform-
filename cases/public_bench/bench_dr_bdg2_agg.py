"""B4-agg: BDG2 多栋建筑聚合 DR 基线验证（同站点随机组合，模拟聚合商资源池）。
事件定义：2017-06-01~08-31 工作日 14:00-17:00（小时 14,15,16），与 B4 单栋相同。
基线公式：app.market.core.dr_baseline，参数全部取 demo_ningxia 规则包默认值（n_days=5, adjust_window_h=2, adjust_cap_pct=20），
  未做任何调参；只用事件日之前 15 天历史 + （adjusted 方法）事件开始前的窗口（小时 11-12），不使用事件时段数据。
聚合：组合内建筑逐时负荷求和后再算基线（聚合商口径）。注入削减 = 真实负荷×cut，申报 = 真实削减均值。
Train/Test：无可调参数故无训练；事件日按随机种子 2017 抽样，组合按种子 7 抽样，结果完全可复现。"""
import os, sys, json, hashlib
import numpy as np, pandas as pd
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))
from app.market import core as C
R = os.path.join(os.path.dirname(__file__), "raw"); OUT = os.path.join(os.path.dirname(__file__), "results")
f = f"{R}/bdg2_electricity_cleaned.csv"
df = pd.read_csv(f, index_col=0, parse_dates=True)["2017-04-01":"2017-08-31 23:00"]
ok = [c for c in df.columns if df[c].notna().mean() > 0.995 and df[c].mean() > 20]
df = df[ok].interpolate(limit=3)
site = pd.Series({c: c.split("_")[0] for c in ok})
rule = C.get_rule("demo_ningxia"); dr = rule["dr"]; EV = [14, 15, 16]
rng_d = np.random.default_rng(2017); rng_p = np.random.default_rng(7)
wdays = [d for d in pd.date_range("2017-06-01", "2017-08-31") if d.weekday() < 5]
ev_days = sorted(rng_d.choice(wdays, size=20, replace=False))
rows = []
for N in (1, 5, 10, 20):
    for k in range(40):   # 40 个随机组合 / 规模
        sites = [s for s, n in site.value_counts().items() if n >= N]
        s0 = sites[rng_p.integers(len(sites))]
        mem = rng_p.choice(site[site == s0].index.values, size=N, replace=False)
        load = df[mem].sum(axis=1)
        for d in ev_days:
            d = pd.Timestamp(d); hd = [d - pd.Timedelta(days=j) for j in range(15, 0, -1)]
            H = [load[x: x + pd.Timedelta(hours=23)].values for x in hd]; act = load[d: d + pd.Timedelta(hours=23)].values
            if any(len(h) != 24 or np.isnan(h).any() for h in H) or len(act) != 24 or np.isnan(act).any(): continue
            types = ["workday" if x.weekday() < 5 else "weekend" for x in hd]
            for meth in ("similar_days_avg", "adjusted_similar_days"):
                for dt in (False, True):
                    kw = dict(history_day_types=types, event_day_type="workday") if dt else {}
                    # adjusted 方法只读 actual 的事件前窗口；传入时把事件时段置 NaN 以证明无泄漏
                    act_masked = act.copy(); act_masked[EV] = np.nan
                    bl = np.array(C.dr_baseline([h.tolist() for h in H], meth, EV, actual=act_masked.tolist(), n_days=dr["n_days"],
                                                adjust_window_h=dr["adjust_window_h"], adjust_cap_pct=dr["adjust_cap_pct"], **kw)["baseline_mw"])
                    assert np.isfinite(bl[EV]).all()
                    tru = act[EV]; est = bl[EV]
                    r = dict(n_bldg=N, portfolio=k, site=s0, day=str(d.date()), method=meth, day_type_filter=dt,
                             ape=float(np.mean(np.abs(est - tru)/tru)*100), bias_pct=float((est.sum() - tru.sum())/tru.sum()*100))
                    for cut in (0.10, 0.20):
                        a2 = act.copy(); a2[EV] = act[EV]*(1 - cut)
                        a = C.dr_assess(rule, bl.tolist(), a2.tolist(), EV, float(np.mean(act[EV]*cut)))
                        r[f"invalid_{int(cut*100)}"] = not a["valid"]; r[f"penalized_{int(cut*100)}"] = a["penalty_cny"] > 0
                    rows.append(r)
R_ = pd.DataFrame(rows); R_.to_csv(f"{OUT}/b4agg_dr_bdg2_events.csv", index=False)
g = R_.groupby(["n_bldg", "method", "day_type_filter"]).agg(n_events=("ape", "size"), n_portfolios=("portfolio", "nunique"),
        mape_median=("ape", "median"), mape_p90=("ape", lambda x: np.percentile(x, 90)), bias_median_pct=("bias_pct", "median"),
        false_invalid_20=("invalid_20", "mean"), false_invalid_10=("invalid_10", "mean"), false_penalty_20=("penalized_20", "mean")).reset_index()
z = 1.96; n_ = g.n_events; ph = g.false_invalid_20   # Wilson 95% CI
g["fi20_ci_lo"] = (ph + z*z/(2*n_) - z*np.sqrt(ph*(1-ph)/n_ + z*z/(4*n_*n_)))/(1 + z*z/n_)
g["fi20_ci_hi"] = (ph + z*z/(2*n_) + z*np.sqrt(ph*(1-ph)/n_ + z*z/(4*n_*n_)))/(1 + z*z/n_)
g["pass"] = (g.mape_median <= 10) & (g.bias_median_pct.abs() <= 3) & (g.false_invalid_20 <= 0.10)
print(g.round(3).to_string())
json.dump(dict(source=dict(file="bdg2_electricity_cleaned.csv", sha256=hashlib.sha256(open(f, "rb").read()).hexdigest(), license="CC BY 4.0"),
               event_definition="2017 Jun-Aug weekdays, hours 14-16 (20 sampled days, seed 2017)", portfolios="same-site random, seed 7, 40 per size",
               criteria="mape_median<=10 & |bias|<=3 & false_invalid_20<=0.10", no_leakage="event-hour actuals masked to NaN before baseline call",
               summary=g.to_dict("records")), open(f"{OUT}/b4agg_dr_bdg2.json", "w"), indent=1)
