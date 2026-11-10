"""模型拓扑编辑：对会话场景（Scenario）做元素级 增/改/删、布局、撤销/重做、校验、重新仿真对比。
元素类型 type：bus/line/trafo/grid/gen/load/re(风/光)/ess/dc/link；key：索引（bus/line/trafo/grid/gen/load/re/link）或名称（ess/dc）。
IEEE14 场景首次编辑网络时自动转换为等值自定义网络（network_case='custom'），保持调度结果一致。"""
from __future__ import annotations
import copy, json
import numpy as np
import networkx as nx
from ..scenario import (DCThermal, HeatNetwork, Scenario, NetBus, NetLine, NetTrafo, NetExtGrid, NetGen, NetLoad, PV, Storage, DataCenter, Link, CustomNetwork, H)
from . import sdco_engine as eng

TYPES = {"bus": "母线", "line": "线路", "trafo": "变压器", "grid": "外网购电点", "gen": "可调度电源", "load": "常规负荷",
         "re": "风电/光伏", "wind": "风电", "pv": "光伏", "ess": "储能", "dc": "数据中心", "link": "算力迁移链路",
         "thermal": "热管理/冷却系统", "heatnet": "区域供热网"}
NET_TYPES = {"bus", "line", "trafo", "grid", "gen", "load"}

# ---------------- IEEE14 -> 自定义网络 ----------------
def to_custom(sc: Scenario) -> Scenario:
    if sc.network_case == "custom": return sc
    N = eng.prepare_network(sc); net = N["net"]; rating = N["rating"]
    buses = [NetBus(name=f"Bus {i}", vn_kv=float(r.vn_kv)) for i, r in net.bus.iterrows()]
    lines = [NetLine(name=f"L{i}", from_bus=int(r.from_bus), to_bus=int(r.to_bus), length_km=float(r.length_km), r_ohm_per_km=float(r.r_ohm_per_km),
                     x_ohm_per_km=float(r.x_ohm_per_km), c_nf_per_km=float(r.c_nf_per_km), rating_mva=float(rating[i]), parallel=int(r.parallel))
             for i, r in net.line.iterrows()]
    nl = len(lines)
    trafos = [NetTrafo(name=f"T{i}", hv_bus=int(r.hv_bus), lv_bus=int(r.lv_bus), sn_mva=float(rating[nl + i]),
                       vk_percent=float(r.vk_percent)*float(rating[nl + i])/float(r.sn_mva), vkr_percent=max(float(r.vkr_percent), 0.0)*float(rating[nl + i])/float(r.sn_mva), parallel=int(r.parallel))
              for i, r in net.trafo.iterrows()]
    egs = [NetExtGrid(bus=int(r.bus), name=str(r["name"] or "grid"), vm_pu=float(r.vm_pu)) for _, r in net.ext_grid.iterrows()]
    gens = [NetGen(name=f"G{i}@Bus{int(r.bus)}", bus=int(r.bus), kind="thermal", pmax_mw=float(r.max_p_mw), pmin_mw=sc.gen_min_share*float(r.max_p_mw),
                   cost_cny_mwh=float(sc.gen_cost[i % len(sc.gen_cost)]), emission_t_mwh=float(sc.gen_emission_t_mwh[i % len(sc.gen_emission_t_mwh)]), vm_pu=float(r.vm_pu))
            for i, r in net.gen.iterrows()]
    loads = [NetLoad(name=f"负荷@Bus{int(r.bus)}", bus=int(r.bus), p_mw=float(r.p_mw), q_mvar=float(r.q_mvar)) for _, r in net.load.iterrows()]
    out = sc.model_copy(deep=True)
    out.network_case = "custom"
    out.network = CustomNetwork(buses=buses, lines=lines, trafos=trafos, ext_grids=egs, gens=gens, loads=loads,
                                note="由 IEEE14 转换（编辑器）；线路额定沿用引擎假设值")
    return out

# ---------------- 元素访问 ----------------
def _list(sc, typ):
    if typ in NET_TYPES:
        nw = sc.network
        return {"bus": nw.buses, "line": nw.lines, "trafo": nw.trafos, "grid": nw.ext_grids, "gen": nw.gens, "load": nw.loads}[typ]
    return {"re": sc.pv, "ess": sc.storage, "dc": sc.data_centers, "link": sc.links}[typ]

MODELS = {"bus": NetBus, "line": NetLine, "trafo": NetTrafo, "grid": NetExtGrid, "gen": NetGen, "load": NetLoad,
          "re": PV, "ess": Storage, "dc": DataCenter, "link": Link}

def _norm_type(t):
    if t in ("thermal", "cool", "tes", "hp", "heatnet"): return "heatnet" if t == "heatnet" else "thermal"
    t = {"wind": "re", "pv": "re", "storage": "ess", "ext_grid": "grid", "transformer": "trafo"}.get(t, t)
    if t not in MODELS: raise ValueError(f"未知元素类型 {t}；可用：{', '.join(MODELS)}")
    return t

def _find(sc, typ, key):
    L = _list(sc, typ)
    if typ in ("ess", "dc"):
        for i, x in enumerate(L):
            if x.name == str(key): return i
        raise ValueError(f"未找到{TYPES[typ]} {key}")
    i = int(key)
    if not 0 <= i < len(L): raise ValueError(f"{TYPES[typ]}索引 {key} 越界（共 {len(L)} 个）")
    return i

def graph_id_to_elem(gid: str):
    """模型图元素 id -> (type, key)。"""
    if gid.startswith("b") and gid[1:].isdigit(): return "bus", int(gid[1:])
    if gid.startswith("grid"): return "grid", int(gid[4:])
    if gid.startswith("ngen"): return "gen", int(gid[4:])
    if gid.startswith("nload"): return "load", int(gid[5:])
    if gid.startswith("re"): return "re", int(gid[2:])
    if gid.startswith("ess:"): return "ess", gid[4:]
    if gid.startswith("dc:"): return "dc", gid[3:]
    for p in ("cool:", "tes:", "hp:"):
        if gid.startswith(p): return "thermal", gid[len(p):]
    if gid == "heatnet": return "heatnet", 0
    if gid.startswith("link"): return "link", int(gid[4:])
    raise ValueError(f"无法识别的元素 id {gid}")

def branch_elem(sc, k: int):
    nl = len(sc.network.lines)
    return ("line", k) if k < nl else ("trafo", k - nl)

def get_element(sc, typ, key):
    typ = _norm_type(typ)
    if typ == "thermal":
        d = sc.data_centers[_find(sc, "dc", key)]
        if d.thermal is None: raise ValueError(f"数据中心 {key} 未配置热模型")
        return {"dc": d.name, **d.thermal.model_dump()}
    if typ == "heatnet":
        if sc.heat_network is None: raise ValueError("场景未配置区域供热网")
        return sc.heat_network.model_dump()
    return _list(sc, typ)[_find(sc, typ, key)].model_dump()

def _fix_profile_len(d):
    for k in ("interactive_mw", "profile"):
        if k in d and d[k] is not None and len(d[k]) != H: raise ValueError(f"{k} 必须 {H} 点")

# ---------------- 默认参数（新增元素） ----------------
_WIND = [round(0.42*(1 + 0.35*np.cos(2*np.pi*(h - 2)/24)), 4) for h in range(24)]
_PVP = [round(float(max(0.0, np.sin((h + 0.5 - 6.5)/14*np.pi)))*0.85, 4) for h in range(24)]

def defaults(sc, typ, params):
    p = dict(params or {}); nb = len(sc.network.buses) if sc.network else 14
    if typ == "bus": p.setdefault("name", f"新母线{nb}"); p.setdefault("vn_kv", 110.0)
    elif typ == "line": p.setdefault("name", f"新线路{len(sc.network.lines)}"); p.setdefault("length_km", 10.0); p.setdefault("rating_mva", 200.0)
    elif typ == "trafo": p.setdefault("name", f"新变压器{len(sc.network.trafos)}"); p.setdefault("sn_mva", 240.0)
    elif typ == "grid": p.setdefault("name", f"外网{len(sc.network.ext_grids)}")
    elif typ == "gen": p.setdefault("name", f"G{len(sc.network.gens)}"); p.setdefault("pmax_mw", 100.0)
    elif typ == "load": p.setdefault("name", f"负荷{len(sc.network.loads)}"); p.setdefault("p_mw", 20.0)
    elif typ == "re":
        k = p.get("kind") or "pv"; p["kind"] = k; p.setdefault("cap_mw", 100.0); p.setdefault("profile", _WIND if k == "wind" else _PVP)
        p.setdefault("name", f"{'风电' if k == 'wind' else '光伏'}{len(sc.pv)+1}")
    elif typ == "ess":
        p.setdefault("name", f"ESS_{len(sc.storage)+1}"); p.setdefault("power_mw", 25.0); p.setdefault("energy_mwh", 2*float(p["power_mw"]))
    elif typ == "dc":
        p.setdefault("name", f"DC_{len(sc.data_centers)+1}"); cap = float(p.setdefault("cap_it_mw", 30.0))
        flex = float(p.pop("flex_share", 0.25)); avg = float(p.pop("avg_it_mw", 0.8*cap))
        p.setdefault("interactive_mw", [round((1-flex)*avg, 3)]*24); p.setdefault("batch_mwh", round(flex*avg*24, 2))
    elif typ == "link":
        D = [d.name for d in sc.data_centers]
        if len(D) < 2 and ("a" not in p or "b" not in p): raise ValueError("新增迁移链路需要至少两个数据中心")
        p.setdefault("a", D[0]); p.setdefault("b", D[1])
    return p

def _dc_update(old: DataCenter, p: dict):
    """支持直接改 IT 容量/PUE/灵活性比例（flex_share）/平均 IT 负荷（avg_it_mw）。"""
    p = dict(p)
    if "flex_share" in p or "avg_it_mw" in p:
        avg = float(p.pop("avg_it_mw", np.mean(old.interactive_mw) + old.batch_mwh/24))
        flex = float(p.pop("flex_share", old.batch_mwh/24/max(avg, 1e-9)))
        if not 0 <= flex <= 1: raise ValueError("灵活负荷比例 flex_share 须在 0~1")
        shape = np.asarray(old.interactive_mw)/max(np.mean(old.interactive_mw), 1e-9)
        p["interactive_mw"] = [round(float(x), 3) for x in shape*(1 - flex)*avg]; p["batch_mwh"] = round(flex*avg*24, 2)
    return p

# ---------------- 母线删除后的重编号 ----------------
def _remap_buses(sc, dead: int):
    nw = sc.network; mp = lambda b: b - 1 if b > dead else b
    for l in nw.lines: l.from_bus, l.to_bus = mp(l.from_bus), mp(l.to_bus)
    for t in nw.trafos: t.hv_bus, t.lv_bus = mp(t.hv_bus), mp(t.lv_bus)
    for x in list(nw.ext_grids) + list(nw.gens) + list(nw.loads) + list(sc.pv) + list(sc.storage) + list(sc.data_centers): x.bus = mp(x.bus)
    sc.bus_region = {mp(int(b)): r for b, r in sc.bus_region.items() if int(b) != dead}
    L = {}
    for k, v in sc.layout.items():
        if k.startswith("b") and k[1:].isdigit():
            i = int(k[1:])
            if i != dead: L[f"b{mp(i)}"] = v
        else: L[k] = v
    sc.layout = L

def attached(sc, bus: int):
    nw = sc.network; out = []
    out += [("line", i) for i, l in enumerate(nw.lines) if bus in (l.from_bus, l.to_bus)]
    out += [("trafo", i) for i, t in enumerate(nw.trafos) if bus in (t.hv_bus, t.lv_bus)]
    for typ, L in (("grid", nw.ext_grids), ("gen", nw.gens), ("load", nw.loads), ("re", sc.pv)):
        out += [(typ, i) for i, x in enumerate(L) if x.bus == bus]
    out += [("ess", x.name) for x in sc.storage if x.bus == bus] + [("dc", x.name) for x in sc.data_centers if x.bus == bus]
    return out

def _drop_dev_layout(sc, prefix):
    sc.layout = {k: v for k, v in sc.layout.items() if not k.startswith(prefix)}

DEV_PREFIX = {"grid": "dev:grid", "gen": "dev:ngen", "load": "dev:nload", "re": "dev:re"}

# ---------------- 编辑操作（纯函数：返回新场景） ----------------
def apply_op(sc: Scenario, op: dict) -> tuple[Scenario, str]:
    """op = {action: add|update|delete, type, key?, params?, cascade?} -> (新场景, 中文描述)。"""
    act = op.get("action"); typ = _norm_type(op.get("type", "")); params = dict(op.get("params") or {})
    sc = sc.model_copy(deep=True)
    if typ in ("thermal", "heatnet"): return _thermal_op(sc, act, typ, op, params)
    if typ in NET_TYPES: sc = to_custom(sc)
    if act == "add":
        params = defaults(sc, typ, {**params, **({"kind": op["type"]} if op.get("type") in ("wind", "pv") else {})})
        _fix_profile_len(params)
        el = MODELS[typ].model_validate(params)
        if typ in ("ess", "dc") and any(x.name == el.name for x in _list(sc, typ)): raise ValueError(f"{TYPES[typ]}名称 {el.name} 已存在")
        _list(sc, typ).append(el)
        if typ == "bus" and "x" in op and "y" in op: sc.layout[f"b{len(sc.network.buses)-1}"] = [float(op["x"]), float(op["y"])]
        tn = TYPES[el.kind] if typ == "re" and el.kind else TYPES[typ]
        desc = f"新增{tn} {getattr(el, 'name', '') or (f'{el.a}↔{el.b}' if typ == 'link' else '')}".strip()
    elif act == "update":
        L = _list(sc, typ); i = _find(sc, typ, op.get("key")); old = L[i]
        if typ == "dc": params = _dc_update(old, params)
        _fix_profile_len(params)
        new = MODELS[typ].model_validate({**old.model_dump(), **params})
        if typ in ("ess", "dc") and new.name != old.name:
            if any(x.name == new.name for x in L): raise ValueError(f"名称 {new.name} 已存在")
            if typ == "dc":
                for l in sc.links:
                    if l.a == old.name: l.a = new.name
                    if l.b == old.name: l.b = new.name
                for j in sc.jobs:
                    if j.dc == old.name: j.dc = new.name
            sc.layout = {(f"dev:{typ}:{new.name}" if k == f"dev:{typ}:{old.name}" else k): v for k, v in sc.layout.items()}
        L[i] = new
        ch = ", ".join(f"{k}={v}" for k, v in params.items() if k not in ("interactive_mw", "profile")) or "曲线"
        desc = f"修改{TYPES[typ]} {getattr(new, 'name', '') or op.get('key')}：{ch}"
    elif act == "delete":
        L = _list(sc, typ); i = _find(sc, typ, op.get("key")); el = L[i]; nm = getattr(el, "name", "") or str(op.get("key"))
        if typ == "bus":
            att = attached(sc, i)
            if att and not op.get("cascade"):
                raise ValueError(f"母线 {nm} 上还连接 {len(att)} 个元件（{', '.join(TYPES[t] for t, _ in att[:6])}…）；请先删除或勾选“级联删除”")
            for t, k in sorted([a for a in att if a[0] in ("line", "trafo", "grid", "gen", "load", "re")], key=lambda a: -a[1]): del _list(sc, t)[k]
            for t, k in att:
                if t in ("ess", "dc"): sc, _ = apply_op(sc, {"action": "delete", "type": t, "key": k})
            if len(sc.network.buses) <= 1: raise ValueError("至少保留一条母线")
            del sc.network.buses[i]; _remap_buses(sc, i)
            for p in DEV_PREFIX.values(): _drop_dev_layout(sc, p)
        elif typ == "dc":
            del L[i]; sc.links = [l for l in sc.links if el.name not in (l.a, l.b)]
            sc.jobs = [j for j in sc.jobs if j.dc != el.name]
            for j in sc.jobs:
                if j.allowed_dcs: j.allowed_dcs = [a for a in j.allowed_dcs if a != el.name] or None
            _drop_dev_layout(sc, f"dev:dc:{el.name}")
        else:
            del L[i]
            if typ in DEV_PREFIX: _drop_dev_layout(sc, DEV_PREFIX[typ])
            if typ == "ess": _drop_dev_layout(sc, f"dev:ess:{el.name}")
        desc = f"删除{TYPES[typ]} {nm}" + ("（级联）" if typ == "bus" and op.get("cascade") else "")
    else:
        raise ValueError(f"未知操作 {act}（add/update/delete）")
    errs = eng.validate(sc)
    hard = [e for e in errs if "越界" in e or "同一母线" in e or "不存在" in e or "必须" in e]
    if hard: raise ValueError("编辑后场景不合法：" + "；".join(hard))
    return sc, desc

# ---------------- 模型校验（中文提示） ----------------
def check_model(sc: Scenario) -> dict:
    errors, warnings = [], []
    for e in eng.validate(sc): (errors if ("越界" in e or "不存在" in e or "必须" in e or "Pmin" in e) else warnings).append(e)
    if sc.network_case != "custom" or not sc.network:
        return dict(ok=not errors, errors=errors, warnings=warnings, islands=[])
    nw = sc.network; nb = len(nw.buses)
    G = nx.Graph(); G.add_nodes_from(range(nb))
    for l in nw.lines:
        if 0 <= l.from_bus < nb and 0 <= l.to_bus < nb: G.add_edge(l.from_bus, l.to_bus)
    for t in nw.trafos:
        if 0 <= t.hv_bus < nb and 0 <= t.lv_bus < nb: G.add_edge(t.hv_bus, t.lv_bus)
    lp_max = float(eng.load_profile().max()*sc.load_scale)
    on = lambda L, b: [x for x in L if x.bus == b]
    for b in range(nb):
        if G.degree(b) == 0 and nb > 1 and not on(nw.ext_grids, b):   # 单母线+外网 = 独立区域（如异地数据中心），不算悬空
            devs = sum(len(on(L, b)) for L in (nw.gens, nw.loads, sc.pv, sc.storage, sc.data_centers))
            warnings.append(f"母线「{nw.buses[b].name}」没有任何线路/变压器连接（悬空母线{'，其上元件将形成独立孤岛' if devs else '，可删除或用线路/变压器连接'}）")
    for k, l in enumerate(nw.lines):
        a, b = l.from_bus, l.to_bus
        if 0 <= a < nb and 0 <= b < nb and abs(nw.buses[a].vn_kv - nw.buses[b].vn_kv) > 1e-6:
            errors.append(f"线路「{l.name or k}」两端电压等级不同（{nw.buses[a].vn_kv:g}/{nw.buses[b].vn_kv:g} kV），不同电压等级之间请用变压器连接")
        if l.rating_mva <= 0 or l.length_km <= 0 or l.x_ohm_per_km <= 0: errors.append(f"线路「{l.name or k}」额定/长度/电抗必须为正")
    for k, t in enumerate(nw.trafos):
        a, b = t.hv_bus, t.lv_bus
        if 0 <= a < nb and 0 <= b < nb and nw.buses[a].vn_kv < nw.buses[b].vn_kv: warnings.append(f"变压器「{t.name or k}」高压侧电压低于低压侧，请检查 hv_bus/lv_bus 是否接反")
        if t.sn_mva <= 0 or t.vk_percent <= 0: errors.append(f"变压器「{t.name or k}」容量/短路电压必须为正")
    islands = []
    for comp in nx.connected_components(G):
        c = set(comp); names = [nw.buses[b].name for b in sorted(c)]
        grid = [e for e in nw.ext_grids if e.bus in c]; gens = [g for g in nw.gens if g.bus in c]
        re = [p for p in sc.pv if p.bus in c]; ess = [s for s in sc.storage if s.bus in c]
        dcs = [d for d in sc.data_centers if d.bus in c]; lds = [l for l in nw.loads if l.bus in c]
        from ..power_model import power_mw
        installed = sum(power_mw(d,d.cap_it_mw)*d.pue for d in dcs) + sum(l.p_mw*lp_max for l in lds)
        fixed_profile = [sum(power_mw(d,d.interactive_mw[t])*(1.0 if sc.thermal_mode=="coupled" and d.thermal is not None else d.pue) for d in dcs)+sum(l.p_mw*eng.load_profile(sc)[t]*sc.load_scale for l in lds) for t in range(sc.n_steps)]
        fixed_peak=max(fixed_profile, default=0)
        flexible_mwh=sum(j.energy_mwh for j in sc.jobs if j.dc in {d.name for d in dcs}) if sc.jobs else sum(d.batch_mwh for d in dcs)
        mandatory_electric_mwh=0.0
        if not sc.jobs and dcs and sc.thermal_mode=="constant_pue" and all(d.power_model=="identity" for d in dcs):
            outside={d.name for d in sc.data_centers if d.bus not in c}
            LM=eng.link_map(sc); export_bound=0.0
            for d in dcs:
                outgoing=sum(LM[(d.name,e)].bw_mw for e in outside if (d.name,e) in LM) if LM is not None else float("inf")
                if outside: export_bound+=min(d.batch_mwh*sc.mig_day_share,24*sc.mig_max_mw,24*outgoing)
            mandatory_electric_mwh=max(0,flexible_mwh-export_bound)*min(d.pue for d in dcs)
        peak=max(fixed_peak,(sc.dt_hours*sum(fixed_profile)+mandatory_electric_mwh)/sc.hours)

        firm = (float("inf") if any(e.import_max_mw >= 1e4 for e in grid) else sum(e.import_max_mw for e in grid)) + sum(g.pmax_mw for g in gens)
        info = dict(buses=names, has_grid=bool(grid), peak_load_mw=round(peak, 6), forecast_fixed_peak_mw=fixed_peak, required_peak_lower_bound_mw=peak, mandatory_flexible_electric_lower_bound_mwh=mandatory_electric_mwh, installed_load_upper_bound_mw=installed, flexible_offered_it_mwh=flexible_mwh, peak_basis="fixed_forecast_plus_mandatory_energy_lower_bound_not_capacity", thermal_load_exact=(sc.thermal_mode=="constant_pue"), fixed_profile_is_electrical_floor=(sc.thermal_mode=="coupled"), firm_mw=None if firm == float("inf") else round(firm, 1),
                    re_mw=round(sum(p.cap_mw for p in re), 1), ess_mw=round(sum(s.power_mw for s in ess), 1))
        islands.append(info)
        tag = "、".join(names[:3]) + ("…" if len(names) > 3 else "")
        if peak > 0 and not (grid or gens or re or ess):
            errors.append(f"电气岛〔{tag}〕有负荷 {peak:.0f} MW 但没有任何电源（外网/机组/风光/储能），无法供电")
        elif peak > 0 and not (grid or gens):
            warnings.append(f"电气岛〔{tag}〕为纯风光储孤岛（无外网/可调度电源）：无风无光时段依赖储能，可能无解；建议加外网购电点或可调度电源")
        elif peak > firm + sum(s.power_mw for s in ess) + 1e-6 and firm != float("inf"):
            warnings.append(f"电气岛〔{tag}〕必需负荷峰值下界 {peak:.3g} MW 大于可靠出力（外网上限+机组+储能）{firm + sum(s.power_mw for s in ess):.3g} MW，低风光时段可能无解")
    for d in sc.data_centers:
        if not 1.0 <= d.pue <= 3.0: warnings.append(f"数据中心「{d.name}」PUE={d.pue} 不在常见范围 1.0~3.0")
        if d.cap_it_mw <= 0: errors.append(f"数据中心「{d.name}」IT 容量必须为正")
    for s in sc.storage:
        if s.power_mw <= 0 or s.energy_mwh <= 0: errors.append(f"储能「{s.name}」功率/容量必须为正")
        elif not 0.25 <= s.energy_mwh/s.power_mw <= 12: warnings.append(f"储能「{s.name}」时长 {s.energy_mwh/s.power_mw:.2f} h 不在常见范围 0.25~12 h")
    for p in sc.pv:
        if p.cap_mw < 0: errors.append("风光装机不能为负")
    for k, l in enumerate(sc.links):
        if l.a == l.b: errors.append(f"迁移链路 {k} 两端为同一数据中心")
    for k, l in enumerate(nw.lines):
        a, b = l.from_bus, l.to_bus
        if not (0 <= a < nb and 0 <= b < nb): continue
        inj = sum(p.cap_mw for p in sc.pv if p.bus in (a, b))
        if inj > 3*l.rating_mva*l.parallel and inj > 0: warnings.append(f"线路「{l.name or k}」端点新能源装机 {inj:.0f} MW 远大于线路额定 {l.rating_mva*l.parallel:.0f} MVA，可能大量弃电")
    return dict(ok=not errors, errors=errors, warnings=warnings, islands=islands)

# ---------------- 关键指标（前后对比） ----------------
def metrics(sc: Scenario, r: dict) -> dict:
    dt=r.get("solver",{}).get("resolution_h",1)
    df = r["df"]; dc = [c for c in df if c.endswith("_grid_MW")]
    dcE = dt*float(df[dc].sum().sum()); load = dcE + dt*float(df.base_load_MW.sum())
    imp = dt*float(df.grid_import_MW.sum()) if "grid_import_MW" in df else 0.0
    used = dt*float(df.pv_used.sum()); clean = dt*float(df.clean_gen_MW.sum()) if "clean_gen_MW" in df else 0.0
    return {"总成本 元": round(r.get("cost_cny", r["objective"]), 0), "外网购电 MWh": round(imp, 1),
            "外送 MWh": round(dt*float(df.grid_export_MW.sum()) if "grid_export_MW" in df else 0.0, 1),
            "新能源利用 MWh": round(used, 1), "新能源占比 %": round(100*min(1.0, (used + clean)/max(load, 1e-9)), 2),
            "弃电 MWh": round(max(0.0, float(r["curtail_mwh"])), 1), "碳排放 tCO2": round(float(r.get("emissions_t", 0.0)), 2),
            "数据中心用电 MWh": round(dcE, 1), "最大支路负载率 %": round(float(df.max_line_loading_pct.max()), 1),
            "迁移 MWh": round(dt*float(df[[c for c in df if c.endswith("_mig_out")]].sum().sum()), 1)}

def compare(before: dict | None, after: dict) -> list:
    out = []
    for k, v in after.items():
        b = (before or {}).get(k)
        out.append(dict(metric=k, before=b, after=v, delta=None if b is None else round(v - b, 3),
                        delta_pct=None if (b is None or abs(b) < 1e-9) else round(100*(v - b)/abs(b), 2)))
    return out


def _thermal_op(sc, act, typ, op, params):
    """热管理（挂在数据中心上）与区域供热网的增/改/删。新增热模型时按 IT 容量缩放默认参数，并切换到 coupled 模式。"""
    params.pop("name", None)
    if typ == "thermal":
        key = params.pop("dc", None) if act == "add" else op.get("key")
        i = _find(sc, "dc", key or sc.data_centers[0].name); d = sc.data_centers[i]
        if act == "delete":
            d.thermal = None; desc = f"移除 {d.name} 热模型（回退常数 PUE）"
        else:
            if act == "add":
                import os, sys
                sys.path.insert(0, os.path.join(os.path.dirname(eng.__file__), "..", "..", "cases", "common"))
                from thermal_params import thermal_for
                base = thermal_for(d.cap_it_mw)
            elif d.thermal is None: raise ValueError(f"数据中心 {d.name} 未配置热模型，请先新增")
            else: base = d.thermal.model_dump()
            params.pop("dc", None)
            d.thermal = DCThermal.model_validate({**base, **{k: v for k, v in params.items() if v is not None}})
            if act == "add": sc.thermal_mode = "coupled"
            desc = (f"为 {d.name} 启用热模型（RC+冷机+自然冷却）" if act == "add" else f"修改 {d.name} 热管理：" + ", ".join(f"{k}={v}" for k, v in params.items()))
    else:
        if act == "delete": sc.heat_network = None; desc = "删除区域供热网"
        else:
            base = sc.heat_network.model_dump() if sc.heat_network else {}
            if act == "update" and not base: raise ValueError("场景未配置区域供热网")
            if act == "add" and "demand_mw_th" not in params:
                import numpy as _np
                pk = float(params.pop("peak_mw_th", 50.0) or 50.0)
                params["demand_mw_th"] = [round(pk*(0.6 + 0.4*(0.5 + 0.5*_np.cos(2*_np.pi*(h - 6)/24))), 2) for h in range(24)]
            params.pop("peak_mw_th", None)
            sc.heat_network = HeatNetwork.model_validate({**base, **{k: v for k, v in params.items() if v is not None}})
            desc = ("新增区域供热网 " if act == "add" else "修改区域供热网：") + ", ".join(f"{k}={v}" for k, v in params.items() if k != "demand_mw_th")
    errs = eng.validate(sc)
    if errs: raise ValueError("编辑后场景不合法：" + "；".join(errs))
    return sc, desc
