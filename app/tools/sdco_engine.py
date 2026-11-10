"""算电协同调度引擎（由 /workspace/sdco-demo/sdco_demo.py 重构为可参数化函数）。
多时段 DC-OPF (B-theta) LP + 数据中心批处理时移/跨中心迁移 + 储能；pandapower 交流潮流校核。"""
from __future__ import annotations
from ..solver_execution import serialized_pyomo, checked_solve
import copy
import numpy as np, pandas as pd
import pandapower as pp, pandapower.networks as pn
import pyomo.environ as pyo
from ..scenario import Scenario, pv_shape, carbon_profile
from ..time_axis import boundary, window, event_steps

BASE_MVA = 100.0
# case14 无有效线路额定值 -> 假设值（合成）：15 条线路 + 5 台变压器
_LINE_RATING = [160, 80, 80, 80, 60, 60, 60, 40, 40, 40, 30, 30, 30, 30, 30]

def _build_custom(sc: Scenario):
    nw = sc.network
    if nw is None: raise ValueError("network_case='custom' 需要提供 network（buses/lines/trafos/ext_grids）")
    net = pp.create_empty_network(sn_mva=BASE_MVA)
    for b in nw.buses: pp.create_bus(net, vn_kv=b.vn_kv, name=b.name)
    for l in nw.lines:
        vn = nw.buses[l.from_bus].vn_kv
        pp.create_line_from_parameters(net, l.from_bus, l.to_bus, l.length_km, l.r_ohm_per_km, l.x_ohm_per_km,
                                       l.c_nf_per_km, max_i_ka=l.rating_mva/(np.sqrt(3)*vn), name=l.name, parallel=l.parallel)
    for t in nw.trafos:
        pp.create_transformer_from_parameters(net, t.hv_bus, t.lv_bus, t.sn_mva, nw.buses[t.hv_bus].vn_kv, nw.buses[t.lv_bus].vn_kv,
                                              t.vkr_percent, t.vk_percent, 0.0, 0.0, name=t.name, parallel=t.parallel)
    for e in nw.ext_grids: pp.create_ext_grid(net, e.bus, vm_pu=e.vm_pu, name=e.name, max_p_mw=e.import_max_mw)
    for ld in nw.loads: pp.create_load(net, ld.bus, p_mw=ld.p_mw, q_mvar=ld.q_mvar, name=ld.name)
    rating = np.array([l.rating_mva*l.parallel for l in nw.lines] + [t.sn_mva*t.parallel for t in nw.trafos], float)
    return net, rating

def branch_arrays(net):
    """DC 支路模型数组 (需先 rundcpp)。与 MATPOWER/pandapower makeBdc 一致：b = 1/(x·tap)，tap=0 视为 1。
    公开基准 B1 (cases/public_bench) 发现旧实现忽略变压器变比，case14/57/118 变压器潮流误差达 6~10%。
    设环境变量 SDCO_DC_IGNORE_TAP=1 可恢复旧行为（仅用于对比复现）。"""
    import os
    br = net._ppc["branch"]
    x = br[:, 3].real.copy(); tap = br[:, 8].real.copy(); tap[tap == 0] = 1.0
    xb = x if os.environ.get("SDCO_DC_IGNORE_TAP") == "1" else x*tap
    return dict(fb=br[:, 0].real.astype(int), tb=br[:, 1].real.astype(int), xb=xb, tap=tap, NBR=len(br))

def prepare_network(sc: Scenario):
    if sc.network_case == "custom":
        net, rating = _build_custom(sc)
    elif sc.network_case == "case14":
        net = pn.case14(); rating = None
    else:
        raise ValueError(f"暂只支持 case14 / custom, 收到 {sc.network_case}")
    # 每个电气岛取一个外网母线作为相角参考；无外网的孤岛（直供微网/离网）加临时平衡点仅用于形成支路矩阵
    import pandapower.topology as top
    refs, dummy = [], []
    for comp in top.connected_components(top.create_nxgraph(net)):
        eg = [int(b) for b in net.ext_grid.bus if int(b) in comp]
        if eg: refs.append(eg[0])
        else: refs.append(min(comp)); dummy.append(min(comp))
    pn_ = net
    if dummy:
        pn_ = copy.deepcopy(net)
        for b in dummy: pp.create_ext_grid(pn_, b, name="_island_ref")
    pp.rundcpp(pn_)
    A = branch_arrays(pn_); br = pn_._ppc["branch"]
    nl = len(net.line)
    if rating is None: rating = np.array(_LINE_RATING + [60]*(len(br)-nl), float)
    return dict(net=net, nb=len(net.bus), fb=A["fb"], tb=A["tb"],
                xb=A["xb"], NBR=A["NBR"], nl=nl, rating=rating, refs=refs)

def load_profile(sc=None):
    h = np.arange(24) if sc is None else np.floor(np.arange(sc.n_steps)*sc.dt_hours)
    return 0.70 + 0.25*np.exp(-((h-11)/3.5)**2) + 0.30*np.exp(-((h-19)/2.5)**2)

def validate(sc: Scenario, nb: int | None = None):
    errs = []
    n=sc.n_steps; dt=sc.dt_hours
    if sc.hours!=24: errs.append("当前常规日调度必须 hours=24；年度/多日路径不可隐式扩展")
    if (dt!=1 or any(j.execution_mode=="continuous" for j in sc.jobs)) and sc.vcc_mode!="off": errs.append("VCC尚不支持15min/整数连续任务；必须关闭，不能默默按1h")
    def check_profile(values,label):
        if len(values)!=n: errs.append(f"{label} 必须 {n} 点(dt={dt}h)")
        if any(not np.isfinite(x) for x in values): errs.append(label+" 必须有限")
    for label,values in [("outdoor_temp_c",sc.outdoor_temp_c)]: check_profile(values,label)
    for group in [sc.outdoor_temp_profiles,sc.outdoor_rh_profiles,sc.carbon_marginal_profiles]:
        for label,values in group.items(): check_profile(values,label)
    for p in sc.pv:
        if p.profile is not None: check_profile(p.profile,"PV.profile")
        if p.lifecycle_tco2e_mwh_profile is not None: check_profile(p.lifecycle_tco2e_mwh_profile,"PV.lifecycle")
    if sc.network:
        for e in sc.network.ext_grids:
            if e.price_cny_kwh is not None: check_profile(e.price_cny_kwh,"grid.price")
            if e.export_price_cny_kwh is not None: check_profile(e.export_price_cny_kwh,"grid.export_price")
    if sc.heat_network:
        check_profile(sc.heat_network.demand_mw_th,"heat.demand")
        for node in sc.heat_network.nodes: check_profile(node.demand_mw_th,"heat.node.demand")
    for ev in sc.dr_events:
        try:
            ts=event_steps(sc,ev)
            if not (0<=ev.start<ev.end<=sc.hours): errs.append("DR窗口必须在物理日内")
        except ValueError as e: errs.append(str(e))
        if ev.baseline_mw is not None: check_profile(ev.baseline_mw,"DR.baseline")
    if nb is None: nb = len(sc.network.buses) if (sc.network_case == "custom" and sc.network) else 14
    if sc.network_case == "custom" and not sc.network: errs.append("network_case=custom 但缺少 network")
    for d in sc.data_centers:
        if not 0 <= d.bus < nb: errs.append(f"{d.name}.bus={d.bus} 超出 0..{nb-1}")
        if len(d.interactive_mw) != n: errs.append(f"{d.name}.interactive_mw 必须 {n} 点(dt={dt}h)")
        if max(d.interactive_mw) > d.cap_it_mw: errs.append(f"{d.name} 交互负载超过 IT 容量")
        if d.batch_mwh > dt*sum(d.cap_it_mw - x for x in d.interactive_mw):
            errs.append(f"{d.name}.batch_mwh 超过日可用 IT 余量")
        pm = getattr(d, "power_model", "identity") or "identity"
        if pm not in ("identity", "idle_dynamic", "pdu_pwl"):
            errs.append(f"{d.name}.power_model 非法: {pm}")
        if pm == "idle_dynamic":
            from ..power_model import resolve_idle_peak
            idle, peak = resolve_idle_peak(d)
            if idle is None or peak is None:
                errs.append(f"{d.name}: idle_dynamic 需要 p_idle_mw/p_peak_mw 或 p_idle_kw/p_peak_kw+n_servers")
            elif peak < idle or idle < 0:
                errs.append(f"{d.name}: 需满足 0 ≤ p_idle ≤ p_peak")
        if pm == "pdu_pwl":
            bps = getattr(d, "pdu_breakpoints", None) or []
            if len(bps) < 2:
                errs.append(f"{d.name}: pdu_pwl 至少需要 2 个断点")
    for s in sc.storage:
        if not 0 <= s.bus < nb: errs.append(f"{s.name}.bus 越界")
        if not (0 <= s.soc_min <= s.soc0 <= s.soc_max <= 1): errs.append(f"{s.name} SOC 参数不合法")
    for p in sc.pv:
        if p.lifecycle_tco2e_mwh_profile is not None and any(not np.isfinite(x) or x<0 for x in p.lifecycle_tco2e_mwh_profile): errs.append("VRE 生命周期强度必须有限非负")
        if not 0 <= p.bus < nb: errs.append(f"PV bus {p.bus} 越界")
    if len(sc.price_cny_kwh) != n: errs.append(f"price_cny_kwh 必须 {n} 点(dt={dt}h)")
    if sc.network_case == "custom" and sc.network:
        nw = sc.network
        for k, l in enumerate(nw.lines):
            if not (0 <= l.from_bus < nb and 0 <= l.to_bus < nb): errs.append(f"线路 {l.name or k} 端点母线越界")
            elif l.from_bus == l.to_bus: errs.append(f"线路 {l.name or k} 两端为同一母线")
        for k, t in enumerate(nw.trafos):
            if not (0 <= t.hv_bus < nb and 0 <= t.lv_bus < nb): errs.append(f"变压器 {t.name or k} 端点母线越界")
            elif t.hv_bus == t.lv_bus: errs.append(f"变压器 {t.name or k} 高/低压侧为同一母线")
        for e in nw.ext_grids:
            if not 0 <= e.bus < nb: errs.append(f"外网 {e.name}.bus 越界")
        for g in nw.gens:
            if not 0 <= g.bus < nb: errs.append(f"电源 {g.name}.bus 越界")
            if g.pmin_mw > g.pmax_mw: errs.append(f"电源 {g.name} Pmin > Pmax")
        for ld in nw.loads:
            if not 0 <= ld.bus < nb: errs.append(f"负荷 {ld.name}.bus 越界")
    if sc.min_green_share is not None and not 0 <= sc.min_green_share <= 1: errs.append("min_green_share 须在 0~1")
    names = {d.name for d in sc.data_centers}
    for r, prof in sc.carbon_profiles.items():
        if len(prof) != n or min(prof) < 0: errs.append(f"carbon_profiles[{r}] 必须为 {n} 个非负值")
    if sc.carbon_weight < 0 or sc.carbon_price_cny_t < 0: errs.append("carbon_weight / carbon_price_cny_t 不能为负")
    if getattr(sc, "vcc_mode", "off") not in ("off", "carbon", "price", "weighted"):
        errs.append(f"vcc_mode 非法: {sc.vcc_mode}")
    if getattr(sc, "vcc_objective_scale", 1.0) < 0: errs.append("vcc_objective_scale 不能为负")
    for l in sc.links:
        if l.a not in names or l.b not in names: errs.append(f"链路 {l.a}-{l.b} 引用了不存在的数据中心")
        if l.bw_mw < 0 or l.latency_ms < 0: errs.append(f"链路 {l.a}-{l.b} 带宽/时延不能为负")
    ids = set()
    for j in sc.jobs:
        if j.id in ids: errs.append(f"任务 id 重复: {j.id}")
        ids.add(j.id)
        if j.dc not in names: errs.append(f"任务 {j.id} 的 dc={j.dc} 不存在")
        try: window(sc,j)
        except ValueError as e: errs.append(str(e))
        if not (0 <= j.release < j.deadline <= sc.hours): errs.append(f"任务 {j.id} 需满足 0 ≤ release < deadline ≤ 24")
        if j.energy_mwh < 0 or j.max_mw <= 0: errs.append(f"任务 {j.id} 能量/功率不合法")
        elif j.execution_mode=="energy" and j.energy_mwh > j.max_mw*(j.deadline - j.release) + 1e-6:
            errs.append(f"任务 {j.id} 能量 {j.energy_mwh} 超过 max_mw×窗口 = {j.max_mw*(j.deadline-j.release):.2f}（提高 max_mw 或放宽截止时间）")
        if j.execution_mode=="continuous":
            if j.duration_h is None or j.duration_h<=0: errs.append(f"任务 {j.id} 必须给出正 duration_h")
            else:
                for h in [j.duration_h,j.initial_progress_h,j.restart_delay_h]:
                    try: boundary(sc,h)
                    except ValueError as e: errs.append(str(e))
                if abs(j.energy_mwh-j.duration_h*j.max_mw)>1e-7: errs.append(f"任务 {j.id} energy_mwh 必须等于duration_h×max_mw；完成价值与实际重做耗能分账")
                if not 0<=j.initial_progress_h<j.duration_h: errs.append(f"任务 {j.id} 初始进度必须小于总工时")
                if j.initial_progress_h and j.release!=0: errs.append("带初始进度的任务必须release=0")
                if j.restart_delay_h<0: errs.append("重启等待必须非负")
                if j.initial_dc and j.initial_dc not in names: errs.append("初始运行站点不存在")
            if sc.lifecycle_counterfactual!="none": errs.append("连续重启任务尚无jobs_origin_uniform反事实；必须设none")
        elif j.initial_progress_h or j.allow_restart or j.duration_h is not None or j.required:
            errs.append("能量流任务不能携带整数任务状态/required；请显式execution_mode=continuous")
        for a in (j.allowed_dcs or []):
            if a not in names: errs.append(f"任务 {j.id} allowed_dcs 含不存在的 {a}")
    if sc.objective_mode == "welfare":
        if not sc.jobs: errs.append("welfare 必须使用显式任务需求报价")
        if any(j.value_cny_mwh is None for j in sc.jobs): errs.append("welfare 每个任务必须提供 value_cny_mwh")
        if sc.carbon_weight != 0: errs.append("welfare 必须显式设 carbon_weight=0")
    if sc.network_domain == "paper_abstract" and sc.network_case != "custom": errs.append("paper_abstract 必须使用显式 custom 网络")
    if sc.lifecycle_counterfactual == "jobs_origin_uniform":
        if sc.network_case != "custom" or not sc.network or sc.network.loads or sc.storage or sc.heat_network:
            errs.append("jobs_origin_uniform 必须是无常规负荷/储能/供热的显式 custom 增量模型；其他模型请保留 counterfactual=none")
        if sc.thermal_mode != "constant_pue" or any(d.power_model != "identity" for d in sc.data_centers):
            errs.append("jobs_origin_uniform 必须使用 identity + constant_pue；其他模型尚无此反事实")
    return errs

def link_map(sc: Scenario):
    """{(src,dst): Link}，双向；links 为空返回 None（不限制）。"""
    if not sc.links: return None
    m = {}
    for l in sc.links: m[(l.a, l.b)] = l; m[(l.b, l.a)] = l
    return m

def job_sites(sc: Scenario, j, optimize: bool):
    """任务可运行的数据中心（考虑 allowed_dcs、链路存在性与时延敏感约束）。"""
    if not optimize: return [j.dc]
    names = [d.name for d in sc.data_centers]; L = link_map(sc)
    out = []
    for d in (j.allowed_dcs or names):
        if d == j.dc: out.append(d); continue
        if L is not None:
            l = L.get((j.dc, d))
            if l is None or l.bw_mw <= 0: continue
            if j.max_latency_ms is not None and l.latency_ms > j.max_latency_ms: continue
        out.append(d)
    if j.dc not in out: out.insert(0, j.dc)
    return out

@serialized_pyomo('daily_sdco')
def solve(sc: Scenario, optimize: bool, use_storage: bool | None = None, solver_opts: dict | None = None, no_migration: bool = False,
          levers: dict | None = None, roll: dict | None = None):
    """optimize=False: 基线（批处理均匀运行在本地、无迁移、无储能）。

    roll (可选，默认 None=旧行为): 日内滚动 / 可行域扫描钩子
      from_t: 从此小时起决策自由；此前小时按 prior 结果固定
      prior: 上次 solve 的结果 dict（含 df）
      baseline_site_mw: 长度 24 的日前关口功率，用于偏离罚
      dev_penalty_cny_mwh: 相对基线 |ΔP| 罚系数
      fix_gens: 过去小时是否同时固定机组/外网/光伏
      envelope_hour / envelope_sense: 'max'|'min' 时改为该小时站点关口极值目标
      rt_storage_only: 可行域实时层，仅放开 envelope_hour 的储能
    """
    errors=validate(sc)
    if errors: raise ValueError("场景校验失败: "+"; ".join(errors))
    if roll:
        from ..time_axis import require_hourly
        require_hourly(sc,"三级滚动/可行域")
    dt=sc.dt_hours; n=sc.n_steps
    use_storage = optimize if use_storage is None else use_storage
    roll = roll or None
    N = prepare_network(sc); net = N["net"]; fb, tb, xb, rating = N["fb"], N["tb"], N["xb"], N["rating"]
    T = range(n); lp = load_profile(sc)*sc.load_scale
    price = np.array(sc.price_cny_kwh); pmwh = price*1000
    PV, PVBUS, PVPPA, PVTOP = {}, {}, {}, {}
    for k, p in enumerate(sc.pv):
        prof = np.array(p.profile) if p.profile else np.repeat(pv_shape(),int(round(1/dt)))
        PV[k] = p.cap_mw*prof; PVBUS[k] = p.bus; PVPPA[k] = (p.ppa_price_cny_kwh or 0.0)*1000; PVTOP[k] = bool(p.ppa_take_or_pay)
    DC = {d.name: d for d in sc.data_centers}; D = list(DC)
    if use_storage: STO = {s.name: s for s in sc.storage}
    else:   # 基线不用储能；但无外网的孤岛（离网微网）中储能是供电必需设备，保留
        import pandapower.topology as _top
        _g = _top.create_nxgraph(net); _eg = set(int(b) for b in net.ext_grid.bus)
        _cg = set(g.bus for g in (sc.network.gens if (sc.network_case == "custom" and sc.network) else []))
        _iso = set().union(*[set(c) for c in _top.connected_components(_g) if not (set(c) & _eg)] or [set()])
        STO = {s.name: s for s in sc.storage if s.bus in _iso}
    gens = []
    egs = sc.network.ext_grids if (sc.network_case == "custom" and sc.network) else None
    for i, r in net.ext_grid.iterrows():
        e = egs[i] if egs else None
        pr = np.array(e.price_cny_kwh)*1000 if (e and e.price_cny_kwh) else pmwh
        xp = np.array(e.export_price_cny_kwh)*1000 if (e and e.export_price_cny_kwh) else pmwh
        xp = np.minimum(xp, pr + sc.grid_markup_cny_mwh - 0.1)   # 同一外网点售电价略低于购电价，避免“同时购售”套利/退化解（LP 无整数约束）
        gens.append(dict(bus=int(r.bus), pmax=float(r.max_p_mw) if np.isfinite(r.max_p_mw) else 1e4, pmin=0.0,
                         cost=pr + sc.grid_markup_cny_mwh, ext=True, name=str(r["name"] or f"grid{i}"),
                         exmax=float(e.export_max_mw) if e else 0.0, excost=xp, dem=float(e.demand_charge_cny_mw_day) if e else 0.0))
    for i, r in net.gen.iterrows():
        gens.append(dict(bus=int(r.bus), pmax=float(r.max_p_mw), pmin=sc.gen_min_share*float(r.max_p_mw),
                         cost=np.full(n, sc.gen_cost[i % len(sc.gen_cost)]), ext=False, exmax=0.0, excost=np.zeros(n), dem=0.0,
                         emis=sc.gen_emission_t_mwh[i % len(sc.gen_emission_t_mwh)]))
    _emerg = bool(getattr(sc, "emergency_mode", False) or ((roll or {}).get("emergency") if roll else False))
    for g in (sc.network.gens if (sc.network_case == "custom" and sc.network) else []):
        _pmax = float(g.pmax_mw)
        _mode = getattr(g, "dispatch_mode", "economic") or "economic"
        if (g.kind or "") == "diesel" and _mode == "emergency_only" and not _emerg:
            _pmax = 0.0  # 默认关闭：仅应急放开，保持旧场景无柴发行为
        _pmin = float(g.pmin_mw)
        if _pmax <= 0: _pmin = 0.0
        gens.append(dict(bus=g.bus, pmax=_pmax, pmin=_pmin, cost=np.full(n, g.cost_cny_mwh), ext=False, exmax=0.0, excost=np.zeros(n),
                         dem=0.0, emis=g.emission_t_mwh, name=g.name, kind=g.kind, eday=g.energy_mwh_day,
                         ramp=getattr(g, "ramp_mw_h", None), dispatch_mode=_mode, source_note=getattr(g, "source_note", "")))
    base_load = {b: net.load[net.load.bus == b].p_mw.sum() for b in range(N["nb"])}
    G = range(len(gens)); B = range(N["nb"]); L = range(N["NBR"])

    m = pyo.ConcreteModel()
    m.pg = pyo.Var(G, T, within=pyo.NonNegativeReals)
    m.gx = pyo.Var(G, T, within=pyo.NonNegativeReals)   # 外网反送（售电）
    for g in G:
        for t in T:
            if gens[g]["exmax"] <= 0: m.gx[g, t].fix(0)
    m.th = pyo.Var(B, T, bounds=(None, None) if sc.network_domain == "paper_abstract" else (-np.pi, np.pi))
    m.pv = pyo.Var(list(PV), T, within=pyo.NonNegativeReals)
    m.bt = pyo.Var(D, T, within=pyo.NonNegativeReals)
    m.mg = pyo.Var(D, D, T, within=pyo.NonNegativeReals)
    m.ch = pyo.Var(list(STO), T, within=pyo.NonNegativeReals)
    m.dis = pyo.Var(list(STO), T, within=pyo.NonNegativeReals)
    m.soc = pyo.Var(list(STO), T, within=pyo.NonNegativeReals)
    JOBS = list(sc.jobs); job_mode = bool(JOBS); LM = link_map(sc); kappa = sc.mig_energy_mwh_per_mwh
    JX = [(j.id, d, t) for j in JOBS for d in job_sites(sc, j, optimize and not no_migration) for t in window(sc,j)]
    JB = {j.id: j for j in JOBS}
    m.pj = pyo.Var(JX, within=pyo.NonNegativeReals)
    m.un = pyo.Var([j.id for j in JOBS], within=pyo.NonNegativeReals)
    for d in D:
        for e in D:
            for t in T:
                if d == e or not optimize or job_mode or no_migration: m.mg[d, e, t].fix(0)
                elif LM is not None and ((d, e) not in LM): m.mg[d, e, t].fix(0)
        if not optimize and not job_mode:
            for t in T: m.bt[d, t].fix(DC[d].batch_mwh/24)
    c = m.c = pyo.ConstraintList()
    if job_mode:
        from collections import defaultdict
        by_dt = defaultdict(list); by_jt = defaultdict(list); by_j = defaultdict(list); mig = defaultdict(list)
        for (jid, d, t) in JX:
            by_dt[d, t].append((jid, d, t)); by_jt[jid, t].append((jid, d, t)); by_j[jid].append((jid, d, t))
            if d != JB[jid].dc: mig[JB[jid].dc, d, t].append((jid, d, t))
        from .integer_jobs import build as build_integer
        integer_info=build_integer(m,sc,JOBS,JX,job_sites, optimize and not no_migration)
        for j in JOBS:
            if j.execution_mode=="continuous": continue
            c.add(dt*sum(m.pj[x] for x in by_j[j.id]) + m.un[j.id] == j.energy_mwh)
            for t in window(sc,j):
                if not by_jt[j.id, t]: continue
                cap = j.max_mw if optimize else j.energy_mwh/(j.deadline - j.release)   # 基线：本地均匀运行
                c.add(sum(m.pj[x] for x in by_jt[j.id, t]) <= cap)
        for d in D:
            for t in T:   # 批处理 IT = 作业功率 + 迁入作业的迁移能耗
                c.add(m.bt[d, t] == sum(m.pj[x] for x in by_dt[d, t])
                      + kappa*sum(m.pj[x] for (h, e, tt), xs in mig.items() if e == d and tt == t for x in xs))
                outs = [x for (h, e, tt), xs in mig.items() if h == d and tt == t for x in xs]
                if outs: c.add(sum(m.pj[x] for x in outs) <= sc.mig_max_mw)
            home_E = sum(j.energy_mwh for j in JOBS if j.dc == d)
            outs = [x for (h, e, tt), xs in mig.items() if h == d for x in xs]
            if outs: c.add(dt*sum(m.pj[x] for x in outs) <= sc.mig_day_share*home_E + 1e-6)
        if LM is not None:
            for (h, e, t), xs in mig.items(): c.add(sum(m.pj[x] for x in xs) <= LM[(h, e)].bw_mw)
    for k in PV:
        for t in T: c.add(m.pv[k, t] <= PV[k][t])
    m.pk = pyo.Var(G, within=pyo.NonNegativeReals)   # 日最大购电功率（需量电费）
    for g in G:
        if gens[g].get("dem", 0) > 0:
            for t in T: c.add(m.pk[g] >= m.pg[g, t])
        else: m.pk[g].fix(0)
        if gens[g].get("eday") is not None: c.add(dt*sum(m.pg[g, t] for t in T) <= gens[g]["eday"])   # 水电日电量
    for g in G:
        for t in T:
            c.add(m.pg[g, t] <= gens[g]["pmax"]); c.add(m.pg[g, t] >= gens[g]["pmin"])
            if gens[g]["exmax"] > 0: c.add(m.gx[g, t] <= gens[g]["exmax"])
        # 柴发/机组爬坡（连续简化；min_up/启停二进制默认不建模）
        _ramp = gens[g].get("ramp")
        if _ramp is not None and float(_ramp) < 1e6:
            for t in range(1, n):
                c.add(m.pg[g, t] - m.pg[g, t - 1] <= dt*float(_ramp))
                c.add(m.pg[g, t - 1] - m.pg[g, t] <= dt*float(_ramp))
    for d in D:
        if not job_mode:
            c.add(dt*sum(m.bt[d, t] for t in T) == DC[d].batch_mwh
                  - dt*sum(m.mg[d, e, t] for e in D for t in T) + dt*(1 + kappa)*sum(m.mg[e, d, t] for e in D for t in T))
            c.add(dt*sum(m.mg[d, e, t] for e in D for t in T) <= sc.mig_day_share*DC[d].batch_mwh)
        for t in T:
            c.add(DC[d].interactive_mw[t] + m.bt[d, t] <= DC[d].cap_it_mw)
            if not job_mode:
                c.add(sum(m.mg[d, e, t] for e in D) <= sc.mig_max_mw)
                if LM is not None:
                    for e in D:
                        if (d, e) in LM: c.add(m.mg[d, e, t] <= LM[(d, e)].bw_mw)
    _soc_meas = ((roll or {}).get("soc_measured") if roll else None) or {}  # {name: MWh}
    _from_meas = int((roll or {}).get("from_t") or 0) if roll else 0
    _soc_end_meas = bool((roll or {}).get("soc_end_use_measured")) if roll else False
    for s, S in STO.items():
        _rf = float(getattr(S, "reserve_frac", 0.0) or 0.0)
        _is_ups = (getattr(S, "kind", "ess") or "ess") == "ups"
        _smin = float(S.soc_min)
        if _is_ups and _rf > 0 and not _emerg:
            _smin = float(S.soc_min) + _rf * (float(S.soc_max) - float(S.soc_min))
        for t in T:
            c.add(m.ch[s, t] <= S.power_mw); c.add(m.dis[s, t] <= S.power_mw)
            c.add(m.soc[s, t] <= S.soc_max*S.energy_mwh); c.add(m.soc[s, t] >= _smin*S.energy_mwh)
            # 实测 SOC：在 from_t 处断开与日前轨迹的硬链接，用测量值作为本小时初值
            if _soc_meas and s in _soc_meas and t == _from_meas and _from_meas > 0:
                prev = float(_soc_meas[s])
            else:
                prev = S.soc0*S.energy_mwh if t == 0 else m.soc[s, t-1]
            c.add(m.soc[s, t] == prev + dt*(S.eta_ch*m.ch[s, t] - m.dis[s, t]/S.eta_dis))
        _end = float(_soc_meas[s]) / max(float(S.energy_mwh), 1e-9) if (_soc_end_meas and s in _soc_meas) else float(S.soc0)
        c.add(m.soc[s, n-1] >= _end*S.energy_mwh)   # 日末 SOC 不低于目标初值（默认同日初）
    from . import thermal as _th
    from .. import power_model as _pm
    from .. import vcc as _vcc
    ITwork = lambda d, t: DC[d].interactive_mw[t] + m.bt[d, t]   # IT 工作功率（容量占用）
    # VCC：日前两阶段 → 先固化 Cap 再约束灵活负荷；joint 在下方与目标一起加入
    _vcc_curves = None; _vcc_extract = None; _vcc_term = 0.0; _vcc_on = False
    if _vcc.active(sc) and optimize and getattr(sc, "vcc_stage", "joint") == "day_ahead":
        _vcc_curves = _vcc.day_ahead_all(sc)
        _vcc.apply_day_ahead_bounds(m, sc, DC, D, T, (lambda d, t: m.bt[d, t]), c, _vcc_curves)
    elif _vcc.active(sc) and optimize:
        _vcc_term, _vcc_extract = _vcc.add_joint(m, sc, DC, D, T, (lambda d, t: m.bt[d, t]), c, optimize)
        _vcc_on = True
    # 硬件功率层（缺省 identity：Pit ≡ ITwork）
    Pit, _pm_info = _pm.add_pyomo_power(m, sc, DC, D, T, ITwork, c, optimize)
    # 热耦合用实际电气 IT 功率作发热；identity 时与旧 ITx 完全一致
    TH = _th.build(m, sc, DC, D, T, Pit, optimize, levers) if _th.active(sc) else None
    LV = TH["levers"] if TH else {**_th.LEVERS_ALL, **(levers or {})}
    elec = TH["elec"] if TH else (lambda d, t: DC[d].pue * Pit(d, t))
    ITx = ITwork  # 兼容下文引用
    # 需求响应基线
    dr_obj, DRE, dr_base = 0, [], {}
    if sc.dr_events and optimize and LV.get("dr", True):
        need = {ev.baseline_method for ev in sc.dr_events}
        prof = {}
        if "plan" in need:
            r0 = solve(sc, True, use_storage, solver_opts, no_migration, levers={**(levers or {}), "dr": False}); prof["plan"] = r0["df"]
        if "bau" in need: prof["bau"] = solve(sc, False, solver_opts=solver_opts)["df"]
        for e, ev in enumerate(sc.dr_events):
            ds = [d for d in D if (not ev.dcs or d in ev.dcs)]
            ss = [x for x in ev.storages if x in STO]
            if ev.baseline_method == "given" and ev.baseline_mw: dr_base[e] = np.array(ev.baseline_mw, float)
            else:
                pdf = prof[ev.baseline_method]; dr_base[e] = pdf[[f"{d}_grid_MW" for d in ds]].sum(axis=1).values
                for x in ss:   # 表后储能：基线关口功率含其净充电（bau 基线无储能列 → 0）
                    if f"{x}_ch" in pdf: dr_base[e] = dr_base[e] + pdf[f"{x}_ch"].values - pdf[f"{x}_dis"].values
        _sn = lambda names, t: sum(m.ch[x, t] - m.dis[x, t] for x in names if x in STO)
        dr_obj, DRE = _th.build_dr(m, sc, DC, D, T, elec, dr_base, LV, stonet=_sn)
    m.gshort = pyo.Var(within=pyo.NonNegativeReals)   # 绿电缺口 MWh（软约束时）
    if sc.min_green_share is not None and D:   # 绿电占比下限（外网购电视为非绿电）
        c.add(dt*sum(m.pg[g, t] for g in G if gens[g]["ext"] for t in T)
              <= dt*(1 - sc.min_green_share)*sum(elec(d, t) for d in D for t in T) + m.gshort)
        if sc.green_shortfall_penalty_cny_mwh is None: m.gshort.fix(0)
    else: m.gshort.fix(0)
    dcload = lambda b, t: sum(elec(d, t) for d in D if DC[d].bus == b)
    stonet = lambda b, t: sum(m.ch[s, t] - m.dis[s, t] for s in STO if STO[s].bus == b)
    flow = lambda l, t: (m.th[fb[l], t] - m.th[tb[l], t]) / xb[l] * BASE_MVA
    for t in T:
        for rb in N["refs"]: c.add(m.th[rb, t] == 0)
        for b in B:
            ex = (sum(m.pg[g, t] - m.gx[g, t] for g in G if gens[g]["bus"] == b) + sum(m.pv[k, t] for k in PV if PVBUS[k] == b)
                  - base_load[b]*lp[t] - dcload(b, t) - stonet(b, t)
                  == sum(flow(l, t) for l in L if fb[l] == b) - sum(flow(l, t) for l in L if tb[l] == b))
            if isinstance(ex, (bool, np.bool_)):   # 空母线（无元件、无支路）：恒等式，跳过；恒不成立则给出可读错误
                if not ex: raise ValueError(f"母线 {b} 功率平衡恒不成立（孤立母线上有固定负荷）")
                continue
            c.add(ex)
        for l in L:
            c.add(flow(l, t) <= rating[l]); c.add(flow(l, t) >= -rating[l])
    deg = 5.0  # 储能循环损耗成本 CNY/MWh（合成），避免同时充放
    # ---- 碳排放（tCO2）：location=数据中心用电×所在区域逐时碳强度；generation=发电侧 ----
    ci_dc = {d: carbon_profile(sc, DC[d].bus) for d in D}
    ci_grid = carbon_profile(sc, gens[0]["bus"])
    gem = [carbon_profile(sc, g["bus"]) if g["ext"] else np.full(n, g["emis"]) for g in gens]
    hn = sc.heat_network; hef = hn.boiler_ef_t_mwh_th if (hn is not None and TH) else 0.0
    _bef = hn.booster_ef_t_mwh_th if (hn is not None and TH and TH.get("HG") is not None and hn.booster == "gas_boiler") else 0.0
    heat_off = lambda t: (hef*m.hdel[t] - _bef*m.hboost[t]) if TH else 0
    emis_loc = lambda t: sum(ci_dc[d][t]*elec(d, t) for d in D) - heat_off(t)
    emis_gen = lambda t: sum(gem[g][t]*m.pg[g, t] for g in G) - heat_off(t)
    emis = emis_loc if sc.carbon_accounting == "location" else emis_gen
    wc = sc.carbon_weight*sc.carbon_price_cny_t
    cost_expr = (dt*(sum(gens[g]["cost"][t]*m.pg[g, t] for g in G for t in T)
                 - sum(gens[g]["excost"][t]*m.gx[g, t] for g in G for t in T if gens[g]["exmax"] > 0)
                 + sc.pv_curtail_penalty*sum(PV[k][t] - m.pv[k, t] for k in PV for t in T)
                 + deg*sum(m.ch[s, t] + m.dis[s, t] for s in STO for t in T)
                 + sum(PVPPA[k]*(PV[k][t] if PVTOP[k] else m.pv[k, t]) for k in PV for t in T if PVPPA[k])
                  ) + sum(gens[g]["dem"]*m.pk[g] for g in G if gens[g].get("dem", 0) > 0)
                 + sc.unserved_penalty_cny_mwh*sum(m.un[j.id] for j in JOBS)
                 + (sc.green_shortfall_penalty_cny_mwh or 0.0)*m.gshort
                 + ((TH["pen"] - TH["heat_rev"]) if TH else 0) + dr_obj)
    # Explicit service costs; unchanged defaults introduce no optimization variables.
    line_fees = {l: sc.network.lines[l].service_fee_cny_mwh for l in L if sc.network_case == "custom" and l < len(sc.network.lines) and sc.network.lines[l].service_fee_cny_mwh > 0}
    line_term = 0
    if line_fees:
        m.flow_abs = pyo.Var(list(line_fees), T, within=pyo.NonNegativeReals)
        for l in line_fees:
            for t in T:
                c.add(m.flow_abs[l,t] >= flow(l,t)); c.add(m.flow_abs[l,t] >= -flow(l,t))
        line_term = dt*sum(line_fees[l]*m.flow_abs[l,t] for l in line_fees for t in T)
    directed = lambda a,b,t: (sum(m.pj[x] for x in mig.get((a,b,t), [])) if job_mode else m.mg[a,b,t])
    fee_links = [link for link in sc.links if link.fee_cny_mwh > 0]
    migration_term = 0
    if fee_links and sc.migration_fee_basis == "net":
        m.migration_abs = pyo.Var(range(len(fee_links)), T, within=pyo.NonNegativeReals)
        for k, link in enumerate(fee_links):
            for t in T:
                signed = directed(link.a,link.b,t)-directed(link.b,link.a,t)
                c.add(m.migration_abs[k,t] >= signed); c.add(m.migration_abs[k,t] >= -signed)
        migration_term = dt*sum(link.fee_cny_mwh*m.migration_abs[k,t] for k,link in enumerate(fee_links) for t in T)
    else:
        migration_term = dt*sum(link.fee_cny_mwh*(directed(link.a,link.b,t)+directed(link.b,link.a,t)) for link in fee_links for t in T)
    rejected_term = sc.unserved_penalty_cny_mwh*sum(m.un[j.id] for j in JOBS)
    value_term = sum(j.value_cny_mwh*(j.energy_mwh-m.un[j.id]) for j in JOBS) if sc.objective_mode == "welfare" else 0
    if sc.objective_mode == "welfare": cost_expr = cost_expr - rejected_term - value_term
    cost_expr = cost_expr + line_term + migration_term + (integer_info["penalty"] if job_mode else 0)
    m.obj = pyo.Objective(expr=cost_expr + (wc*dt*sum(emis(t) for t in T) if wc > 0 else 0) + (_vcc_term if _vcc_on else 0))
    # ---- 三级优化钩子（roll）：默认 None，不影响旧路径 ----
    if roll:
        _from = int(roll.get("from_t") or 0)
        _prior = roll.get("prior")
        _pdf = _prior["df"] if (_prior is not None and "df" in _prior) else None
        _fix_gens = bool(roll.get("fix_gens", True))
        _env_h = roll.get("envelope_hour")
        _env_sense = roll.get("envelope_sense")
        _rt_only = bool(roll.get("rt_storage_only", False))
        def _cell(col, t, default=None):
            if _pdf is None or col not in _pdf.columns: return default
            try: return float(_pdf.loc[int(t), col])
            except Exception: return default
        # 锁定过去小时
        if _pdf is not None and _from > 0:
            for t in range(0, min(_from, 24)):
                for d in D:
                    vbt = _cell(f"{d}_batch_IT", t)
                    if vbt is not None:
                        try: m.bt[d, t].fix(vbt)
                        except Exception: pass
                if bool(roll.get("fix_storage", True)):
                    for s in STO:
                        vc = _cell(f"{s}_ch", t); vd = _cell(f"{s}_dis", t); vs = _cell(f"{s}_soc", t)
                        if vc is not None: m.ch[s, t].fix(max(0.0, vc))
                        if vd is not None: m.dis[s, t].fix(max(0.0, vd))
                        if vs is not None: m.soc[s, t].fix(max(0.0, vs))
                if _fix_gens:
                    for k in PV:
                        vpv = _cell("pv_used", t)
                        # 无法按场站拆分时按可用上限比例近似：用 avail 比例
                        pass
                    for k in PV:
                        # 按比例分配 pv_used
                        pav = float(PV[k][t]); tot = float(sum(PV[j][t] for j in PV)) or 1.0
                        used = _cell("pv_used", t, 0.0) or 0.0
                        m.pv[k, t].fix(max(0.0, min(pav, used * pav / tot)))
                    for g in G:
                        vg = _cell(f"gen{g}_MW", t)
                        if vg is not None: m.pg[g, t].fix(max(0.0, vg))
                        if gens[g]["exmax"] > 0:
                            vx = _cell(f"gen{g}_export_MW", t, 0.0) or 0.0
                            m.gx[g, t].fix(max(0.0, vx))
                if TH and bool(roll.get("fix_thermal", True)):
                    for d in TH.get("TD", []):
                        vt = _cell(f"{d}_Tin_C", t); vm = _cell(f"{d}_Tmass_C", t)
                        if vt is not None:
                            try: m.Ta[d, t].fix(vt)
                            except Exception: pass
                        if vm is not None:
                            try: m.Tm[d, t].fix(vm)
                            except Exception: pass
                        vqc = _cell(f"{d}_chiller_MWth", t); vqf = _cell(f"{d}_free_MWth", t)
                        if vqc is not None:
                            try: m.qch[d, t].fix(max(0.0, vqc))
                            except Exception: pass
                        if vqf is not None:
                            try: m.qfree[d, t].fix(max(0.0, vqf))
                            except Exception: pass
                        vtc = _cell(f"{d}_tes_ch_MWth", t); vtd = _cell(f"{d}_tes_dis_MWth", t); vts = _cell(f"{d}_tes_soc_MWh", t)
                        if vtc is not None:
                            try: m.tes_c[d, t].fix(max(0.0, vtc))
                            except Exception: pass
                        if vtd is not None:
                            try: m.tes_d[d, t].fix(max(0.0, vtd))
                            except Exception: pass
                        if vts is not None:
                            try: m.tes_s[d, t].fix(max(0.0, vts))
                            except Exception: pass
        # 实时可行域：锁全日后仅放开某小时储能
        if _rt_only and _pdf is not None and _env_h is not None:
            hh = int(_env_h)
            for t in T:
                for d in D:
                    vbt = _cell(f"{d}_batch_IT", t)
                    if vbt is not None: m.bt[d, t].fix(vbt)
                if _fix_gens:
                    for k in PV:
                        pav = float(PV[k][t]); tot = float(sum(PV[j][t] for j in PV)) or 1.0
                        used = _cell("pv_used", t, 0.0) or 0.0
                        m.pv[k, t].fix(max(0.0, min(pav, used * pav / tot)))
                    for g in G:
                        vg = _cell(f"gen{g}_MW", t)
                        if vg is not None: m.pg[g, t].fix(max(0.0, vg))
                for s in STO:
                    if t == hh: continue
                    vc = _cell(f"{s}_ch", t); vd = _cell(f"{s}_dis", t); vs = _cell(f"{s}_soc", t)
                    if vc is not None: m.ch[s, t].fix(max(0.0, vc))
                    if vd is not None: m.dis[s, t].fix(max(0.0, vd))
                    if vs is not None: m.soc[s, t].fix(max(0.0, vs))
        # 相对基线偏离罚
        _pen = float(roll.get("dev_penalty_cny_mwh") or 0.0)
        _base = roll.get("baseline_site_mw")
        if _pen > 0 and _base is not None and _env_h is None:
            m.dev_p = pyo.Var(T, within=pyo.NonNegativeReals)
            m.dev_n = pyo.Var(T, within=pyo.NonNegativeReals)
            for t in T:
                if t < _from:
                    m.dev_p[t].fix(0); m.dev_n[t].fix(0)
                else:
                    c.add(m.dev_p[t] - m.dev_n[t] == sum(elec(d, t) for d in D) - float(_base[t]))
            m.obj.expr = m.obj.expr + _pen * sum(m.dev_p[t] + m.dev_n[t] for t in T)
        # 可行域：改目标为该小时站点关口 max/min
        if _env_h is not None and _env_sense in ("max", "min"):
            hh = int(_env_h)
            site_h = sum(elec(d, hh) for d in D)
            m.del_component(m.obj)
            if _env_sense == "max":
                m.obj = pyo.Objective(expr=site_h, sense=pyo.maximize)
            else:
                m.obj = pyo.Objective(expr=site_h, sense=pyo.minimize)
    import time as _time
    so = solver_opts or {}; opt = pyo.SolverFactory("appsi_highs")
    opt.highs_options["primal_feasibility_tolerance"]=1e-7
    if so.get("time_limit_s"): opt.config.time_limit = float(so["time_limit_s"])
    if so.get("mip_gap") is not None:
        try: opt.config.mip_gap = float(so["mip_gap"])
        except Exception: pass
    if not _pm_info.get("milp") and not (job_mode and integer_info["milp"]):
        m.dual = pyo.Suffix(direction=pyo.Suffix.IMPORT)  # MILP（PDU SOS2）无可用对偶
    if job_mode and integer_info["milp"]: opt.highs_options["mip_rel_gap"] = float(so.get("mip_gap") or 0)
    _t0 = _time.time(); res = checked_solve(opt,m,load_solutions=False); _dt = _time.time() - _t0
    tc = str(res.solver.termination_condition)
    _nv = sum(1 for x in m.component_data_objects(pyo.Var, active=True) if not x.fixed)
    _nfix = sum(1 for x in m.component_data_objects(pyo.Var, active=True) if x.fixed)
    _nc = sum(1 for _ in m.component_data_objects(pyo.Constraint, active=True))
    if tc != "optimal":
        hint = "检查容量/批处理量/线路约束是否过紧"
        if sc.min_green_share is not None: hint += f"；已设置绿电占比下限 min_green_share={sc.min_green_share}，当日风光可用电量可能不足"
        import pandapower.topology as _tp
        _used = {int(b) for b in net.ext_grid.bus} | {d.bus for d in sc.data_centers} | {p.bus for p in sc.pv} | {s_.bus for s_ in sc.storage} \
                | {int(b) for b in net.load.bus} | {int(b) for b in net.gen.bus} | {g["bus"] for g in gens}
        if any((set(c) & _used) and not (set(c) & set(int(b) for b in net.ext_grid.bus)) for c in _tp.connected_components(_tp.create_nxgraph(net))):
            hint += "；存在无外网孤岛（离网微网），低风光时段电源/储能可能不足"   # 空母线（无任何元件）不算孤岛
        if sc.thermal_mode == "coupled":
            _df = _th.cooling_deficits(sc, optimize)
            if _df:
                w = max(_df, key=lambda x: x["need_mw"] - x["avail_mw"])
                hint += (f"；冷量不足（设计日预检）：{len({x['dc'] for x in _df})} 个 DC 共 {len(_df)} 个小时可用冷量 < 必须排热，最严重 {w['dc']} {w['hour']} 时"
                         f"（室外 {w['t_out']}°C）可用 {w['avail_mw']} MW < 需 {w['need_mw']} MW → 冷机装机需 ≥ {w['chiller_needed_mw']} MW（现 {w['chiller_cap_mw']}），"
                         "或改干湿联合排热/加蓄冷")
            else: hint += "；热耦合模式：可能入口温度/变化率约束过紧"
            if not optimize: hint += "（基线为定送风温度、无蓄冷/预冷运行）"
        raise RuntimeError(f"{'MILP' if job_mode and integer_info['milp'] else 'LP'} 求解失败: {tc}（{hint}；整数任务请检查required、连续窗口、初始进度和重启等待）" if job_mode and integer_info["milp"] else f"LP 求解失败: {tc}（{hint}）")
    m.solutions.load_from(res)
    try:
        from ..research.binding import analyze as _bind
        _binding = _bind(m)
    except Exception as _e: _binding = [dict(group="对偶分析失败", error=str(_e))]
    cleanup=None
    if sc.migration_cleanup=="lexicographic_gross" and optimize:
        from .migration_cleanup import apply as cleanup_apply
        cleanup=cleanup_apply(m,sc,opt,dt*sum(directed(a,b,t) for a in D for b in D if a!=b for t in T))
    v = pyo.value
    rows = []
    for t in T:
        r = dict(hour=t if dt==1 else t*dt, step=t, duration_h=dt, price=price[t], pv_avail=float(sum(PV[k][t] for k in PV)),
                 pv_used=float(sum(v(m.pv[k, t]) for k in PV)),
                 base_load_MW=float(sum(base_load.values())*lp[t]))
        for d in D:
            r[f"{d}_batch_IT"] = v(m.bt[d, t])
            r[f"{d}_grid_MW"] = float(v(elec(d, t)))
            _work = float(DC[d].interactive_mw[t] + v(m.bt[d, t]))
            r[f"{d}_IT_work_MW"] = _work
            r[f"{d}_IT_MW"] = float(v(Pit(d, t)))  # 电气 IT；identity 时 = work（旧行为）
            r[f"{d}_mig_out"] = sum(v(m.mg[d, e, t]) for e in D)
        for s in STO:
            r[f"{s}_ch"] = v(m.ch[s, t]); r[f"{s}_dis"] = v(m.dis[s, t]); r[f"{s}_soc"] = v(m.soc[s, t])
        for g in G: r[f"gen{g}_MW"] = v(m.pg[g, t])
        for g in G:
            if gens[g]["exmax"] > 0: r[f"gen{g}_export_MW"] = v(m.gx[g, t])
        r["grid_import_MW"] = float(sum(v(m.pg[g, t]) for g in G if gens[g]["ext"]))
        r["grid_export_MW"] = float(sum(v(m.gx[g, t]) for g in G))
        r["fossil_gen_MW"] = float(sum(v(m.pg[g, t]) for g in G if not gens[g]["ext"] and gens[g].get("emis", 1) > 0))
        r["clean_gen_MW"] = float(sum(v(m.pg[g, t]) for g in G if not gens[g]["ext"] and gens[g].get("emis", 1) <= 0))
        r["hour_cost"] = float(sum(gens[g]["cost"][t]*v(m.pg[g, t]) - gens[g]["excost"][t]*v(m.gx[g, t]) for g in G)
                               + sum(PVPPA[k]*(PV[k][t] if PVTOP[k] else v(m.pv[k, t])) for k in PV))
        r["hour_cost"]*=dt
        r["ci_grid_t_mwh"] = float(ci_grid[t])
        r["emis_location_t"] = dt*float(v(emis_loc(t))); r["emis_generation_t"] = dt*float(v(emis_gen(t)))
        if job_mode:
            for d in D: r[f"{d}_mig_out"] = float(sum(v(m.pj[x]) for (h, e, tt), xs in mig.items() if h == d and tt == t for x in xs))
        if TH:
            for d in TH["TD"]:
                th = DC[d].thermal; inf = TH["info"][d]; it = r[f"{d}_IT_MW"]
                ce = float(v(TH["cool_e"](d, t))); hpe = float(v(m.qhp[d, t]))/float(inf["hp_cop"][t])
                r.update({f"{d}_Tin_C": float(v(m.Ta[d, t])), f"{d}_Tmass_C": float(v(m.Tm[d, t])), f"{d}_Tout_C": float(inf["tout"][t]),
                          f"{d}_COP": float(inf["cop"][t]), f"{d}_cool_MW": ce, f"{d}_other_MW": it*th.other_frac,
                          f"{d}_chiller_MWth": float(v(m.qch[d, t])), f"{d}_free_MWth": float(v(m.qfree[d, t])),
                          f"{d}_tes_ch_MWth": float(v(m.tes_c[d, t])), f"{d}_tes_dis_MWth": float(v(m.tes_d[d, t])), f"{d}_tes_soc_MWh": float(v(m.tes_s[d, t])),
                          f"{d}_hp_heat_MWth": float(v(m.qhp[d, t])), f"{d}_hp_MW": hpe,
                          f"{d}_PUE": (it + ce + it*th.other_frac)/max(it, 1e-9), f"{d}_HPCOP": float(inf["hp_cop"][t]),
                          f"{d}_water_m3": dt*float(it*inf["wue"][t]), f"{d}_cool_free_frac": float(inf["free_avail"][t]/max(th.free_cap_mw_th, 1e-9)) if th.free_cap_mw_th > 0 else 0.0,
                          f"{d}_cool_avail_MWth": float(inf["chiller_avail"] + inf["free_avail"][t] + (th.tes_p_mw_th if TH["levers"]["tes"] else 0))})
            r["heat_boost_MWth"] = float(v(m.hboost[t]))
            if TH.get("HG") is not None:
                G_ = TH["HG"]; r.update(heat_T_req_C=float(G_["t_req"][t]), heat_T_plant_C=float(G_["t_plant"][t]), heat_T_ach_C=float(G_["t_ach"][t]),
                                        heat_T_deliver_C=float(G_["t_deliver"][t]), heat_margin_K=float(G_["margin"][t]), heat_f_boost=float(G_["f_boost"][t]))
            r["heat_delivered_MWth"] = float(v(m.hdel[t])); r["heat_store_MWh"] = float(v(m.hs[t]))
            r["heat_charge_MWth"]=float(v(m.hsc[t]));r["heat_discharge_MWth"]=float(v(m.hsd[t]))
            if hn:
                for node in hn.nodes:
                    for col,var in [("del",m.hnode_del),("ch",m.hnode_sc),("dis",m.hnode_sd),("soc",m.hnode_s)]: r[f"heat_node_{node.id}_{col}"]=float(v(var[node.id,t]))
                for pi,pipe in enumerate(hn.pipes): r[f"heat_pipe_{pi}_MWth"]=float(v(m.hpipe[pi,t]))
            r["heat_demand_MWth"] = (float(sum(nd.demand_mw_th[t] for nd in hn.nodes)) if hn.nodes else float(hn.demand_mw_th[t])) if hn is not None else 0.0
            r["heat_offset_t"] = dt*float(hef*v(m.hdel[t]) - _bef*v(m.hboost[t]))
        if DRE:
            r["dr_delivered_MW"] = float(sum(v(m.dr[e, t]) for e in DRE if (e, t) in m.dr))
            r["dr_request_MW"] = float(sum(sc.dr_events[e].request_mw for e in DRE if sc.dr_events[e].start <= t*dt < sc.dr_events[e].end))
            r["dr_baseline_MW"] = float(sum(dr_base[e][t] for e in DRE if sc.dr_events[e].start <= t*dt < sc.dr_events[e].end))
        r["max_line_loading_pct"] = max((abs(v(flow(l, t)))/rating[l]*100 for l in L), default=0.0)
        rows.append(r)
    df = pd.DataFrame(rows)
    emissions = float(df.emis_location_t.sum() if sc.carbon_accounting == "location" else df.emis_generation_t.sum())
    carbon_term = wc*emissions
    out = dict(optimize=optimize, storage=list(STO), gens=[{k: (x.tolist() if hasattr(x, "tolist") else x) for k, x in g.items()} for g in gens], objective=v(m.obj), gen_cost=float(df.hour_cost.sum()),
               curtail_mwh=dt*float((df.pv_avail-df.pv_used).sum()), df=df, emissions_t=emissions,
               cost_cny=float(v(m.obj)) - carbon_term + (float(v(value_term)) if sc.objective_mode=="welfare" else 0.0),
               unserved_penalty_cny=float(sc.unserved_penalty_cny_mwh*sum(v(m.un[j.id]) for j in JOBS)) if sc.objective_mode == "cost" else 0.0,
               curtail_penalty_cny=float(sc.pv_curtail_penalty*dt*float((df.pv_avail-df.pv_used).sum())), carbon_term_cny=carbon_term, carbon_weight=sc.carbon_weight,
               carbon_accounting=sc.carbon_accounting,
               ppa_cost_cny=dt*float(sum(PVPPA[k]*(PV[k][t] if PVTOP[k] else v(m.pv[k, t])) for k in PV for t in T)),
               demand_charge_cny=float(sum(gens[g]["dem"]*v(m.pk[g]) for g in G if gens[g].get("dem", 0) > 0)))
    try: _bound = float(res.problem.lower_bound)
    except Exception: _bound = None
    _obj = float(v(m.obj))
    out["solver"] = dict(name="HiGHS (appsi_highs, Pyomo)", problem="LP（线性规划，连续变量）", status=tc, objective=_obj,
                         bound=_bound, gap_pct=(abs(_obj - _bound)/max(abs(_obj), 1e-9)*100 if _bound is not None and np.isfinite(_bound) else 0.0),
                         time_s=round(_dt, 3), n_vars=_nv, n_fixed_vars=_nfix, n_constraints=_nc, hours=sc.hours, steps=n, resolution_h=dt,
                         time_limit_s=so.get("time_limit_s"), no_migration=no_migration)
    out["migration_cleanup"] = cleanup
    out["binding"] = _binding
    out["time_axis"] = dict(duration_h=sc.hours, dt_hours=dt, steps=n, indices="step", hour="physical elapsed hours", rate_units="MW", integration="energy=MW*dt; emissions/cost interval-integrated; ramp per physical hour", unsupported=["15min VCC", "15min/integer three-tier rolling", "15min annual investment", "15min market sandbox"])
    if job_mode and integer_info["milp"]:
        out["integer_tasks"]=integer_info["extract"](v)
        out["solver"]["problem"]="MILP（整数连续任务/取消重启）"
    out["n_storage_used"] = len(STO)
    # UPS / 柴发透明摘要（默认空；有资源时填）
    out["ups"] = [{"name": s, "kind": getattr(STO[s], "kind", "ess"), "energy_mwh": float(STO[s].energy_mwh),
                   "power_mw": float(STO[s].power_mw), "eta_ch": float(STO[s].eta_ch), "eta_dis": float(STO[s].eta_dis),
                   "soc0": float(STO[s].soc0), "soc_min": float(STO[s].soc_min), "soc_max": float(STO[s].soc_max),
                   "reserve_frac": float(getattr(STO[s], "reserve_frac", 0.0) or 0.0),
                   "source_note": getattr(STO[s], "source_note", "") or "",
                   "discharge_mwh": dt*float(df[f"{s}_dis"].sum()) if f"{s}_dis" in df.columns else 0.0,
                   "charge_mwh": dt*float(df[f"{s}_ch"].sum()) if f"{s}_ch" in df.columns else 0.0}
                  for s in STO if (getattr(STO[s], "kind", "ess") or "ess") == "ups"]
    out["diesel"] = []
    for gi, g in enumerate(gens):
        if (g.get("kind") or "") != "diesel":
            continue
        col = f"gen{gi}_MW"
        series = [float(x) for x in df[col].values] if col in df.columns else []
        out["diesel"].append({"name": g.get("name"), "bus": g.get("bus"), "pmax_mw": g.get("pmax"), "pmin_mw": g.get("pmin"),
                              "ramp_mw_h": g.get("ramp"), "cost_cny_mwh": float(g["cost"][0]) if hasattr(g.get("cost"), "__getitem__") else g.get("cost"),
                              "emission_t_mwh": g.get("emis"), "dispatch_mode": g.get("dispatch_mode"),
                              "source_note": g.get("source_note") or "", "energy_mwh": dt*float(sum(series)),
                              "peak_mw": float(max(series) if series else 0.0), "hours_on": dt*sum(1 for x in series if x > 1e-6),
                              "series_mw": series})
    out["emergency_mode"] = bool(_emerg)
    if _soc_meas:
        out["soc_measured_mwh"] = {k: float(v) for k, v in _soc_meas.items()}
    out["cost_terms"] = dict(   # 目标函数逐项（元/日），合计 = objective
        grid_purchase=dt*float(sum(gens[g]["cost"][t]*v(m.pg[g, t]) for g in G for t in T if gens[g]["ext"])),
        local_gen=dt*float(sum(gens[g]["cost"][t]*v(m.pg[g, t]) for g in G for t in T if not gens[g]["ext"])),
        export_revenue=-float(sum(gens[g]["excost"][t]*v(m.gx[g, t]) for g in G for t in T if gens[g]["exmax"] > 0)),
        curtail_penalty=dt*float(sc.pv_curtail_penalty*sum(PV[k][t] - v(m.pv[k, t]) for k in PV for t in T)),
        storage_degradation=dt*float(deg*sum(v(m.ch[s, t]) + v(m.dis[s, t]) for s in STO for t in T)),
        ppa=out["ppa_cost_cny"], demand_charge=out["demand_charge_cny"], unserved_penalty=out["unserved_penalty_cny"],
        carbon=float(carbon_term))
    if line_fees: out["cost_terms"]["physical_line_service"] = float(v(line_term))
    if fee_links: out["cost_terms"]["migration_service"] = float(v(migration_term))
    if sc.objective_mode == "welfare": out["cost_terms"]["admitted_demand_value"] = -float(v(value_term))
    if job_mode and integer_info["milp"]: out["cost_terms"]["cancellation"] = float(v(integer_info["penalty"]))
    if TH:
        out["cost_terms"]["thermal_penalty"] = float(v(TH["pen"])); out["cost_terms"]["heat_revenue"] = -float(v(TH["heat_rev"]))
        out["thermal"] = thermal_summary(sc, df, TH, m, hn)
    if DRE:
        out["cost_terms"]["dr_revenue"] = float(v(dr_obj))
        out["dr"] = [dict(name=sc.dr_events[e].name, kind=sc.dr_events[e].kind, start=sc.dr_events[e].start, end=sc.dr_events[e].end,
                          request_mw=sc.dr_events[e].request_mw, price_cny_mwh=sc.dr_events[e].price_cny_mwh, baseline_method=sc.dr_events[e].baseline_method,
                          baseline_mw=[round(float(dr_base[e][t]), 3) for t in event_steps(sc,sc.dr_events[e])],
                          delivered_mw=[round(float(v(m.dr[e, t])), 3) for t in event_steps(sc,sc.dr_events[e])],
                          delivered_mwh=round(dt*float(sum(v(m.dr[e, t]) for t in event_steps(sc,sc.dr_events[e]))), 3),
                          requested_mwh=round(sc.dr_events[e].request_mw*(sc.dr_events[e].end - sc.dr_events[e].start), 3),
                          revenue_cny=round(dt*float(sc.dr_events[e].price_cny_mwh*sum(v(m.dr[e, t]) for t in event_steps(sc,sc.dr_events[e]))), 1))
                     for e in DRE]
    out["levers"] = LV; out["thermal_mode"] = sc.thermal_mode if TH else "constant_pue"
    out["power_model"] = {d: _pm.describe(DC[d]) for d in D}
    if _pm_info.get("milp"): out["solver"]["problem"] = "MILP（PDU 分段线性 SOS2）"
    # VCC 结果
    if _vcc_curves is not None:
        out["vcc"] = _vcc.summarize(_vcc_curves); out["vcc"]["curves"] = _vcc_curves
    elif _vcc_extract is not None:
        _vc = _vcc_extract(v); out["vcc"] = _vcc.summarize(_vc); out["vcc"]["curves"] = _vc
        out["cost_terms"]["vcc_shaping"] = float(v(_vcc_term) if _vcc_on else 0.0)
    else:
        out["vcc"] = None
    if job_mode:
        jr = []
        for j in JOBS:
            xs = by_j[j.id]; served = j.energy_mwh-float(v(m.un[j.id])); migr = dt*sum(v(m.pj[x]) for x in xs if x[1] != j.dc)
            hrs = [x[2] for x in xs if v(m.pj[x]) > 1e-6]
            jr.append(dict(job=j.id, home=j.dc, release=j.release, deadline=j.deadline, energy_mwh=j.energy_mwh,
                           served_mwh=round(served, 4), unserved_mwh=round(float(v(m.un[j.id])), 4),
                           finish_hour=dt*(max(hrs) + 1) if hrs else None, migrated_mwh=round(migr, 4),
                           sites=",".join(sorted({x[1] for x in xs if v(m.pj[x]) > 1e-6})),
                           latency_sensitive=j.max_latency_ms is not None,
                           met_deadline=bool(v(m.un[j.id]) <= 1e-4)))
        out["jobs"] = pd.DataFrame(jr)
        lk = []
        for (h, e, t), xs in mig.items():
            f = sum(v(m.pj[x]) for x in xs)
            if f > 1e-6: lk.append(dict(src=h, dst=e, hour=t, mw=f, cap_mw=LM[(h, e)].bw_mw if LM else None,
                                        latency_ms=LM[(h, e)].latency_ms if LM else None))
        out["links"] = pd.DataFrame(lk, columns=["src", "dst", "hour", "mw", "cap_mw", "latency_ms"])
        out["mig_energy_mwh"] = dt*float(kappa*df[[f"{d}_mig_out" for d in D]].sum().sum())
    else:
        out["mig_energy_mwh"] = dt*float(kappa*df[[f"{d}_mig_out" for d in D]].sum().sum())
    eligible=set(JX)
    allocation_value=lambda jid,d,t: float(v(m.pj[jid,d,t])) if (jid,d,t) in eligible else 0.0
    out["allocations"] = [dict(job=j.id, origin=j.dc, destination=d, hour=t if dt==1 else t*dt, step=t, duration_h=dt,eligible=(j.id,d,t) in eligible,
        it_mw=allocation_value(j.id,d,t), energy_mwh=dt*allocation_value(j.id,d,t), value_cny_mwh=j.value_cny_mwh) for j in JOBS for d in D for t in window(sc,j)]
    out["job_admission"] = [dict(job=j.id, origin=j.dc, offered_mwh=j.energy_mwh,
        served_mwh=float(j.energy_mwh-v(m.un[j.id])), unserved_mwh=float(v(m.un[j.id])), value_cny_mwh=j.value_cny_mwh) for j in JOBS]
    out["migration_audit"] = []
    for link in sc.links:
        for t in T:
            fw=dt*float(v(directed(link.a,link.b,t))); bw=dt*float(v(directed(link.b,link.a,t)))
            amount=fw+bw if sc.migration_fee_basis == "gross" else abs(fw-bw)
            out["migration_audit"].append(dict(src=link.a,dst=link.b,hour=t if dt==1 else t*dt,step=t,duration_h=dt,forward_mwh=fw,reverse_mwh=bw,
                gross_mwh=fw+bw,signed_net_mwh=fw-bw,abs_net_mwh=abs(fw-bw),directional_cap_mw=link.bw_mw,
                fee_basis=sc.migration_fee_basis,fee_cny_mwh=link.fee_cny_mwh,cost_cny=amount*link.fee_cny_mwh))
    out["network_mapping"] = dict(domain=sc.network_domain, base_mva=BASE_MVA, angle_unit="radian", angle_bounds_rad=None if sc.network_domain == "paper_abstract" else [-float(np.pi),float(np.pi)], refs=list(N["refs"]),
        branches=[dict(branch=int(l),from_bus=int(fb[l]),to_bus=int(tb[l]),x_tap_pu=float(xb[l]),b_mw_per_rad=float(BASE_MVA/xb[l]),rating_mw=float(rating[l]),
            x_ohm=(sc.network.lines[l].x_ohm_per_km*sc.network.lines[l].length_km/sc.network.lines[l].parallel) if sc.network_case=="custom" and l<len(sc.network.lines) else None,
            service_fee_cny_mwh=float(line_fees.get(l,0))) for l in L])
    out["network_dispatch"] = [dict(hour=t if dt==1 else t*dt,step=t,duration_h=dt,theta_rad=[float(v(m.th[b,t])) for b in B],flow_mw=[float(v(flow(l,t))) for l in L]) for t in T]
    out["market_clearing"] = dict(objective_mode=sc.objective_mode,migration_fee_basis=sc.migration_fee_basis,
        admitted_value_cny=float(v(value_term)),physical_line_service_cny=float(v(line_term)),migration_service_cny=float(v(migration_term)),
        welfare_cny=-float(v(m.obj)) if sc.objective_mode=="welfare" else None)
    if TH and hn:
        from ..heat_audit import boundary_audit
        out['heat_boundary_audit']=boundary_audit(sc,df,(TH.get('HG') or {}).get('loss'),TH['HD'])
    if TH and hn and hn.nodes:
        out["heat_network_audit"]=[]
        for pi,pipe in enumerate(hn.pipes):
            delay=int(round(pipe.delay_h/dt));series=[float(v(m.hpipe[pi,t])) for t in T]
            sent=dt*sum(series);arrived=dt*(1-pipe.loss)*sum(series[:max(0,n-delay)])
            transit=dt*(1-pipe.loss)*sum(series[max(0,n-delay):]) if delay else 0.
            out["heat_network_audit"].append(dict(pipe=pipe.name or str(pi),delay_h=pipe.delay_h,delay_steps=delay,initial_in_transit_mwh=0.,sent_mwh=sent,pipe_loss_mwh=pipe.loss*sent,delivered_mwh=arrived,arrived_mwh=arrived,boundary="pipe outlet before node storage/use; delivered_mwh legacy alias of arrived_mwh",end_in_transit_mwh=transit,conservation_residual_mwh=sent-pipe.loss*sent-arrived-transit))
    if sc.lifecycle_enabled:
        vre_hour=[dt*float(sum(v(m.pv[k,t])*(sc.pv[k].lifecycle_tco2e_mwh_profile[t] if sc.pv[k].lifecycle_tco2e_mwh_profile is not None else sc.pv[k].lifecycle_tco2e_mwh) for k in PV)) for t in T]
        embodied=sc.lifecycle_embodied_t_per_year*24/sc.lifecycle_year_hours
        operational=float(df.emis_generation_t.sum())
        counterfactual=None
        if sc.lifecycle_counterfactual=="jobs_origin_uniform":
            counterfactual=dt*sum(float(ci_dc[d][t])*DC[d].pue*(DC[d].interactive_mw[t]+sum(j.energy_mwh/(j.deadline-j.release) for j in JOBS if j.dc==d and j.release<=t<j.deadline)) for d in D for t in T)
        life=operational+sum(vre_hour)+embodied
        out["lifecycle_ledger"] = dict(unit="tCO2e",accounting="generation_operations_plus_vre_lifecycle_plus_annualized_construction",changes_objective=False,
            operational_generation_t=operational,legacy_location_t=float(df.emis_location_t.sum()),vre_lifecycle_t=sum(vre_hour),vre_lifecycle_hourly_t=vre_hour,
            construction_allocated_t=embodied,construction_annual_t=sc.lifecycle_embodied_t_per_year,year_hours=sc.lifecycle_year_hours,total_t=life,
            counterfactual_basis=sc.lifecycle_counterfactual,counterfactual_t=counterfactual,net_avoided_t=counterfactual-life if counterfactual is not None else None)
    return out

def ac_check(sc: Scenario, result: dict, hour: float | None = None):
    dt=sc.dt_hours
    if sc.network_domain == "paper_abstract": raise ValueError("paper_abstract 不适用交流物理校核；请切回 physical 并提供真实参数")
    N = prepare_network(sc); net = N["net"]; nl, rating = N["nl"], N["rating"]
    od = result["df"]; lp = load_profile(sc)*sc.load_scale
    dccols = [c for c in od if c.endswith("_grid_MW")]
    sto = result["storage"]
    if hour is None:
        tot = od.base_load_MW + od[dccols].sum(axis=1) + sum(od[f"{s}_ch"]-od[f"{s}_dis"] for s in sto)
        hour = int(np.argmax(tot.values))
    else: hour=boundary(sc,hour)
    if not 0<=hour<sc.n_steps: raise ValueError("AC物理时刻超出日内")
    acn = copy.deepcopy(net)
    acn.load["p_mw"] *= lp[hour]; acn.load["q_mvar"] *= lp[hour]
    for d in sc.data_centers:
        p = od.loc[hour, f"{d.name}_grid_MW"]
        pp.create_load(acn, d.bus, p_mw=p, q_mvar=d.pf_q_ratio*p, name=d.name)
    for s in sc.storage:
        if s.name in sto:
            pp.create_load(acn, s.bus, p_mw=od.loc[hour, f"{s.name}_ch"]-od.loc[hour, f"{s.name}_dis"], q_mvar=0, name=s.name)
    n_ext = len(net.ext_grid)
    cg = sc.network.gens if (sc.network_case == "custom" and sc.network) else []
    import pandapower.topology as top
    has_slack = set(int(b) for b in net.ext_grid.bus); slack_gens = set()
    for comp in top.connected_components(top.create_nxgraph(acn)):
        if has_slack & set(comp): continue
        idx = [i for i, g in enumerate(cg) if g.bus in comp]
        if idx:   # 孤岛：最大可调度电源作平衡机
            i = max(idx, key=lambda i: cg[i].pmax_mw); pp.create_ext_grid(acn, cg[i].bus, name=f"{cg[i].name}(孤岛平衡)")
            has_slack.add(cg[i].bus); slack_gens.add(i)
        else:      # 仅风光储：储能（构网型）母线作虚拟平衡点
            sb = next((s.bus for s in sc.storage if s.bus in comp), min(comp)); pp.create_ext_grid(acn, sb, name="孤岛虚拟平衡(构网型储能)")
    for i, g in enumerate(cg):
        p = float(od.loc[hour, f"gen{n_ext + len(net.gen) + i}_MW"])
        if i in slack_gens: continue
        if g.vm_pu is not None: pp.create_gen(acn, g.bus, p_mw=p, vm_pu=g.vm_pu, name=g.name)
        elif p > 1e-6: pp.create_sgen(acn, g.bus, p_mw=p, name=g.name)
    pvbus = {}
    for p in sc.pv:
        prof = np.array(p.profile) if p.profile else np.repeat(pv_shape(),int(round(1/dt)))
        pvbus[p.bus] = pvbus.get(p.bus, 0) + p.cap_mw*prof[hour]
    share = od.loc[hour, "pv_used"]/max(od.loc[hour, "pv_avail"], 1e-6)
    for b, pa in pvbus.items(): pp.create_sgen(acn, b, p_mw=pa*share)
    for i in range(len(net.gen)): acn.gen.loc[i, "p_mw"] = od.loc[hour, f"gen{i+n_ext}_MW"]
    acn.line["max_i_ka"] = rating[:nl]/(np.sqrt(3)*acn.bus.vn_kv[acn.line.from_bus].values)/acn.line["parallel"].values
    pp.runpp(acn)
    tl = (np.hypot(acn.res_trafo.p_hv_mw, acn.res_trafo.q_hv_mvar)/rating[nl:]*100)
    line_peak = float(acn.res_line.loading_percent.max()) if len(acn.res_line) else 0.0
    trafo_peak = float(tl.max()) if len(tl) else 0.0
    vm = acn.res_bus.vm_pu
    result['_vm'] = vm.values.tolist()
    return dict(hour=hour if dt==1 else hour*dt, step=hour, duration_h=dt, converged=bool(acn.converged), vmin_pu=float(vm.min()), vmax_pu=float(vm.max()),
                vmin_bus=int(vm.idxmin()), max_line_loading_pct=line_peak,
                max_trafo_loading_pct=trafo_peak,
                max_branch_loading_pct=float(max(line_peak, trafo_peak)),
                dcopf_pred_loading_pct=float(od.loc[hour, "max_line_loading_pct"]),
                slack_p_mw=float(acn.res_ext_grid.p_mw.iloc[0]),
                ext_grid_p_mw={str(acn.ext_grid.name.iloc[i] or i): round(float(acn.res_ext_grid.p_mw.iloc[i]), 2) for i in range(len(acn.ext_grid))},
                line_loading_pct={str(acn.line.name.iloc[i] or i): round(float(acn.res_line.loading_percent.iloc[i]), 1) for i in range(nl)},
                bus_vm_pu={str(acn.bus.name.iloc[i] or i): round(float(vm.iloc[i]), 4) for i in range(len(acn.bus))},
                line_p_from_mw={str(acn.line.name.iloc[i] or i): round(float(acn.res_line.p_from_mw.iloc[i]), 2) for i in range(nl)},
                trafo_p_hv_mw={str(acn.trafo.name.iloc[i] or i): round(float(acn.res_trafo.p_hv_mw.iloc[i]), 2) for i in range(len(acn.trafo))},
                trafo_loading_pct={str(acn.trafo.name.iloc[i] or i): round(float(tl.iloc[i]), 1) for i in range(len(acn.trafo))},
                losses_mw=round(float(acn.res_line.pl_mw.sum() + acn.res_trafo.pl_mw.sum()), 3),
                voltage_ok=bool(vm.min() >= 0.94 and vm.max() <= 1.10),
                loading_ok=bool(max(line_peak, trafo_peak) <= 100))


def thermal_summary(sc, df, TH, m, hn):
    """热安全/动态 PUE/能量平衡核查（电-热）。"""
    dt=sc.dt_hours
    v = pyo.value; DC = {d.name: d for d in sc.data_centers}; S = {}
    for d in TH["TD"]:
        th = DC[d].thermal; tin = df[f"{d}_Tin_C"]; pue = df[f"{d}_PUE"]
        it = df[f"{d}_IT_MW"]; cav = df[f"{d}_cool_avail_MWth"]
        # 空气节点热平衡残差（MW_th）
        res = []
        for t in range(sc.n_steps):
            prev = th.t0_c if t == 0 else tin[t-1]
            qroom = df[f"{d}_chiller_MWth"][t] - df[f"{d}_tes_ch_MWth"][t] + df[f"{d}_free_MWth"][t] + df[f"{d}_tes_dis_MWth"][t] + df[f"{d}_hp_heat_MWth"][t]*(1 - 1/df[f"{d}_HPCOP"][t])
            res.append(th.c_air_mwh_k*(tin[t] - prev)/dt - (it[t]*(1 + th.other_frac*0.5) - qroom - th.ua_am_mw_k*(tin[t] - df[f"{d}_Tmass_C"][t]) + th.ua_env_mw_k*(df[f"{d}_Tout_C"][t] - tin[t])))
        ramp = np.abs(np.diff(np.r_[th.t0_c, tin.values]))/dt
        viol = []
        if tin.max() > th.t_allow_max_c + 1e-5: viol.append(f"入口温度 {tin.max():.2f}°C > 允许上限 {th.t_allow_max_c}")
        if tin.min() < th.t_min_c - 1e-5: viol.append(f"入口温度 {tin.min():.2f}°C < 下限 {th.t_min_c}")
        if ramp.max() > th.ramp_max_k_h + 1e-5: viol.append(f"温升速率 {ramp.max():.2f} K/h 超限")
        if (df[f"{d}_chiller_MWth"] > _chav(th) + 1e-5).any(): viol.append("冷机出力超过 N+1 可用冷量")
        hrs_rec = dt*float((tin > th.t_rec_max_c + 1e-4).sum())
        bind = dict(t_allow_max=int((tin >= th.t_allow_max_c - 1e-4).sum()), t_min=int((tin <= th.t_min_c + 1e-4).sum()),
                    ramp=int((ramp >= th.ramp_max_k_h - 1e-4).sum()), chiller_n1=int((df[f"{d}_chiller_MWth"] >= _chav(th) - 1e-4).sum()),
                    it_vs_cooling=int((it >= cav - 1e-4).sum()))
        bind={key:dt*value for key,value in bind.items()}
        tot = df[f"{d}_grid_MW"].sum()
        S[d] = dict(tin_min_c=round(float(tin.min()), 2), tin_max_c=round(float(tin.max()), 2), margin_to_allow_k=round(float(th.t_allow_max_c - tin.max()), 2),
                    margin_to_rec_k=round(float(th.t_rec_max_c - tin.max()), 2), hours_above_rec=hrs_rec, max_ramp_k_h=round(float(ramp.max()), 2),
                    pue_min=round(float(pue.min()), 3), pue_max=round(float(pue.max()), 3), pue_avg=round(float((df[f"{d}_IT_MW"] + df[f"{d}_cool_MW"] + df[f"{d}_other_MW"]).sum()/it.sum()), 3),
                    cooling_mwh=round(dt*float(df[f"{d}_cool_MW"].sum()), 2), it_mwh=round(dt*float(it.sum()), 2), elec_mwh=round(dt*float(tot), 2),
                    hp_heat_mwh=round(dt*float(df[f"{d}_hp_heat_MWth"].sum()), 2), hp_elec_mwh=round(dt*float(df[f"{d}_hp_MW"].sum()), 2),
                    free_cooling_mwh=round(dt*float(df[f"{d}_free_MWth"].sum()), 2), tes_discharge_mwh=round(dt*float(df[f"{d}_tes_dis_MWth"].sum()), 2),
                    min_cool_margin_mw=round(float((cav - it).min()), 2), binding_hours=bind, violations=viol,
                    thermal_balance_max_residual=float(np.max(np.abs(res))),
                    water_m3=round(float(df[f"{d}_water_m3"].sum()), 1), wue_l_kwh=round(float(df[f"{d}_water_m3"].sum()/max(dt*it.sum(), 1e-9)), 3),
                    cooling=_cool_report(th, it, tin, DC[d].cap_it_mw), hp_cop_min=round(float(df[f"{d}_HPCOP"].min()), 2), hp_cop_max=round(float(df[f"{d}_HPCOP"].max()), 2),
                    elec_balance_max_residual=float(np.max(np.abs(df[f"{d}_grid_MW"] - (it*(1 + th.other_frac) + df[f"{d}_cool_MW"] + df[f"{d}_hp_MW"])))))
    H = None
    if hn is not None and TH["HD"]:
        dl = df["heat_delivered_MWth"]; hp = sum(df[f"{d}_hp_heat_MWth"] for d in TH["HD"]) if TH["HD"] else 0*dl
        _HG = TH.get("HG"); _loss = float(_HG["loss"]) if _HG is not None else hn.pipe_loss   # 余热品位模型：管损随长度、补热也进管网（诊断模块发现旧校核漏算）
        hp = hp + (df["heat_boost_MWth"] if _HG is not None else 0)
        multi = bool(TH.get("_heat_multi") or (getattr(hn, "nodes", None) and len(hn.nodes) > 0))
        if multi:
            H = dict(delivered_mwh=round(dt*float(dl.sum()), 2), demand_mwh=round(dt*sum(sum(node.demand_mw_th) for node in hn.nodes), 2),
                     revenue_cny=round(dt*float(hn.price_cny_mwh_th*dl.sum()), 1),
                     carbon_offset_t=round(float(df["heat_offset_t"].sum()), 2),
                     boost_mwh=round(dt*float(df["heat_boost_MWth"].sum()), 2),
                     multi_node=True, n_nodes=len(hn.nodes), n_pipes=len(hn.pipes or []),
                     balance_max_residual=max((abs(float(pyo.value(c.body))-float(pyo.value(c.lower))) for c in m.thc.values() if c.equality),default=0.), note="多节点：实际热等式残差；管段在途存量单列，不伪报0；详见逐节点/管段导出")
        else:
            H = dict(delivered_mwh=round(dt*float(dl.sum()), 2), demand_mwh=round(dt*float(sum(hn.demand_mw_th)), 2), revenue_cny=round(dt*float(hn.price_cny_mwh_th*dl.sum()), 1),
                     carbon_offset_t=round(float(df["heat_offset_t"].sum()), 2), pipe_loss_mwh=round(dt*float(_loss*np.sum(hp)), 2),
                     boost_mwh=round(dt*float(df["heat_boost_MWth"].sum()), 2),
                     balance_max_residual=float(np.max(np.abs((1 - _loss)*np.asarray(hp) - np.diff(np.r_[hn.storage_soc0*hn.storage_mwh_th if hn.storage_mwh_th > 0 else 0, df["heat_store_MWh"].values])/dt - dl - (np.r_[hn.storage_soc0*hn.storage_mwh_th if hn.storage_mwh_th > 0 else 0, df["heat_store_MWh"].values[:-1]]*(1-(1-hn.storage_loss_h)**dt)/dt if hn.storage_mwh_th > 0 else 0)))))
    if H is not None and TH.get("HG") is not None:
        from .heat_grade import verdict
        G_ = TH["HG"]; pr = np.asarray(sc.price_cny_kwh)*1000 + sc.grid_markup_cny_mwh
        hpe = sum(df[f"{d}_hp_MW"] for d in TH["HD"]); bst = df["heat_boost_MWth"]
        elec_b = bst if hn.booster == "electric" else 0*bst
        hp_cost = dt*float(((hpe + elec_b)*pr).sum()); b_cost = dt*float(hn.booster_price_cny_mwh_th*bst.sum()) if hn.booster == "gas_boiler" else 0.0
        ci = float(df["ci_grid_t_mwh"].mean())
        b_ef = dt*float(hn.booster_ef_t_mwh_th*bst.sum()) if hn.booster == "gas_boiler" else dt*float(ci*bst.sum())
        V = verdict(hn, G_, dt*float(dl.sum()), dt*float((hpe + elec_b).sum()), hp_cost, dt*float(bst.sum()), b_cost, b_ef, ci, dt*float(np.sum(hp)))
        V["t_src_c"] = round(float(G_["t_src"]), 1)
        H.update(feasibility=V, terminal_type=hn.terminal_type, pipe_length_km=hn.pipe_length_km,
                 t_req_c=[round(float(x), 1) for x in G_["t_req"]], t_deliver_c=[round(float(x), 1) for x in G_["t_deliver"]],
                 heat_cost_cny_gj=V["heat_cost_cny_gj"], min_margin_k=V["min_margin_k"])
    allv = [f"{d}: {x}" for d in S for x in S[d]["violations"]]
    return dict(dcs=S, heat=H, violations=allv, safe=not allv)

def _cool_report(th, it, tin, cap):
    from .cooling import safety_report
    try: return safety_report(th, it.values, tin.values, cap)
    except Exception: return {}

def _chav(th):
    from .thermal import chiller_avail
    return chiller_avail(th)
