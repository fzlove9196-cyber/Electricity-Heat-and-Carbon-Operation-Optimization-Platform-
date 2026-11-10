"""B3: 公开电价 (AEMO NEM SA1 5-min RRP, 2024-01) + 公开气象 (Open-Meteo ERA5 archive, Adelaide 逐时气温)
驱动 app.market.core.optimize，比较日前/日内滚动与 naive / myopic / 无日内 / 无热安全 / 完美预知 策略。
价格单位: AUD/MWh(原值，不换算)；交易规则仍为 demo_ningxia【示范】；资源 = zhongwei 案例(DC+ESS+UPS, 柴发按规则禁用)。
预测 = 前一日同小时持续性 (价格与气温)；日内滚动 每4h, 当前起4h用实际值(假设短时预测准确)，其余用持续性。
碳排: 常数因子 (澳 NGA 2024 SA Scope2 0.22 tCO2e/MWh，【近似】)，因此碳差异只反映电量差异。"""
import os, sys, json, copy, hashlib
import numpy as np, pandas as pd
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))
from app.market import core as C
if "--legacy-core" in sys.argv:   # 复现修复前行为: 载入修复前 core 快照 (raw/market_core.py.before_fix)
    import importlib.util
    import importlib.machinery
    _ld = importlib.machinery.SourceFileLoader("app.market.core_legacy", os.path.join(os.path.dirname(__file__), "raw/market_core.py.before_fix"))
    _sp = importlib.util.spec_from_loader(_ld.name, _ld)
    import app.market.core as _new; C = importlib.util.module_from_spec(_sp); _sp.loader.exec_module(C); C.CASES = _new.CASES; C.HERE = _new.HERE
R = os.path.join(os.path.dirname(__file__), "raw"); OUT = os.path.join(os.path.dirname(__file__), "results")
H = 24; EF = 0.22; TAG = sys.argv[sys.argv.index("--tag")+1] if "--tag" in sys.argv else "run"
sha = lambda f: hashlib.sha256(open(f, "rb").read()).hexdigest()
files = [f"{R}/aemo_SA1_202312.csv", f"{R}/aemo_SA1_202401.csv", f"{R}/openmeteo_adelaide_202312_202401.json"]
pr = pd.concat([pd.read_csv(f) for f in files[:2]]); pr["ts"] = pd.to_datetime(pr.SETTLEMENTDATE) - pd.Timedelta(minutes=5)  # 区间起点
hp = pr.set_index("ts").RRP.resample("1h").mean()                        # 5-min -> 小时均价
om = json.load(open(files[2])); tp = pd.Series(om["hourly"]["temperature_2m"], index=pd.to_datetime(om["hourly"]["time"]))
days = pd.date_range("2024-01-01", "2024-01-31")
res0, _, _ = C.resources_from_case("zhongwei", with_backup=True)
CH = float(sys.argv[sys.argv.index("--chiller")+1]) if "--chiller" in sys.argv else None   # 压力情景: 冷机额定=CH×IT【假设】
for r in res0:
    if CH and r["type"] == "dc": r["thermal"]["chiller_cap_mw_th"] = CH*r["cap_it_mw"]
P0 = {"id": "public_bench", "rule_id": "demo_ningxia", "resources": res0}
rule = C.get_rule("demo_ningxia")
def day(series, d): return series[d: d + pd.Timedelta(hours=23)].values.astype(float)
def with_temp(P, T):
    P = copy.deepcopy(P)
    for r in P["resources"]:
        if r["type"] == "dc": r["outdoor_temp_c"] = [float(x) for x in T]
    return P
def evaluate(P_act, plan, price):
    """在实际气温下执行计划: 超热安全容量的批处理被迫削减(=热违约/偏差)。"""
    g = np.array(plan["g"], float); viol = 0.0; vh = 0; itw = 0.0
    for r in P_act["resources"]:
        if r["type"] != "dc": continue
        it = np.array(plan["per"][r["id"]]["it_mw"]); cap = np.array([C._therm_cap(r, t) for t in range(H)])
        over = np.maximum(0, it - cap); over[over < 1e-3] = 0.0; viol += float(over.sum()); vh += int((over > 1e-6).sum())
        itw += float((it - over).sum()) - float(np.sum(r["interactive_mw"]))
        g = g - over*np.array([C._k(r, t) for t in range(H)])
    return dict(batch_served_mwh=itw, cost=float(np.dot(price, g)), energy=float(g.sum()), viol_mwh=viol, viol_h=vh, carbon_t=float(g.sum()*EF), g=g)
def myopic(P, price_act, hist24):
    """规则型短视策略: 只看当前价与过去24h实际价; 批处理在价≤过去24h中位数时满负荷, 否则仅保证剩余时间能完成;
    ESS 价≤P25 充, ≥P75 放。"""
    P = copy.deepcopy(P); out_g = np.zeros(H); per = {}
    dcs = [r for r in P["resources"] if r["type"] == "dc"]; ess = [r for r in P["resources"] if r["type"] in ("ess", "ups")]
    hist = list(hist24)
    rem = {r["id"]: r["batch_mwh"] for r in dcs}; soc = {e["id"]: e["soc0"]*e["energy_mwh"] for e in ess}
    for r in dcs: per[r["id"]] = {"it_mw": [0.0]*H}
    for t in range(H):
        med = np.median(hist[-24:]); q25, q75 = np.percentile(hist[-24:], [25, 75]); g = 0.0
        for r in dcs:
            room = [max(0.0, C._therm_cap(r, s) - r["interactive_mw"][s]) for s in range(H)]
            future = sum(room[t+1:]); need = max(0.0, rem[r["id"]] - future)
            b = min(room[t], rem[r["id"]]) if price_act[t] <= med else min(room[t], need)
            rem[r["id"]] -= b; it = r["interactive_mw"][t] + b; per[r["id"]]["it_mw"][t] = it; g += it*C._k(r, t)
        for e in ess:
            E = e["energy_mwh"]; fl = (e.get("reserve_frac") or rule["ups_reserve_floor_frac"]) if e["type"] == "ups" else e["soc_min"]
            if price_act[t] <= q25: x = min(e["power_mw"], (e["soc_max"]*E - soc[e["id"]])/e["eta"]); soc[e["id"]] += x*e["eta"]; g += x
            elif price_act[t] >= q75: x = min(e["power_mw"], (soc[e["id"]] - fl*E)*e["eta"]); soc[e["id"]] -= x/e["eta"]; g -= x
        out_g[t] = g; hist.append(price_act[t])
    return {"g": out_g.tolist(), "per": per}
def rolling(P_fc, P_act, f_price, a_price, f_temp, a_temp, da, no_thermal=False):
    plan = da
    for t0 in range(4, H, 4):
        pmix = f_price.copy(); pmix[t0:t0+4] = a_price[t0:t0+4]
        tmix = f_temp.copy(); tmix[t0:t0+4] = a_temp[t0:t0+4]
        Pm = with_temp(P_fc, tmix)
        new = C.optimize(Pm, pmix, target=da["g"], dev_pen=0.05*float(np.mean(np.abs(f_price))) , fix=plan, from_t=t0)
        if new.get("ok"): plan = new
    return plan
rows = []
orig_cap = C._therm_cap
for d in days:
    a_p = day(hp, d); f_p = day(hp, d - pd.Timedelta(days=1)); a_T = day(tp, d); f_T = day(tp, d - pd.Timedelta(days=1))
    hist = day(hp, d - pd.Timedelta(days=1))
    P_act = with_temp(P0, a_T); P_fc = with_temp(P0, f_T)
    S = {}
    S["naive"] = evaluate(P_act, C.optimize(P_act, a_p, baseline=True), a_p)
    da = C.optimize(P_fc, f_p); S["da_only"] = evaluate(P_act, da, a_p)
    roll = rolling(P_fc, P_act, f_p, a_p, f_T, a_T, da); S["da_id_rolling"] = evaluate(P_act, roll, a_p)
    S["myopic"] = evaluate(P_act, myopic(P_act, a_p, hist), a_p)
    C._therm_cap = lambda dc, t: dc["cap_it_mw"]       # 无热安全: 去掉气温相关冷量上限
    da_nt = C.optimize(P_fc, f_p); roll_nt = rolling(P_fc, P_act, f_p, a_p, f_T, a_T, da_nt)
    C._therm_cap = orig_cap
    S["da_id_no_thermal"] = evaluate(P_act, roll_nt, a_p)
    da_m = C.optimize(with_temp(P0, f_T + 2.0), f_p); roll_m = rolling(with_temp(P0, f_T + 2.0), P_act, f_p, a_p, f_T + 2.0, a_T, da_m)
    S["da_id_rolling_margin2K"] = evaluate(P_act, roll_m, a_p)
    S["oracle"] = evaluate(P_act, C.optimize(P_act, a_p), a_p)
    for k, v in S.items():
        dev = float(np.abs(v["g"] - np.array(da["g"])).sum()) if k in ("da_only", "da_id_rolling") else None
        rows.append(dict(day=str(d.date()), strategy=k, batch_served_mwh=v["batch_served_mwh"], cost_aud=v["cost"], energy_mwh=v["energy"], thermal_viol_mwh=v["viol_mwh"],
                         thermal_viol_h=v["viol_h"], carbon_t=v["carbon_t"], abs_dev_vs_da_mwh=dev,
                         price_mean=float(a_p.mean()), price_max=float(a_p.max()), tmax=float(a_T.max())))
df = pd.DataFrame(rows); df.to_csv(f"{OUT}/b3_market_aemo_{TAG}_daily.csv", index=False)
agg = df.groupby("strategy").agg(batch_served_mwh=("batch_served_mwh", "sum"), cost_aud=("cost_aud", "sum"), energy_mwh=("energy_mwh", "sum"), thermal_viol_mwh=("thermal_viol_mwh", "sum"),
                                 thermal_viol_h=("thermal_viol_h", "sum"), carbon_t=("carbon_t", "sum"), abs_dev_vs_da_mwh=("abs_dev_vs_da_mwh", "sum"))
agg["cost_per_mwh"] = agg.cost_aud/agg.energy_mwh
base = agg.loc["naive", "cost_aud"]; agg["saving_vs_naive_pct"] = (base - agg.cost_aud)/abs(base)*100
orc = agg.loc["oracle", "cost_aud"]; agg["regret_vs_oracle_pct"] = (agg.cost_aud - orc)/abs(orc)*100
print(agg.round(2).to_string())
crit = dict(rolling_le_da_only=bool(agg.loc["da_id_rolling", "cost_aud"] <= agg.loc["da_only", "cost_aud"] + 1e-6),
            da_le_naive=bool(agg.loc["da_only", "cost_aud"] <= base), oracle_is_lower_bound=bool((agg.drop(["da_id_no_thermal"]).cost_aud >= orc - 1e-3).all()),
            rolling_and_oracle_zero_thermal_viol=bool(agg.loc[["da_id_rolling", "oracle"], "thermal_viol_mwh"].max() < 1e-6),
            no_thermal_variant_violates=bool(agg.loc["da_id_no_thermal", "thermal_viol_mwh"] > 0) or bool(agg.loc["da_id_no_thermal", "cost_aud"] == agg.loc["da_id_rolling", "cost_aud"]),
            naive_batch_matches_oracle_within_0p1pct=bool(abs(agg.loc["naive", "batch_served_mwh"]/agg.loc["oracle", "batch_served_mwh"] - 1) < 0.001))
json.dump(dict(tag=TAG, chiller_cap_x_it=CH, sources={f.split("/")[-1]: sha(f) for f in files}, aggregate=agg.reset_index().to_dict("records"), criteria=crit,
               n_days=len(days)), open(f"{OUT}/b3_market_aemo_{TAG}.json", "w"), indent=1)
print(crit)
