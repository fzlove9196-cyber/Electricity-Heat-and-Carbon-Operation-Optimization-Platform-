"""B4-methods: 公开 DR 基线方法比较（BDG2 电表 + BDG2 气象），时间顺序 验证/测试 分离。
候选方法（运行前固定，见 CANDS）；选择规则（运行前固定）：在 VALIDATION(2016 夏) 全部 N 汇总上，
  先筛 |偏差中位|≤3% 且 0%削减误报率 FP0≤5%，再取 20% 削减误判无效率 FN20 最低者（并列取 MAPE 低）。
选定后在 TEST_SUMMER(2017 夏) 与 TEST_WINTER(2017-01-16~03-15) 上一次性评估，不再改参数。
无泄漏：事件时段实测置 NaN 后再传入；历史只取事件日之前；气温为外生变量（事件日气温在实务中可由气象站事后得到）。
伪事件为反事实方法诊断，不代表真实 DR 效果；考核规则为示范规则包，不代表中国任何正式规则。"""
import os, sys, json, hashlib
import numpy as np, pandas as pd
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))
from app.market import core as C
R = os.path.join(os.path.dirname(__file__), "raw"); OUT = os.path.join(os.path.dirname(__file__), "results")
fe, fw = f"{R}/bdg2_electricity_cleaned.csv", f"{R}/bdg2_weather.csv"
el = pd.read_csv(fe, index_col=0, parse_dates=True)
wx = pd.read_csv(fw, parse_dates=["timestamp"]).pivot_table(index="timestamp", columns="site_id", values="airTemperature")
wx = wx.reindex(el.index).interpolate(limit=6)
ok = [c for c in el.columns if el[c].notna().mean() > 0.99 and el[c].mean() > 20 and c.split("_")[0] in wx and wx[c.split("_")[0]].notna().mean() > 0.98]
el = el[ok].interpolate(limit=3); site = pd.Series({c: c.split("_")[0] for c in ok})
rule = C.get_rule("demo_ningxia"); EV = [14, 15, 16]
CANDS = {
 "L0_similar_days_default": dict(legacy="similar_days_avg"),
 "L1_adjusted_daytype": dict(legacy="adjusted_similar_days", dt=True),
 "caiso_10of10_mult": dict(method="x_of_y", x=10, y=10, adjust="mult"),
 "pjm_4of5_add": dict(method="x_of_y", x=4, y=5, adjust="add"),
 "10of10_add": dict(method="x_of_y", x=10, y=10, adjust="add"),
 "towt_none": dict(method="towt", adjust="none"),
 "towt_add": dict(method="towt", adjust="add"),
 "towt_mult": dict(method="towt", adjust="mult"),
 "ens_10of10add_towtadd": dict(ens=("10of10_add", "towt_add")),
}
PERIODS = {"validation_2016_summer": ("2016-06-01", "2016-08-31"), "test_2017_summer": ("2017-06-01", "2017-08-31"),
           "test_2017_winter": ("2017-01-16", "2017-03-15")}
def baseline(name, hist, types, act_m, ht, et):
    c = CANDS[name]
    if "ens" in c: return np.mean([baseline(k, hist, types, act_m, ht, et) for k in c["ens"]], axis=0)
    if "legacy" in c:
        kw = dict(history_day_types=types, event_day_type="workday") if c.get("dt") else {}
        return np.array(C.dr_baseline(hist[-15:].tolist(), c["legacy"], EV, actual=act_m.tolist(), n_days=5, adjust_window_h=2, adjust_cap_pct=20, **kw)["baseline_mw"])
    kw = {k: v for k, v in c.items()}
    return np.array(C.dr_baseline_v2(hist, EV, history_day_types=types, event_day_type="workday", actual=act_m, history_temps=ht, event_temps=et, **kw)["baseline_mw"])
rows = []; rng_p = np.random.default_rng(7)
ports = {}
for N in (1, 5, 10, 20):
    sites = [s for s, n in site.value_counts().items() if n >= N]; ports[N] = []
    for k in range(30):
        s0 = sites[rng_p.integers(len(sites))]; ports[N].append((s0, rng_p.choice(site[site == s0].index.values, size=N, replace=False)))
for per, (a, b) in PERIODS.items():
    rng_d = np.random.default_rng(abs(hash(per)) % 2**32 if False else {"validation_2016_summer": 1, "test_2017_summer": 2, "test_2017_winter": 3}[per])
    wd = [d for d in pd.date_range(a, b) if d.weekday() < 5]; days = sorted(rng_d.choice(wd, size=15, replace=False))
    for N, plist in ports.items():
        for k, (s0, mem) in enumerate(plist):
            load = el[mem].sum(axis=1); T = wx[s0]
            for d in days:
                d = pd.Timestamp(d); hd = [d - pd.Timedelta(days=j) for j in range(60, 0, -1)]
                try:
                    hist = np.array([load[x: x + pd.Timedelta(hours=23)].values for x in hd]); ht = np.array([T[x: x + pd.Timedelta(hours=23)].values for x in hd])
                except ValueError: continue
                act = load[d: d + pd.Timedelta(hours=23)].values; et = T[d: d + pd.Timedelta(hours=23)].values
                if np.isnan(hist).any() or np.isnan(ht).any() or np.isnan(act).any() or np.isnan(et).any() or hist.shape != (60, 24): continue
                types = ["workday" if x.weekday() < 5 else "weekend" for x in hd]
                act_m = act.copy(); act_m[EV] = np.nan
                for name in CANDS:
                    bl = baseline(name, hist, types, act_m, ht, et); tru = act[EV]; est = bl[EV]
                    r = dict(period=per, n_bldg=N, portfolio=k, day=str(d.date()), method=name,
                             ape=float(np.mean(np.abs(est - tru)/tru)*100), bias_pct=float((est.sum() - tru.sum())/tru.sum()*100))
                    decl20 = float(np.mean(tru*0.2))
                    for cut in (0.0, 0.1, 0.2, 0.3):
                        a2 = act.copy(); a2[EV] = act[EV]*(1 - cut)
                        v = C.dr_assess(rule, bl.tolist(), a2.tolist(), EV, float(np.mean(tru*cut)) if cut > 0 else decl20)["valid"]
                        r[f"valid_{int(cut*100)}"] = v
                    rows.append(r)
D = pd.DataFrame(rows); D.to_csv(f"{OUT}/b4m_events.csv", index=False)
def wilson(p, n, z=1.96):
    c = (p + z*z/(2*n))/(1 + z*z/n); h = z*np.sqrt(p*(1-p)/n + z*z/(4*n*n))/(1 + z*z/n); return c - h, c + h
def summ(g):
    n = len(g); fn20 = 1 - g.valid_20.mean(); lo, hi = wilson(fn20, n)
    return pd.Series(dict(n_events=n, mape_median=g.ape.median(), mape_p90=g.ape.quantile(.9), bias_median=g.bias_pct.median(),
                          FN10=1 - g.valid_10.mean(), FN20=fn20, FN20_lo=lo, FN20_hi=hi, FN30=1 - g.valid_30.mean(), FP0=g.valid_0.mean()))
S = D.groupby(["period", "method", "n_bldg"]).apply(summ).reset_index()
P = D.groupby(["period", "method"]).apply(summ).reset_index()
val = P[P.period == "validation_2016_summer"].copy()
elig = val[(val.bias_median.abs() <= 3) & (val.FP0 <= 0.05)].sort_values(["FN20", "mape_median"])
selected = elig.method.iloc[0] if len(elig) else None
S["pass"] = (S.mape_median <= 10) & (S.bias_median.abs() <= 3) & (S.FN20 <= 0.10) & (S.FP0 <= 0.05)
S["pass_ci"] = S["pass"] & (S.FN20_hi <= 0.10)
pd.set_option("display.width", 250)
print("VALIDATION pooled:\n", val.round(3).to_string()); print("SELECTED:", selected)
print(S[S.method.isin([selected, "L0_similar_days_default", "L1_adjusted_daytype"])].round(3).to_string())
json.dump(dict(sources=dict(electricity=dict(sha256=hashlib.sha256(open(fe, "rb").read()).hexdigest()),
                            weather=dict(url="https://media.githubusercontent.com/media/buds-lab/building-data-genome-project-2/master/data/weather/weather.csv",
                                         license="CC BY 4.0", sha256=hashlib.sha256(open(fw, "rb").read()).hexdigest())),
               candidates=CANDS, periods=PERIODS, event_hours=EV, portfolios_per_N=30, event_days_per_period=15,
               selection_rule="validation pooled: |bias|<=3% & FP0<=5%, then min FN20, tie min MAPE", selected=selected,
               criteria="mape_median<=10 & |bias|<=3 & FN20<=0.10 & FP0<=0.05 ; pass_ci additionally FN20 95% upper<=0.10",
               validation_pooled=val.to_dict("records"), by_n=S.to_dict("records"), pooled=P.to_dict("records")),
          open(f"{OUT}/b4m_dr_methods.json", "w"), indent=1, default=str)
