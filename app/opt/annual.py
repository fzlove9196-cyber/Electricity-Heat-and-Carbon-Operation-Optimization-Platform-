"""全年 8760h 运行 + 容量规划 稀疏 LP（scipy.sparse + HiGHS，直接组装矩阵，不经 Pyomo）。

时间结构：365 个“日”映射到 K 个代表日（K=365 即完整 8760h，逐日独立且精确）。
储能（电池 / 各 DC 蓄冷罐 / 热网蓄热）采用 Kotzur 等(2018) 的“日内相对 SOC + 日间 SOC 链接”：
  s[c,h] 日内相对荷电；S[d] 第 d 天起始荷电，S[d+1]=(1−loss)^24·S[d]+Δ[c(d)]（循环）；
  S[d]+max_h s[c(d),h] ≤ SOCmax·E，S[d]+min_h s[c(d),h] ≥ SOCmin·E —— 在聚类后仍保持全年时序（季节性储能也可表达）。
与日内 Pyomo 模型（sdco_engine，含 RC 热惯性/潮流/N-1）不同，年度模型为“铜板 + 准稳态冷却”：
  逐时冷量平衡 qfree+qch−tes_c+tes_d+hr = (IT)(1+other)，不含机房热容与网络潮流（这些由日内模型校核）。
"""
import time, copy
import numpy as np
import scipy.sparse as sp
from scipy.optimize import linprog

CAPEX = {  # 【假设】2024–2025 中国市场量级，元/单位；life 年；om 年运维占投资比例
    "wind":  dict(cn="风电", unit="MW", cny=4.0e6, life=20, om=0.02),
    "pv":    dict(cn="光伏", unit="MW", cny=3.0e6, life=25, om=0.015),
    "bat_e": dict(cn="电池能量", unit="MWh", cny=0.8e6, life=12, om=0.02),
    "bat_p": dict(cn="电池功率(PCS)", unit="MW", cny=0.2e6, life=12, om=0.02),
    "tes":   dict(cn="蓄冷罐(虚拟储冷)", unit="MWh_th", cny=0.15e6, life=20, om=0.01),
    "hs":    dict(cn="蓄热罐(虚拟储热)", unit="MWh_th", cny=0.10e6, life=20, om=0.01),
    "chiller": dict(cn="冷机增容", unit="MW_th", cny=1.0e6, life=20, om=0.02),
    "hp":    dict(cn="余热热泵", unit="MW_th", cny=1.5e6, life=20, om=0.02),
}
RATE = 0.06

def crf(life, r=RATE): return r*(1 + r)**life/((1 + r)**life - 1)
def ann(key): c = CAPEX[key]; return c["cny"]*(crf(c["life"]) + c["om"])

# ------------------------------------------------------------------ 案例（从预置场景 + 全年 ERA5）
SITE_OF = [("ulanqab", "ulanqab", "mengxi", 1.0), ("helinger", "hohhot_helinger", "mengxi", 1.0), ("zhongwei", "zhongwei", "ningxia", 1.0),
           ("shaoguan", "shaoguan", "guangdong", 1.0), ("odense", "odense", "denmark", 1.0)]

def site_for(preset):
    for k, site, reg, _ in SITE_OF:
        if preset.startswith(k): return site, reg
    raise ValueError(f"预置 {preset} 未配置全年气象站点（SITE_OF）")

def build_case(preset, year=2024, wind_scale=1.0, carbon_basis="marginal", carbon_price=None):
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "cases", "common"))
    import climate as CM
    from ..scenario import load_preset, region_of
    from . import carbon as CB
    sc = load_preset(preset); site, reg = site_for(preset)
    raw = CM.fetch(site, year); D = CM.days(raw); nd = min(365, D["T"].shape[0])
    f = lambda a: np.nan_to_num(np.asarray(a[:nd], float).reshape(-1), nan=float(np.nanmean(a)))
    T, RH, W, G = f(D["T"]), f(D["RH"])/100, f(D["W"]), f(D["G"])
    wcf = np.clip(CM.wind_cf(W)*wind_scale, 0, 1); pcf = CM.pv_cf(G)
    regs = [region_of(sc, d.bus) for d in sc.data_centers]; main = max(set(regs), key=regs.count)
    dcs = [d for d, r in zip(sc.data_centers, regs) if r == main]
    wind0 = pv0 = 0.0; ppa = 0.0
    for p in sc.pv:
        if region_of(sc, p.bus) != main: continue
        k = p.kind or ("wind" if p.profile and min(p.profile[:5] + p.profile[-3:]) > 0.02 else "pv")
        if k == "wind": wind0 += p.cap_mw
        else: pv0 += p.cap_mw
        ppa += (p.ppa_price_cny_kwh or 0)*1000*p.cap_mw*(wcf if k == "wind" else pcf).sum()
    sto = [s for s in sc.storage if region_of(sc, s.bus) == main]
    price = (np.asarray(sc.price_cny_kwh, float)*1000 + sc.grid_markup_cny_mwh); dem_charge = 0.0
    hydro = []
    if sc.network is not None:
        eg = [e for e in sc.network.ext_grids if region_of(sc, e.bus) == main]
        if eg and eg[0].price_cny_kwh: price = np.asarray(eg[0].price_cny_kwh, float)*1000; dem_charge = (eg[0].demand_charge_cny_mw_day or 0)*365
        for g in sc.network.gens:
            if getattr(g, "energy_mwh_day", None): hydro.append(dict(name=g.name, pmax=g.pmax_mw, eday=g.energy_mwh_day, cost=g.cost_cny_mwh or 0.0))
    price = np.tile(price, nd)
    cm = CB.marginal(reg, T, wcf, pcf)
    ef = cm["mef"] if carbon_basis == "marginal" else np.full(T.size, cm["avg"])
    return dict(preset=preset, site=site, region=reg, year=year, nd=nd, T=T, RH=RH, wind_cf=wcf, pv_cf=pcf, price=price, ef=ef,
                ef_avg=cm["avg"], ef_marg=cm["mef"], carbon_basis=carbon_basis, carbon_stats=cm["stats"],
                carbon_price=sc.carbon_price_cny_t if carbon_price is None else carbon_price,
                dcs=[copy.deepcopy(d) for d in dcs], wind0=wind0, pv0=pv0, ppa_const=ppa, storage=[s.model_copy() for s in sto],
                hydro=hydro, dem_charge=dem_charge, hn=copy.deepcopy(sc.heat_network), region_name=main,
                source=f"Open-Meteo ERA5 {site} {year} 全年逐时（{raw.get('_url', '')[:120]}…）", wind_scale=wind_scale)

# ------------------------------------------------------------------ 代表日聚类
def cluster(case, k, how="medoid"):
    nd = case["nd"]
    if k is None or k >= nd: return np.arange(nd), np.ones(nd), np.arange(nd)
    from sklearn.cluster import KMeans
    F = np.hstack([(case[x].reshape(nd, 24) - case[x].mean())/(case[x].std() + 1e-9) for x in ("T", "wind_cf", "pv_cf", "ef")])
    km = KMeans(n_clusters=k, n_init=10, random_state=0).fit(F)
    reps = np.array([np.where(km.labels_ == c)[0][np.argmin(((F[km.labels_ == c] - km.cluster_centers_[c])**2).sum(1))] for c in range(k)])
    w = np.bincount(km.labels_, minlength=k).astype(float)
    if how == "medoid+ext":   # 追加极端日（最低风电日、最高气温日）为单独代表日
        ext = {int(np.argmin(case["wind_cf"].reshape(nd, 24).mean(1))), int(np.argmax(case["T"].reshape(nd, 24).max(1)))} - set(reps.tolist())
        lab = km.labels_.copy()
        for e in ext: w[lab[e]] -= 1; lab[e] = len(reps); reps = np.append(reps, e); w = np.append(w, 1.0)
        return reps, w, lab
    return reps, w, km.labels_

# ------------------------------------------------------------------ 稀疏 LP 组装器
class LP:
    def __init__(s): s.n = 0; s.lb = []; s.ub = []; s.names = {}; s.R = {"le": [[], [], [], [], []], "eq": [[], [], [], [], []]}; s.m = {"le": 0, "eq": 0}
    def var(s, name, size=1, lb=0.0, ub=np.inf):
        idx = np.arange(s.n, s.n + size); s.n += size
        s.lb.append(np.broadcast_to(np.asarray(lb, float), (size,)).copy()); s.ub.append(np.broadcast_to(np.asarray(ub, float), (size,)).copy())
        s.names[name] = idx; return idx
    def row(s, terms, sense, rhs, group):
        rhs = np.atleast_1d(np.asarray(rhs, float)); n = rhs.size; sg = -1.0 if sense == "ge" else 1.0; key = "eq" if sense == "eq" else "le"
        r0 = s.m[key]; rows = np.arange(r0, r0 + n); I, J, V, B, Gp = s.R[key]
        for idx, coef in terms:
            idx = np.broadcast_to(np.asarray(idx), (n,)); cf = np.broadcast_to(np.asarray(coef, float), (n,))
            I.append(rows); J.append(idx); V.append(sg*cf)
        B.append(sg*rhs); Gp.append((group, r0, r0 + n)); s.m[key] += n
        return (key, r0, r0 + n)
    def bounds(s): return np.concatenate(s.lb), np.concatenate(s.ub)
    def mat(s, key, extra=()):
        I, J, V, B, _ = s.R[key]; m = s.m[key]
        I = list(I); J = list(J); V = list(V); B = list(B)
        for k, (vec, rhs) in enumerate(extra):
            nz = np.nonzero(vec)[0]; I.append(np.full(nz.size, m + k)); J.append(nz); V.append(vec[nz]); B.append(np.array([rhs]))
        mm = m + len(extra)
        if mm == 0: return None, None
        A = sp.csr_matrix((np.concatenate(V) if V else [], (np.concatenate(I) if I else [], np.concatenate(J) if J else [])), shape=(mm, s.n))
        return A, np.concatenate(B)

# ------------------------------------------------------------------ 年度模型
def build(case, k=None, plan=None, need_margin=False, how="medoid", fixed=None):
    """plan: dict 资产 -> 最大新增量（None/缺省=不规划，只运行）。返回模型对象 M（含 LP、目标向量、指标函数）。"""
    from ..tools import cooling as CL, heat_grade as HG
    plan = plan or {}; t0 = time.time()
    reps, wday, labels = cluster(case, k, how); K = len(reps); N = 24*K
    hsel = (reps[:, None]*24 + np.arange(24)[None, :]).reshape(-1)
    T, RH = case["T"][hsel], case["RH"][hsel]; wcf, pcf = case["wind_cf"][hsel], case["pv_cf"][hsel]
    if how == "centroid" and K < case["nd"]:   # 簇均值曲线（保能量，但抹平波动）
        nd = case["nd"]; cm = lambda a: np.vstack([a.reshape(nd, 24)[labels == c].mean(0) for c in range(K)]).reshape(-1)
        T, RH, wcf, pcf = cm(case["T"]), cm(case["RH"]), cm(case["wind_cf"]), cm(case["pv_cf"])
    price, ef = case["price"][hsel], case["ef"][hsel]
    if how == "centroid" and K < case["nd"]: ef = cm(case["ef"])
    Wt = np.repeat(wday, 24)
    lp = LP(); obj = {}; OBJ = lambda: np.zeros(0)
    cost_terms, carb_terms, grid_terms, capex_terms, invest_terms = [], [], [], [], []   # (idx, coef)
    const_cost = case["ppa_const"]
    def capvar(key, ub_add, scale=1.0, name=None):
        nm = name or f"d_{key}"
        if fixed is not None:
            if nm[2:] not in fixed: return None
            v = lp.var(nm, 1, fixed[nm[2:]], fixed[nm[2:]]); capex_terms.append((v, ann(key))); invest_terms.append((v, CAPEX[key]["cny"])); return v
        if not plan.get(key): return None
        v = lp.var(nm, 1, 0, plan[key]*scale); capex_terms.append((v, ann(key))); invest_terms.append((v, CAPEX[key]["cny"])); return v
    # ---- 电力侧
    g = lp.var("grid", N); grid_terms.append((g, Wt))
    cost_terms.append((g, Wt*price)); carb_terms.append((g, Wt*ef))
    Pk = lp.var("peak", 1)
    if case.get("dem_charge"): cost_terms.append((Pk, np.array([case["dem_charge"]])))
    lp.row([(g, 1.0), (Pk, -1.0)], "le", np.zeros(N), "峰值购电定义")
    dW = capvar("wind", None); dPV = capvar("pv", None)
    w = lp.var("wind", N); pv = lp.var("pv", N)
    lp.row([(w, 1.0)] + ([(dW, -wcf)] if dW is not None else []), "le", wcf*case["wind0"], "风电可发上限")
    lp.row([(pv, 1.0)] + ([(dPV, -pcf)] if dPV is not None else []), "le", pcf*case["pv0"], "光伏可发上限")
    supply = [(g, 1.0), (w, 1.0), (pv, 1.0)]; demand = []
    hy = []
    for hd in case["hydro"]:
        v = lp.var(f"hydro_{hd['name']}", N, 0, hd["pmax"]); hy.append(v); supply.append((v, 1.0)); cost_terms.append((v, Wt*hd["cost"]))
        lp.row([(v.reshape(K, 24)[:, h], 1.0) for h in range(24)], "le", np.full(K, hd["eday"]), "水电日电量")
    links = []   # 储能块（用于日间链接）
    def storage(tag, ch, dis, eta_c, eta_d, loss, E0, dE, smin, smax, cn):
        s = lp.var(f"{tag}_rel", N, -np.inf, np.inf); S = lp.var(f"{tag}_S", case["nd"], 0, np.inf)
        mx = lp.var(f"{tag}_mx", K, -np.inf, np.inf); mn = lp.var(f"{tag}_mn", K, -np.inf, np.inf)
        sh = s.reshape(K, 24); chh = ch.reshape(K, 24); dh = dis.reshape(K, 24)
        lp.row([(sh[:, 0], 1.0), (chh[:, 0], -eta_c), (dh[:, 0], 1/eta_d)], "eq", np.zeros(K), f"{cn}日内荷电")
        for h in range(1, 24):
            lp.row([(sh[:, h], 1.0), (sh[:, h - 1], -(1 - loss)), (chh[:, h], -eta_c), (dh[:, h], 1/eta_d)], "eq", np.zeros(K), f"{cn}日内荷电")
        lp.row([(s, 1.0), (np.repeat(mx, 24), -1.0)], "le", np.zeros(N), f"{cn}日内最大"); lp.row([(s, 1.0), (np.repeat(mn, 24), -1.0)], "ge", np.zeros(N), f"{cn}日内最小")
        nd = case["nd"]; d = np.arange(nd); nxt = (d + 1) % nd; cd = labels if K < nd else d
        lp.row([(S[nxt], 1.0), (S[d], -(1 - loss)**24), (sh[cd, 23], -1.0)], "eq", np.zeros(nd), f"{cn}日间链接")
        tE = [(dE, -smax)] if dE is not None else []; tEm = [(dE, -smin)] if dE is not None else []
        lp.row([(S, 1.0), (mx[cd], 1.0)] + tE, "le", np.full(nd, smax*E0), f"{cn}容量上限")
        lp.row([(S, 1.0), (mn[cd], 1.0)] + tEm, "ge", np.full(nd, smin*E0), f"{cn}容量下限")
        links.append(tag)
    # 电池（合并既有 + 新增）
    E0 = sum(s.energy_mwh for s in case["storage"]); P0 = sum(s.power_mw for s in case["storage"])
    dBE = capvar("bat_e", None); dBP = capvar("bat_p", None)
    if E0 > 0 or dBE is not None:
        bc = lp.var("bat_ch", N); bd = lp.var("bat_dis", N)
        for v in (bc, bd): lp.row([(v, 1.0)] + ([(dBP, -1.0)] if dBP is not None else []), "le", np.full(N, P0), "电池功率上限")
        if dBE is not None and dBP is not None: lp.row([(dBP, 1.0), (dBE, -1.0)], "le", 0.0, "电池时长≥1h")
        storage("bat", bc, bd, 0.95, 0.95, 0.0002, E0, dBE, 0.1, 0.95, "电池"); supply.append((bd, 1.0)); demand.append((bc, 1.0))
    # ---- 数据中心
    load_const = 0.0; it_const = 0.0; dce_terms = []; e_const = np.zeros(N)
    DCI = []; it_terms = []; hp_heat = []; need_rows = []
    for j, dc in enumerate(case["dcs"]):
        th = dc.thermal; inter = np.tile(np.asarray(dc.interactive_mw, float), K)
        hc = CL.hourly(th, T, RH); cop, ff, fcop = hc["cop"], hc["ff"], hc["free_cop"]
        n1 = (th.chiller_units - 1)/th.chiller_units if th.redundancy_n1 else 1.0
        bt = lp.var(f"batch_{j}", N, 0, np.maximum(dc.cap_it_mw - inter, 0))
        lp.row([(bt.reshape(K, 24)[:, h], 1.0) for h in range(24)], "eq", np.full(K, dc.batch_mwh), f"{dc.name} 批处理日电量")
        qf = lp.var(f"qfree_{j}", N, 0, th.free_cap_mw_th*ff); qc = lp.var(f"qch_{j}", N)
        dC = capvar("chiller", None, dc.cap_it_mw/max(1, sum(d.cap_it_mw for d in case["dcs"])), f"d_chiller_{j}")
        lp.row([(qc, 1.0)] + ([(dC, -1.0)] if dC is not None else []), "le", np.full(N, th.chiller_cap_mw_th*n1), f"{dc.name} 冷机可用冷量(N+1)")
        bal = [(qf, 1.0), (qc, 1.0)]; rhs = inter*(1 + th.other_frac); e_terms = [(qc, 1/cop + th.tower_pump_kw_per_kw), (qf, 1/fcop), (bt, 1 + th.other_frac)]
        dT_ = capvar("tes", None, 1.0, f"d_tes_{j}")
        if th.tes_mwh_th > 0 or dT_ is not None:
            tc = lp.var(f"tes_c_{j}", N); td = lp.var(f"tes_d_{j}", N)
            pmax = th.tes_p_mw_th if th.tes_mwh_th > 0 else 0.0
            for v in (tc, td): lp.row([(v, 1.0)] + ([(dT_, -0.25)] if dT_ is not None else []), "le", np.full(N, pmax), f"{dc.name} 蓄冷功率")
            storage(f"tes{j}", tc, td, 1.0, 1.0, th.tes_loss_h, th.tes_mwh_th, dT_, 0.0, 1.0, f"{dc.name} 蓄冷")
            bal += [(tc, -1.0), (td, 1.0)]
        hr = None
        if case["hn"] is not None:
            hn = case["hn"]; dH = capvar("hp", None, 1.0, f"d_hp_{j}")
            if th.hp_cap_mw_th > 0 or dH is not None:
                tsrc = CL.source_temp(th)
                if hn.terminal_type:
                    hg = HG.hourly(hn, tsrc, T); hcop = np.clip(hg["cop"], 1.3, 40)
                else: hcop = np.full(N, th.hp_cop)
                hr = lp.var(f"hr_{j}", N); bal.append((hr, 1.0)); e_terms.append((hr, 1/(hcop - 1)))
                lp.row([(hr, 1.0), (bt, -th.hr_max_frac*(1 + th.other_frac))], "le", th.hr_max_frac*inter*(1 + th.other_frac), f"{dc.name} 可回收余热")
                lp.row([(hr, hcop/(hcop - 1))] + ([(dH, -1.0)] if dH is not None else []), "le", np.full(N, th.hp_cap_mw_th), f"{dc.name} 热泵容量")
                hp_heat.append((hr, hcop/(hcop - 1)))
        lp.row(bal + [(bt, -(1 + th.other_frac))], "eq", rhs, f"{dc.name} 冷量平衡")
        for idx, cf in e_terms: demand.append((idx, cf)); dce_terms.append((idx, Wt*cf))
        it_const += float((inter*Wt).sum()) + dc.batch_mwh*float(wday.sum())
        e_const += inter*(1 + th.other_frac)
        load_const += float((inter*(1 + th.other_frac)*Wt).sum())
        DCI.append(dict(name=dc.name, inter=inter, bt=bt, qf=qf, qc=qc, e_terms=e_terms, cap=dc.cap_it_mw, other=th.other_frac,
                        need=dc.cap_it_mw*(1 + th.other_frac) - th.free_cap_mw_th*ff, cav=th.chiller_cap_mw_th*n1, dC=dC, mode=th.cooling_mode or "generic"))
    # 热安全裕度 m：冷机可用冷量 ≥ (1+m)×（满载 IT 发热 − 可用自然冷量），逐时
    mvar = None
    if need_margin:
        mvar = lp.var("margin", 1, 0, 5.0)
        for di in DCI:
            nd_ = np.maximum(di["need"], 0); sel = nd_ > 1e-6
            if sel.any(): lp.row([(mvar, -nd_[sel])] + ([(di["dC"], 1.0)] if di["dC"] is not None else []), "ge", nd_[sel] - di["cav"], f"{di['name']} 热安全裕度")
    # ---- 热网
    hd = None
    if hp_heat:
        hn = case["hn"]
        if hn.design_load_mw_th > 0: dem = HG.degree_hour_demand(hn, T)
        else:
            h2 = copy.deepcopy(hn); h2.design_load_mw_th = max(hn.demand_mw_th) or 0; dem = HG.degree_hour_demand(h2, T)
        loss = HG.pipe(hn)[1] if hn.terminal_type else hn.pipe_loss
        hd = lp.var("heat_del", N, 0, dem); bal = [(idx, (1 - loss)*cf) for idx, cf in hp_heat] + [(hd, -1.0)]
        dHS = capvar("hs", None)
        if hn.storage_mwh_th > 0 or dHS is not None:
            hc_ = lp.var("hs_c", N); hdis = lp.var("hs_d", N)
            for v in (hc_, hdis): lp.row([(v, 1.0)] + ([(dHS, -0.25)] if dHS is not None else []), "le", np.full(N, hn.storage_p_mw_th), "蓄热功率")
            storage("hs", hc_, hdis, 1.0, 1.0, hn.storage_loss_h, hn.storage_mwh_th, dHS, 0.0, 1.0, "热网蓄热"); bal += [(hc_, -1.0), (hdis, 1.0)]
        lp.row(bal, "ge", np.zeros(N), "热网热平衡(可弃热)")
        cost_terms.append((hd, -Wt*hn.price_cny_mwh_th)); carb_terms.append((hd, -Wt*hn.boiler_ef_t_mwh_th))
    # ---- 功率平衡
    lp.row(supply + [(i, -c) for i, c in demand], "ge", e_const, "电力平衡")
    # 目标向量
    def vec(terms):
        v = np.zeros(lp.n)
        for idx, cf in terms: np.add.at(v, np.asarray(idx).reshape(-1), np.broadcast_to(np.asarray(cf, float), np.asarray(idx).shape).reshape(-1))
        return v
    carbon = vec(carb_terms); energy = vec(cost_terms)
    load_terms = [(i, Wt*c) for i, c in demand]
    M = dict(lp=lp, case=case, K=K, N=N, Wt=Wt, reps=reps, wday=wday, labels=labels, DCI=DCI, hd=hd, g=g, w=w, pv=pv, Pk=Pk, mvar=mvar,
             vec=dict(energy=energy, capex=vec(capex_terms), carbon=carbon, peak=vec([(Pk, 1.0)]), grid=vec(grid_terms),
                      margin=vec([(mvar, -1.0)]) if mvar is not None else None, load=vec(load_terms), invest=vec(invest_terms), dce=vec(dce_terms)),
             it_const=it_const,
             const_cost=const_cost, load_const=load_const, build_s=time.time() - t0, plan=plan, T=T, price=price, ef=ef)
    return M

def objective_vec(M, key):
    V = M["vec"]; cp = M["case"]["carbon_price"]
    if key in ("cost", "npv"): return V["energy"] + V["capex"] + cp*V["carbon"]
    if key == "carbon": return V["carbon"]
    if key == "peak": return V["peak"]
    if key == "green": return V["grid"]
    if key == "thermal_margin":
        if V["margin"] is None: raise ValueError("热安全裕度需 need_margin=True")
        return V["margin"]
    raise KeyError(key)

def obj_value(M, key, x):
    v = float(objective_vec(M, key) @ x)
    return v + (M["const_cost"] if key in ("cost", "npv") else 0.0)

def solve(M, cvec, extra=()):
    """extra: [(vec, rhs, group)] 追加 ≤ 行（ε 约束 / 回收期 / 绿电等）。返回 dict(x, status, duals, time)。"""
    lp = M["lp"]; t0 = time.time(); lb, ub = lp.bounds()
    Aub, bub = lp.mat("le", [(v, r) for v, r, _ in extra]); Aeq, beq = lp.mat("eq")
    res = linprog(cvec, A_ub=Aub, b_ub=bub, A_eq=Aeq, b_eq=beq, bounds=np.column_stack([lb, ub]), method="highs")
    out = dict(status="optimal" if res.status == 0 else res.message, time=time.time() - t0, x=res.x if res.status == 0 else None)
    if res.status == 0:
        du = res.ineqlin.marginals; groups = {}
        for gname, a, b in lp.R["le"][4]:
            groups[gname] = groups.get(gname, 0.0) + float(np.abs(du[a:b]).sum())
        out["groups"] = {k: v for k, v in sorted(groups.items(), key=lambda z: -z[1]) if v > 1e-6}
        m = lp.m["le"]; out["extra_duals"] = [float(du[m + i]) for i in range(len(extra))]
        dq = res.eqlin.marginals if Aeq is not None else []
        for gname, a, b in lp.R["eq"][4]:
            v = float(np.abs(dq[a:b]).sum()) if len(dq) else 0
            if v > 1e-6: out["groups"][gname] = out["groups"].get(gname, 0) + v
        out["nvar"], out["nrow"] = lp.n, lp.m["le"] + lp.m["eq"] + len(extra)
    return out

def kpis(M, x):
    """全年指标（直接由 8760h/代表日加权解计算）。"""
    V = M["vec"]; lp = M["lp"]; case = M["case"]; Wt = M["Wt"]
    grid = float(V["grid"] @ x); load = float(V["load"] @ x) + M["load_const"]
    it = sum(float(((di["inter"] + x[di["bt"]])*Wt).sum()) for di in M["DCI"])
    dc_e = 0.0
    for di in M["DCI"]:
        for idx, cf in di["e_terms"]: dc_e += float((x[idx]*np.broadcast_to(cf, (M["N"],))*Wt).sum())
        dc_e += float((di["inter"]*(1 + di["other"])*Wt).sum())
    heat = float((x[M["hd"]]*Wt).sum()) if M["hd"] is not None else 0.0
    gi = x[M["g"]]; e_marg = float((gi*case["ef_marg"][(M["reps"][:, None]*24 + np.arange(24)).reshape(-1)]*Wt).sum()); e_avg = grid*case["ef_avg"]
    caps = {}
    for nm, idx in lp.names.items():
        if nm.startswith("d_") and idx.size == 1 and x[idx[0]] > 1e-3: caps[nm[2:]] = round(float(x[idx[0]]), 2)
    capex_ann = float(V["capex"] @ x); invest = 0.0
    for nm, v in caps.items():
        key = nm.split("_")[0] if not nm.startswith("bat") else nm
        key = {"chiller": "chiller", "tes": "tes", "hp": "hp"}.get(key, key)
        if key in CAPEX: invest += v*CAPEX[key]["cny"]
    wind_gen = float((x[M["w"]]*Wt).sum()); pv_gen = float((x[M["pv"]]*Wt).sum())
    cp = case["carbon_price"]; carbon = float(V["carbon"] @ x)
    return dict(cost_total=obj_value(M, "cost", x), energy_cost=float(V["energy"] @ x) + M["const_cost"], capex_ann=capex_ann, invest=invest,
                carbon_cost=cp*carbon, carbon_net_t=carbon, emis_marg_t=e_marg, emis_avg_t=e_avg, grid_mwh=grid, load_mwh=load,
                green_share=1 - grid/max(load, 1e-9), it_mwh=it, pue=dc_e/max(it, 1e-9), heat_mwh=heat, peak_mw=float(x[M["Pk"][0]]),
                wind_used_mwh=wind_gen, pv_used_mwh=pv_gen, margin=float(x[M["mvar"][0]]) if M["mvar"] is not None else None, caps=caps)

# ------------------------------------------------------------------ HiGHS 会话：一次组装，多次热启动（ε-约束扫描/换目标只改成本与行界）
class Session:
    def __init__(s, M, extra_vecs, time_limit=900):
        import highspy
        lp = M["lp"]; s.M = M; lb, ub = lp.bounds()
        Aub, bub = lp.mat("le", [(v, np.inf) for v in extra_vecs]); Aeq, beq = lp.mat("eq")
        A_ = sp.vstack([Aub, Aeq]).tocsc(); s.m_le = lp.m["le"]; s.nx = len(extra_vecs)
        rl = np.concatenate([np.full(Aub.shape[0], -np.inf), beq]); ru = np.concatenate([bub, beq])
        h = highspy.Highs(); h.setOptionValue("output_flag", False); h.setOptionValue("time_limit", float(time_limit))
        L = highspy.HighsLp(); L.num_col_ = lp.n; L.num_row_ = A_.shape[0]
        L.col_cost_ = np.zeros(lp.n); L.col_lower_ = lb; L.col_upper_ = np.where(np.isinf(ub), highspy.kHighsInf, ub)
        L.col_lower_ = np.where(np.isinf(lb), -highspy.kHighsInf, lb)
        L.row_lower_ = np.where(np.isinf(rl), -highspy.kHighsInf, rl); L.row_upper_ = np.where(np.isinf(ru), highspy.kHighsInf, ru)
        L.a_matrix_.format_ = highspy.MatrixFormat.kColwise; L.a_matrix_.start_ = A_.indptr; L.a_matrix_.index_ = A_.indices; L.a_matrix_.value_ = A_.data
        h.passModel(L); s.h = h; s.inf = highspy.kHighsInf; s.n = lp.n; s.first = True
    def solve(s, cvec, extra_rhs):
        """extra_rhs: 长度 = extra_vecs，None=不启用该行。返回与 solve() 相同结构。"""
        import highspy
        t0 = time.time(); h = s.h
        h.changeColsCost(s.n, np.arange(s.n, dtype=np.int32), np.asarray(cvec, float))
        if s.nx:
            rows = np.arange(s.m_le, s.m_le + s.nx, dtype=np.int32)
            up = np.array([s.inf if v is None else float(v) for v in extra_rhs]); h.changeRowsBounds(s.nx, rows, np.full(s.nx, -s.inf), up)
        if not s.first: h.setOptionValue("presolve", "off")
        h.run(); s.first = False
        st = h.getModelStatus()
        if st != highspy.HighsModelStatus.kOptimal:
            h.setOptionValue("presolve", "on"); h.clearSolver(); h.run(); st = h.getModelStatus()
        out = dict(status="optimal" if st == highspy.HighsModelStatus.kOptimal else h.modelStatusToString(st), time=time.time() - t0, x=None)
        if out["status"] != "optimal": return out
        sol = h.getSolution(); x = np.asarray(sol.col_value); du = -np.asarray(sol.row_dual)   # 与 linprog marginals 同号（≤ 行 ≤0）
        out["x"] = x; lp = s.M["lp"]; groups = {}
        for key, off in (("le", 0), ("eq", s.m_le + s.nx)):
            for gname, a, b in lp.R[key][4]:
                v = float(np.abs(du[off + a:off + b]).sum())
                if v > 1e-6: groups[gname] = groups.get(gname, 0) + v
        out["groups"] = dict(sorted(groups.items(), key=lambda z: -z[1]))
        out["extra_duals"] = [float(du[s.m_le + i]) for i in range(s.nx)]; out["nvar"] = s.n
        return out
