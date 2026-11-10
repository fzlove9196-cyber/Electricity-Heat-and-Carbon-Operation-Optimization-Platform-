"""结果诊断（确定性，无需 LLM）：求解状态、PUE 合理范围、能量平衡残差、同时购售电/充放电、热安全裕度、
DR 缺额、余热末端温度、紧约束与影子价格、不可行原因（约束松弛试探）。每条 finding 带证据与修订建议。"""
from __future__ import annotations
import numpy as np

LV = {"error": 3, "warn": 2, "info": 1, "ok": 0}

def F(code, level, title, detail, evidence=None, suggest=None):
    return dict(code=code, level=level, title=title, detail=detail, evidence=evidence or {}, suggest=suggest)

def diagnose(run: dict) -> list:
    out = []
    if run["status"] != "optimal":
        out.append(F("SOLVER_FAIL" if run["status"] == "error" else "INFEASIBLE", "error", "模型不可行" if run["status"] == "infeasible" else "求解出错",
                     run.get("error", "")[:300], {"status": run["status"]},
                     dict(action="explain_infeasible", note="逐项松弛关键约束，定位导致不可行的假设")))
        return out
    r, sc, k = run["_r"], run["_sc"], run["kpis"]; df = r["df"]
    out.append(F("SOLVER_OK", "ok", "求解器状态正常", f"HiGHS optimal，{r['solver']['n_vars']} 变量 / {r['solver']['n_constraints']} 约束，gap {r['solver']['gap_pct']:.2g}%",
                 {"status": "optimal", "time_s": r["solver"]["time_s"]}))
    th = r.get("thermal")
    if th:
        D = th["dcs"]
        res = dict(热=max(x["thermal_balance_max_residual"] for x in D.values()), 电=max(x["elec_balance_max_residual"] for x in D.values()),
                   供热=(th.get("heat") or {}).get("balance_max_residual") or 0.0)
        bad = {a: b for a, b in res.items() if b is not None and b > 1e-4}
        out.append(F("BALANCE", "error" if bad else "ok", "能量平衡残差" + ("超限" if bad else "正常"),
                     "；".join(f"{a}平衡最大残差 {b:.2e}" for a, b in res.items()), {f"residual_{a}": float(b) for a, b in res.items()}))
        pmin, pmax, pav = k.get("pue_min", 0), k.get("pue_max", 0), k.get("pue_avg", 0)
        if pmin < 1.0: out.append(F("PUE_UNREAL", "error", "PUE < 1.0（物理上不可能）", f"最小 PUE={pmin}：检查热泵用电/余热收入是否被错误抵扣进 PUE", {"pue_min": pmin}))
        elif pmax > 1.8: out.append(F("PUE_HIGH", "warn", "PUE 偏高", f"最大 PUE={pmax}（>1.8），冷却系统接近能力边界", {"pue_max": pmax}))
        else: out.append(F("PUE_RANGE", "ok", "PUE 在合理范围", f"PUE {pmin}–{pmax}（均值 {pav}），符合 1.05–1.6 经验区间", {"pue_min": pmin, "pue_max": pmax}))
        if th["violations"]:
            out.append(F("THERMAL_VIOL", "error", "热安全违规", f"{len(th['violations'])} 处：{str(th['violations'][:3])[:200]}", {"n": len(th["violations"])}))
        mg = k.get("thermal_margin_k", 99)
        if mg <= 0.05:
            hrs = sorted({h for x in D.values() for h in (x.get("binding_hours") or [])})
            out.append(F("THERMAL_EDGE", "warn", "入口温度贴着允许上限运行（零裕度）",
                         f"最高入口温度 {k.get('tin_max_c')}°C = 允许上限，裕度 {mg} K；紧约束时段 {hrs[:12]}。优化把热惯性用尽，实际扰动下无安全余量",
                         {"tin_max_c": k.get("tin_max_c"), "margin_k": mg, "hours": hrs[:24]},
                         dict(action="stress_margin", note="建议增加 1–2 K 安全裕度或热浪加强压力测试")))
        elif mg < 2: out.append(F("THERMAL_TIGHT", "warn", "热安全裕度偏小", f"裕度 {mg} K < 2 K", {"margin_k": mg}))
        else: out.append(F("THERMAL_OK", "ok", "热安全满足", f"最高入口 {k.get('tin_max_c')}°C，裕度 {mg} K", {"margin_k": mg}))
    sim = []
    for g in range(len(r.get("gens", []))):   # 同一外网接口同时购电与反送 = 套利/建模漏洞（不同接口一购一送属正常的跨区输送）
        a, b = df.get(f"gen{g}_MW"), df.get(f"gen{g}_export_MW")
        if a is not None and b is not None:
            m_ = (a > 0.1) & (b > 0.1)
            if m_.any(): sim.append((g, df.hour[m_].tolist(), float(np.minimum(a[m_], b[m_]).max())))
    if sim: out.append(F("SIM_BUY_SELL", "warn", "同一外网接口同时购电与售电（疑似套利/建模漏洞）",
                         "；".join(f"接口 gen{g}：{len(h)} 小时，最大同时量 {x:.1f} MW" for g, h, x in sim), {"hours": sim[0][1][:12]}, dict(action="check_prices")))
    elif "grid_import_MW" in df: out.append(F("NO_ARBITRAGE", "ok", "无同一接口同时购售电", "各外网接口逐时购电与反送互斥（跨接口一购一送属跨区输送）", {}))
    for st in r.get("storage", []):
        c, d = df.get(f"{st}_ch"), df.get(f"{st}_dis")
        if c is not None and d is not None and ((c > 0.1) & (d > 0.1)).any():
            out.append(F("SIM_CH_DIS", "warn", f"储能 {st} 同时充放电", "LP 松弛下的同时充放（损耗被当作“消纳”手段），结果需复核", {"hours": df.hour[(c > 0.1) & (d > 0.1)].tolist()[:12]}))
    for e in r.get("dr") or []:
        if e["requested_mwh"] > 0 and e["delivered_mwh"] < 0.99*e["requested_mwh"]:
            out.append(F("DR_SHORTFALL", "warn", f"需求响应未足额：{e['name']}", f"请求 {e['requested_mwh']:.1f} MWh，实际 {e['delivered_mwh']:.1f} MWh（{100*e['delivered_mwh']/e['requested_mwh']:.0f}%）",
                         {"requested_mwh": e["requested_mwh"], "delivered_mwh": round(e["delivered_mwh"], 2)}, dict(action="find_firm_dr", note="二分搜索可保证的硬承诺量")))
        elif e["requested_mwh"] > 0:
            out.append(F("DR_OK", "ok", f"需求响应足额：{e['name']}", f"{e['delivered_mwh']:.1f}/{e['requested_mwh']:.1f} MWh", {}))
    if k.get("heat_verdict"):
        lv = "ok" if k["heat_verdict"] == "可行" else "warn"
        out.append(F("HEAT_TERMINAL", lv, f"余热供暖末端判定：{k['heat_verdict']}",
                     f"末端温度裕度 {k.get('terminal_margin_k')} K，调峰补热 {k.get('heat_boost_mwh')} MWh_th，热成本 {k.get('heat_cost_cny_gj')} 元/GJ",
                     {"terminal_margin_k": k.get("terminal_margin_k"), "boost_mwh": k.get("heat_boost_mwh")},
                     None if lv == "ok" else dict(action="compare_terminals", note="余热品位不足：比较低温末端或高温热泵")))
    if k.get("heat_delivered_mwh") and sc.heat_network is not None:
        dem = float(np.sum(sc.heat_network.demand_mw_th))
        if dem > 0 and k["heat_delivered_mwh"] >= 0.98*dem*(1 - 0):
            out.append(F("HEAT_DEMAND_CAP", "info", "供热量受热网需求上限约束", f"供热 {k['heat_delivered_mwh']:.0f} MWh_th ≈ 热网可接纳 {dem:.0f} MWh_th：扩大热泵容量无额外收益", {"demand_mwh": round(dem, 1)}))
    for b in (r.get("binding") or [])[:3]:
        out.append(F("BINDING", "info", f"紧约束：{b['group']}", f"{b['n_binding']}/{b['n']} 条约束起作用，Σ|影子价格|={b['dual_abs_sum']:.0f}，最大 {b['dual_max']}（元/单位右端）",
                     {"group": b["group"], "dual_max": b["dual_max"], "n_binding": b["n_binding"]}))
    if abs(k.get("cost_cny", 0)) > 5e7: out.append(F("COST_UNREAL", "warn", "日成本量级异常", f"{k['cost_cny']:.3g} 元/日，检查单位（kWh/MWh）", {}))
    return out

def worst(findings):
    return max((LV[f["level"]] for f in findings), default=0)

RELAX = [("dr_soft", "DR 改为尽力响应（非硬约束）", {"dr_events.*.mandatory": False}),
         ("t_allow", "入口温度允许上限 +2 K", {"data_centers.*.thermal.t_allow_max_c": {"op": "add", "value": 2.0}}),
         ("chiller", "冷机装机 +20%", {"data_centers.*.thermal.chiller_cap_mw_th": {"op": "mul", "value": 1.2}}),
         ("ramp", "温变率上限放宽到 10 K/h", {"data_centers.*.thermal.ramp_max_k_h": 10.0}),
         ("cooler", "室外温度 −2 K（热浪减弱）", {"outdoor_temp_c": {"op": "add", "value": -2.0}, "outdoor_temp_profiles.*": {"op": "add", "value": -2.0}})]

def explain_infeasible(base, mods: dict) -> dict:
    """确定性不可行原因分析：在失败模型上逐项松弛，看哪一项恢复可行（IIS 的工程近似）。"""
    from .experiments import apply_mods
    from ..tools import sdco_engine as eng
    tests = []
    for key, name, rel in RELAX:
        m2 = dict(mods); m2.update(rel)
        try:
            sc = apply_mods(base, m2)
        except Exception as e:
            tests.append(dict(key=key, relax=name, feasible=None, note=f"不适用：{e}")); continue
        try:
            r = eng.solve(sc, True); tests.append(dict(key=key, relax=name, feasible=True, cost_cny=round(r["cost_cny"], 1),
                                                     dr_delivered=round(sum(e["delivered_mwh"] for e in r.get("dr") or []), 2)))
        except Exception as e: tests.append(dict(key=key, relax=name, feasible=False))
    ok = [t for t in tests if t["feasible"]]
    cause = ("DR 硬承诺量超出热浪日冷却/热惯性可支撑的削减能力" if any(t["key"] == "dr_soft" for t in ok) else
             "热安全约束（入口温度/冷量）过紧" if ok else "多重约束共同作用，单项松弛不能恢复可行")
    return dict(tests=tests, restoring=[t["relax"] for t in ok], cause=cause)

def find_firm_dr(base, mods: dict, lo=0.0, hi=None, iters=7) -> dict:
    """二分搜索：DR 设为硬约束时可保证的最大削峰功率 MW（确定性求解）。"""
    from .experiments import apply_mods
    from ..tools import sdco_engine as eng
    sc0 = apply_mods(base, mods); hi = hi if hi is not None else max(e.request_mw for e in sc0.dr_events)
    trace = []
    for _ in range(iters):
        mid = round((lo + hi)/2, 2)
        m2 = dict(mods); m2.update({"dr_events.0.mandatory": True, "dr_events.0.request_mw": mid})
        try: eng.solve(apply_mods(base, m2), True); lo = mid; trace.append((mid, True))
        except Exception: hi = mid; trace.append((mid, False))
    return dict(firm_mw=lo, upper_mw=hi, trace=trace)
