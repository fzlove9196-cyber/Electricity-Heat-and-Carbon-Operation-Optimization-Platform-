"""算-电-热-碳耦合子模型（全部线性，HiGHS LP 可解）。
每个数据中心：两节点集总 RC 热模型（空气/入口温度 T^a + 建筑/机架热质量 T^m，隐式欧拉离散）、
冷机（COP 随室外温度逐时预计算 → 冷机电功率 = Q/COP_t 为线性）、自然冷却（按室外温度逐时可用冷量）、
冷却塔/水泵辅机、蓄冷罐（显式储冷）、余热回收热泵 → 区域供热网（热网惯性/蓄热罐 = 虚拟储热）。
热安全硬约束：T_min ≤ T^a ≤ T_allow_max、|ΔT^a| ≤ ramp、冷机出力 ≤ N+1 可用冷量、IT ≤ 可用冷却能力。
推荐上限（27°C）超出部分软惩罚。需求响应：相对基线的削减/增加量 ≤ 申报，按补偿价计收益。"""
from __future__ import annotations
import numpy as np
import pyomo.environ as pyo
from ..scenario import outdoor_temp, outdoor_rh
from ..time_axis import event_steps

LEVERS_ALL = dict(precool=True, tes=True, heat=True, dr=True)

def cop_curve(th, tout):
    return np.clip(th.cop_ref - th.cop_slope_per_k*(np.asarray(tout) - th.cop_t_ref_c), th.cop_min, th.cop_max)

def free_frac(th, tout):
    tout = np.asarray(tout, float)
    return np.clip((th.free_t_zero_c - tout)/max(th.free_t_zero_c - th.free_t_full_c, 1e-6), 0, 1)

def chiller_avail(th):
    n = max(int(th.chiller_units), 1)
    return th.chiller_cap_mw_th*((n - 1)/n if (th.redundancy_n1 and n > 1) else 1.0)

def active(sc):
    return sc.thermal_mode == "coupled" and any(d.thermal is not None for d in sc.data_centers)

def heat_dcs(sc):
    hn = sc.heat_network
    if hn is None: return []
    names = hn.dcs or [d.name for d in sc.data_centers]
    return [d.name for d in sc.data_centers if d.name in names and d.thermal is not None and d.thermal.hp_cap_mw_th > 0]


def _build_multi_heat(m, c, hn, HD, T, HG, info, dt):
    """多节点热平衡 + 管段时延（整小时）。hdel = 全网送达负荷之和（售热口径）。
    日初 t < delay 的到达量按 0（无跨日初值，保守、保持 LP 日内独立）。"""
    nodes = list(hn.nodes); Nids = [n.id for n in nodes]; Nmap = {n.id: n for n in nodes}
    pipes = list(hn.pipes or []); Pids = list(range(len(pipes)))
    inject = dict(hn.inject_at or {}); default_n = Nids[0]
    for d in HD: inject.setdefault(d, default_n)
    plant = inject.get(sorted(HD)[0], default_n)
    m.hnode_del = pyo.Var(Nids, T, within=pyo.NonNegativeReals)
    m.hnode_sc = pyo.Var(Nids, T, within=pyo.NonNegativeReals)
    m.hnode_sd = pyo.Var(Nids, T, within=pyo.NonNegativeReals)
    m.hnode_s = pyo.Var(Nids, T, within=pyo.NonNegativeReals)
    if Pids: m.hpipe = pyo.Var(Pids, T, within=pyo.NonNegativeReals)
    for pi, pipe in enumerate(pipes):
        for t in T: c.add(m.hpipe[pi, t] <= float(pipe.capacity_mw_th))
    for t in T:
        if HG is not None:
            f = float(HG["f_boost"][t]); c.add(m.hboost[t]*(1 - f) == f*sum(m.qhp[d, t] for d in HD))
        else:
            m.hboost[t].fix(0)
        for nid in Nids:
            n = Nmap[nid]
            inj = sum(m.qhp[d, t] for d in HD if inject.get(d) == nid)
            if HG is not None and nid == plant: inj = inj + m.hboost[t]
            inflow = 0; outflow = 0
            for pi, pipe in enumerate(pipes):
                if pipe.to == nid:
                    delay = max(int(round(pipe.delay_h/dt)), 0); src_t = t - delay
                    if src_t >= 0: inflow = inflow + (1 - float(pipe.loss)) * m.hpipe[pi, src_t]
                if pipe.frm == nid: outflow = outflow + m.hpipe[pi, t]
            dem_t = float(n.demand_mw_th[t]) if t < len(n.demand_mw_th) else 0.0
            c.add(m.hnode_del[nid, t] <= dem_t)
            c.add(inj + inflow + m.hnode_sd[nid, t] == m.hnode_del[nid, t] + outflow + m.hnode_sc[nid, t])
            if n.storage_mwh_th > 0:
                c.add(m.hnode_sc[nid, t] <= n.storage_p_mw_th); c.add(m.hnode_sd[nid, t] <= n.storage_p_mw_th)
                c.add(m.hnode_s[nid, t] <= n.storage_mwh_th)
                ps = n.storage_soc0*n.storage_mwh_th if t == 0 else m.hnode_s[nid, t-1]
                c.add(m.hnode_s[nid, t] == (1 - n.storage_loss_h)**dt*ps + dt*(m.hnode_sc[nid, t] - m.hnode_sd[nid, t]))
            else:
                m.hnode_sc[nid, t].fix(0); m.hnode_sd[nid, t].fix(0); m.hnode_s[nid, t].fix(0)
        c.add(m.hdel[t] == sum(m.hnode_del[nid, t] for nid in Nids))
        m.hsc[t].fix(0); m.hsd[t].fix(0); m.hs[t].fix(0)
    for nid in Nids:
        n = Nmap[nid]
        if n.storage_mwh_th > 0: c.add(m.hnode_s[nid, len(T)-1] >= n.storage_soc0*n.storage_mwh_th)
    info["heat_nodes"] = Nids
    info["heat_pipes"] = [dict(name=p.name or f"p{i}", frm=p.frm, to=p.to, delay_h=int(p.delay_h), loss=float(p.loss)) for i, p in enumerate(pipes)]

def build(m, sc, DC, D, T, IT, optimize, levers=None):
    """在 Pyomo 模型 m 上添加热子模型。IT(d,t) 为 IT 功率表达式。返回 dict(elec=fn(d,t), obj=expr, info)。"""
    dt=sc.dt_hours
    lv = {**LEVERS_ALL, **(levers or {})}
    if not optimize: lv = dict(precool=False, tes=False, heat=False, dr=False)
    TD = [d for d in D if sc.thermal_mode == "coupled" and DC[d].thermal is not None]
    c = m.thc = pyo.ConstraintList()
    m.Ta = pyo.Var(TD, T); m.Tm = pyo.Var(TD, T)
    m.qch = pyo.Var(TD, T, within=pyo.NonNegativeReals)   # 冷机冷量（含给蓄冷罐充冷）
    m.qfree = pyo.Var(TD, T, within=pyo.NonNegativeReals)
    m.tes_c = pyo.Var(TD, T, within=pyo.NonNegativeReals); m.tes_d = pyo.Var(TD, T, within=pyo.NonNegativeReals)
    m.tes_s = pyo.Var(TD, T, within=pyo.NonNegativeReals)
    m.qhp = pyo.Var(TD, T, within=pyo.NonNegativeReals)   # 热泵供热量
    m.exc = pyo.Var(TD, T, within=pyo.NonNegativeReals)   # 超推荐上限 K
    info = {}; HD = set(heat_dcs(sc)) if lv["heat"] else set()
    from . import cooling as _cl, heat_grade as _hg
    hn = sc.heat_network; HG = None
    if hn is not None and hn.demand_mode == "degree_hour" and hn.design_load_mw_th > 0 and sc.data_centers:
        hn.demand_mw_th = [round(float(x), 3) for x in _hg.degree_hour_demand(hn, outdoor_temp(sc, sc.data_centers[0].bus))]
    if hn is not None and hn.terminal_type and HD:
        ws = sum(DC[d].thermal.hp_cap_mw_th for d in HD)
        tsrc = sum(_cl.source_temp(DC[d].thermal)*DC[d].thermal.hp_cap_mw_th for d in HD)/max(ws, 1e-9)
        tout_h = outdoor_temp(sc, DC[sorted(HD)[0]].bus); HG = _hg.hourly(hn, tsrc, tout_h); HG["t_src"] = tsrc
    for d in TD:
        th = DC[d].thermal; tout = outdoor_temp(sc, DC[d].bus); hc = _cl.hourly(th, tout, outdoor_rh(sc, DC[d].bus)); cop = hc["cop"]; ff = hc["ff"]
        hpc = np.full(len(T), th.hp_cop)
        if HG is not None and d in HD:
            Hd = _hg.hourly(hn, _cl.source_temp(th), tout); hpc = Hd["cop"]
        cav = chiller_avail(th); info[d] = dict(cop=cop, tout=tout, rh=outdoor_rh(sc, DC[d].bus), free_avail=th.free_cap_mw_th*ff, chiller_avail=cav, free_cop=hc["free_cop"], wue=hc["wue"], hp_cop=hpc, lf=hc["lf"])
        for t in T:
            prevA = th.t0_c if t == 0 else m.Ta[d, t-1]; prevM = th.t0_c if t == 0 else m.Tm[d, t-1]
            qroom = m.qch[d, t] - m.tes_c[d, t] + m.qfree[d, t] + m.tes_d[d, t] + m.qhp[d, t]*(1 - 1/hpc[t])
            # 空气节点（隐式欧拉，Δt=1h）：C_a ΔT = IT + 其他发热 − 排热 − UA_am(Ta−Tm) + UA_env(Tout−Ta)
            c.add(th.c_air_mwh_k*(m.Ta[d, t] - prevA) == dt*(IT(d, t)*(1 + th.other_frac*0.5) - qroom
                  - th.ua_am_mw_k*(m.Ta[d, t] - m.Tm[d, t]) + th.ua_env_mw_k*(tout[t] - m.Ta[d, t])))
            c.add(th.c_mass_mwh_k*(m.Tm[d, t] - prevM) == dt*th.ua_am_mw_k*(m.Ta[d, t] - m.Tm[d, t]))
            # 热安全硬约束
            c.add(m.Ta[d, t] >= th.t_min_c); c.add(m.Ta[d, t] <= th.t_allow_max_c)
            c.add(m.Ta[d, t] - prevA <= dt*th.ramp_max_k_h); c.add(prevA - m.Ta[d, t] <= dt*th.ramp_max_k_h)
            c.add(m.exc[d, t] >= m.Ta[d, t] - th.t_rec_max_c)
            c.add(m.qch[d, t] <= cav)                                   # N+1 可用冷机冷量
            c.add(m.qfree[d, t] <= th.free_cap_mw_th*ff[t])
            c.add(m.qch[d, t] - m.tes_c[d, t] + m.qfree[d, t] + m.tes_d[d, t] <= th.crah_cap_mw_th)   # 末端排热能力
            c.add(m.tes_c[d, t] <= m.qch[d, t])
            # IT 不得超过可用冷却能力（稳态充足性，热安全硬约束）
            c.add(IT(d, t) <= cav + th.free_cap_mw_th*ff[t] + (th.tes_p_mw_th if lv["tes"] else 0) + (th.hp_cap_mw_th*(1 - 1/hpc[t]) if d in HD else 0))
            # 蓄冷罐
            if th.tes_mwh_th > 0 and lv["tes"]:
                c.add(m.tes_c[d, t] <= th.tes_p_mw_th); c.add(m.tes_d[d, t] <= th.tes_p_mw_th); c.add(m.tes_s[d, t] <= th.tes_mwh_th)
                ps = th.tes_soc0*th.tes_mwh_th if t == 0 else m.tes_s[d, t-1]
                c.add(m.tes_s[d, t] == (1 - th.tes_loss_h)**dt*ps + dt*(m.tes_c[d, t] - m.tes_d[d, t]))
            else:
                for x in (m.tes_c, m.tes_d): x[d, t].fix(0)
                m.tes_s[d, t].fix(th.tes_soc0*th.tes_mwh_th)
            if d in HD:
                c.add(m.qhp[d, t] <= th.hp_cap_mw_th); c.add(m.qhp[d, t]*(1 - 1/hpc[t]) <= th.hr_max_frac*IT(d, t))
            else: m.qhp[d, t].fix(0)
            if not lv["precool"]: m.Ta[d, t].fix(th.t0_c)               # 无预冷：定送风温度运行
        if th.tes_mwh_th > 0 and lv["tes"]: c.add(m.tes_s[d, len(T)-1] >= th.tes_soc0*th.tes_mwh_th)
        if lv["precool"]: c.add(m.Ta[d, len(T)-1] <= th.t0_c); c.add(m.Tm[d, len(T)-1] <= th.t0_c)   # 日末不"透支"热惯性
    # 区域供热网 + 虚拟储热（单节点旧路径 / 多节点+管段时延）
    m.hdel = pyo.Var(T, within=pyo.NonNegativeReals); m.hboost = pyo.Var(T, within=pyo.NonNegativeReals); m.hs = pyo.Var(T, within=pyo.NonNegativeReals)
    m.hsc = pyo.Var(T, within=pyo.NonNegativeReals); m.hsd = pyo.Var(T, within=pyo.NonNegativeReals)
    multi = bool(hn is not None and getattr(hn, "nodes", None))
    if multi and len(hn.nodes) == 0: multi = False
    info["_heat_multi"] = multi
    if hn is not None and HD and multi:
        _build_multi_heat(m, c, hn, HD, T, HG, info, dt)
    elif hn is not None and HD:
        for t in T:
            if HG is not None:   # 余热品位模型：站出口温度不足部分由调峰补热（比例 f_t 逐时预计算）；管网热损随长度
                f = float(HG["f_boost"][t]); c.add(m.hboost[t]*(1 - f) == f*sum(m.qhp[d, t] for d in HD))
                c.add((1 - HG["loss"])*(sum(m.qhp[d, t] for d in HD) + m.hboost[t]) + m.hsd[t] - m.hsc[t] == m.hdel[t])
            else:
                m.hboost[t].fix(0)
                c.add((1 - hn.pipe_loss)*sum(m.qhp[d, t] for d in HD) + m.hsd[t] - m.hsc[t] == m.hdel[t])
            c.add(m.hdel[t] <= hn.demand_mw_th[t])
            if hn.storage_mwh_th > 0:
                c.add(m.hsc[t] <= hn.storage_p_mw_th); c.add(m.hsd[t] <= hn.storage_p_mw_th); c.add(m.hs[t] <= hn.storage_mwh_th)
                ps = hn.storage_soc0*hn.storage_mwh_th if t == 0 else m.hs[t-1]
                c.add(m.hs[t] == (1 - hn.storage_loss_h)**dt*ps + dt*(m.hsc[t] - m.hsd[t]))
            else: m.hsc[t].fix(0); m.hsd[t].fix(0); m.hs[t].fix(0)
        if hn.storage_mwh_th > 0: c.add(m.hs[len(T)-1] >= hn.storage_soc0*hn.storage_mwh_th)
    else:
        for t in T: m.hdel[t].fix(0); m.hboost[t].fix(0); m.hs[t].fix(0); m.hsc[t].fix(0); m.hsd[t].fix(0)

    def cool_e(d, t):
        th = DC[d].thermal; cop = info[d]["cop"][t]
        return m.qch[d, t]*(1/cop + th.tower_pump_kw_per_kw) + m.qfree[d, t]/info[d]["free_cop"][t]
    def elec(d, t):
        if d not in TD: return DC[d].pue*IT(d, t)
        th = DC[d].thermal
        e = IT(d, t)*(1 + th.other_frac) + cool_e(d, t) + m.qhp[d, t]/info[d]["hp_cop"][t]
        if HG is not None and hn.booster == "electric" and HD and d == sorted(HD)[0]: e = e + m.hboost[t]   # 电热补热（效率≈1）计入首个供热 DC 用电
        return e
    pen = dt*sum(DC[d].thermal.rec_exceed_penalty_cny_kh*m.exc[d, t] for d in TD for t in T)
    heat_rev = (dt*hn.price_cny_mwh_th*sum(m.hdel[t] for t in T)) if (hn is not None and HD) else 0
    if HG is not None and hn.booster == "gas_boiler":   # 燃气调峰成本（碳另行核算）
        pen = pen + dt*hn.booster_price_cny_mwh_th*sum(m.hboost[t] for t in T)
    return dict(HG=HG, TD=TD, HD=sorted(HD), elec=elec, cool_e=cool_e, pen=pen, heat_rev=heat_rev, info=info, levers=lv)

def build_dr(m, sc, DC, D, T, elec, baseline_dc, levers, stonet=None):
    """需求响应：baseline_dc = {e: 24 点基线关口功率（DC 用电 + 计入的表后储能净充电）}。stonet(names, t)=储能净充电表达式。返回 (obj_expr, records)。"""
    E = list(range(len(sc.dr_events))) if levers.get("dr", True) and sc.dr_events else []
    m.dr = pyo.Var([(e, t) for e in E for t in event_steps(sc,sc.dr_events[e])], within=pyo.NonNegativeReals)
    m.drs = pyo.Var([(e, t) for e in E for t in event_steps(sc,sc.dr_events[e])], within=pyo.NonNegativeReals)
    c = m.drc = pyo.ConstraintList(); obj = 0
    for e in E:
        ev = sc.dr_events[e]; ds = [d for d in D if (not ev.dcs or d in ev.dcs)]
        for t in event_steps(sc,ev):
            base = float(baseline_dc[e][t]); load = sum(elec(d, t) for d in ds) + (stonet(ev.storages, t) if (stonet and ev.storages) else 0)
            c.add(m.dr[e, t] <= ((base - load) if ev.kind == "reduce" else (load - base)))
            c.add(m.dr[e, t] <= min(ev.request_mw, ev.max_mw if ev.max_mw is not None else 1e9))
            if ev.mandatory: c.add(m.dr[e, t] >= ev.request_mw)
            c.add(m.drs[e, t] >= ev.request_mw - m.dr[e, t])
            obj = obj + sc.dt_hours*(-ev.price_cny_mwh*m.dr[e, t] + ev.shortfall_penalty_cny_mwh*m.drs[e, t])
    return obj, E

def cooling_deficits(sc, optimize=True, tol=1e-6):
    """设计日冷量充足性预检（不求解）：逐时 可用冷量(N+1 冷机 + 自然冷却 + 蓄冷放冷) vs 必须带走的 IT 发热。
    optimize=True 时只计不可时移的交互负载；基线计交互 + 批处理均匀运行。返回 [{dc, hour, avail_mw, need_mw, t_out, ratio_needed}]。"""
    from . import cooling as _cl
    out = []
    if sc.thermal_mode != "coupled": return out
    for d in sc.data_centers:
        th = d.thermal
        if th is None: continue
        tout = outdoor_temp(sc, d.bus); hc = _cl.hourly(th, tout, outdoor_rh(sc, d.bus)); cav = chiller_avail(th)
        for t in range(len(tout)):
            ta = th.t_allow_max_c if optimize else th.t0_c   # 基线定送风温度；优化时入口最高可到允许上限
            need = (d.interactive_mw[t] + (0 if optimize else d.batch_mwh/24))*(1 + th.other_frac*0.5) + max(0.0, th.ua_env_mw_k*(float(tout[t]) - ta))
            avail = cav + th.free_cap_mw_th*hc["ff"][t] + (th.tes_p_mw_th if (optimize and th.tes_mwh_th > 0) else 0)
            if need > avail + tol:
                n = max(int(th.chiller_units), 1); k = (n - 1)/n if (th.redundancy_n1 and n > 1) else 1.0
                out.append(dict(dc=d.name, hour=t, avail_mw=round(float(avail), 2), need_mw=round(float(need), 2), t_out=round(float(tout[t]), 1),
                                chiller_needed_mw=round(float((need - th.free_cap_mw_th*hc["ff"][t])/k), 1), chiller_cap_mw=th.chiller_cap_mw_th))
    return out
