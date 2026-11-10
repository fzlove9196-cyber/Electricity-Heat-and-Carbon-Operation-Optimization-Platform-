"""需求驱动寻优：结构化目标规格 → 单目标 / 加权 / 字典序 / ε-约束帕累托；标注成本最优、碳最优、膝点；对偶解释；边际减排成本。"""
import copy, time
import numpy as np
from . import annual as A

OBJ = {  # key: (中文, 单位, 方向说明)
    "cost": ("年化总成本", "元/年", "min"), "carbon": ("年净碳排放", "tCO2/年", "min"), "green": ("外购电量(≈绿电占比最大)", "MWh/年", "min"),
    "peak": ("峰值购电功率", "MW", "min"), "thermal_margin": ("热安全裕度", "×", "max"), "npv": ("净现值(=年化成本最小)", "元/年", "min"),
}
CONS = {"green": "绿电占比 ≥", "carbon": "年碳排放 ≤", "cost": "年化总成本 ≤", "peak": "峰值购电 ≤", "payback": "投资回收期 ≤",
        "thermal_margin": "热安全裕度 ≥", "pue": "年均 PUE ≤"}

def default_spec(preset="zhongwei_summer_coupled"):
    return dict(preset=preset, year=2024, resolution="full", carbon_basis="marginal", carbon_price=None, wind_scale=1.0,
                mode="pareto", objectives=[dict(key="cost", weight=1.0, priority=1), dict(key="carbon", weight=1.0, priority=2)],
                pareto=dict(x="cost", y="carbon", n=7), constraints=[],
                decisions=dict(wind=True, pv=True, bat_e=True, bat_p=True, tes=True, hs=True, chiller=False, hp=True), cooling_modes=[])

def plan_bounds(case, dec):
    it = sum(d.cap_it_mw for d in case["dcs"]); hn = case["hn"]
    hl = (hn.design_load_mw_th or max(hn.demand_mw_th or [0])) if hn else 0
    ub = dict(wind=5*it, pv=5*it, bat_e=8*it, bat_p=2*it, tes=4*it, hs=8*hl, chiller=0.5*it, hp=1.0*hl)
    out = {}
    for k, v in (dec or {}).items():
        if k not in ub or not v: continue
        out[k] = ub[k] if isinstance(v, bool) else float(v)
        if out[k] <= 0: out.pop(k)
    return out

def formulation(spec):
    """透明化：把规格翻译成数学表述（展示在目标卡上）。"""
    o = spec["objectives"]; L = []
    if spec["mode"] == "pareto":
        px, py = spec["pareto"]["x"], spec["pareto"]["y"]
        L.append(f"ε-约束帕累托：min {OBJ[px][0]}  s.t. {OBJ[py][0]} ≤ ε_i，ε_i 在 [{OBJ[py][0]}最优值, {OBJ[px][0]}最优时的取值] 间等分 {spec['pareto']['n']} 点")
    elif spec["mode"] == "weighted":
        L.append("加权和：min Σ_k w_k·f_k/(f_k^max − f_k^min)（支付表归一化），" + "，".join(f"w[{OBJ[x['key']][0]}]={x['weight']}" for x in o))
    elif spec["mode"] == "lexicographic":
        L.append("字典序：" + " → ".join(f"P{x['priority']} {OBJ[x['key']][0]}" for x in sorted(o, key=lambda z: z["priority"])) + "（上一级最优值放宽 1% 作为下一级约束）")
    else:
        L.append(f"单目标：{'max' if o[0]['key'] == 'thermal_margin' else 'min'} {OBJ[o[0]['key']][0]}")
    L.append("年化总成本 = Σ_t w_t·(电价_t·购电_t + 水电成本_t) + 碳价·净排放 − 售热收入 + Σ_a (CRF(6%,n_a)+运维率_a)·单位投资_a·新增_a + PPA 照付不议")
    L.append("净排放 = Σ_t w_t·EF_t·购电_t − 锅炉排放因子·售热量；EF_t = " + ("逐时边际碳因子（剩余负荷-优先顺序法）" if spec.get("carbon_basis") == "marginal" else "省级平均因子（常数）"))
    for c in spec["constraints"]:
        L.append(f"硬约束：{CONS.get(c['key'], c['key'])} {c['value']}")
    dv = [A.CAPEX[k]["cn"] for k, v in spec["decisions"].items() if v and k in A.CAPEX]
    L.append("容量决策变量：" + ("、".join(dv) if dv else "无（仅运行优化）") + ("；散热方式枚举：" + "/".join(spec["cooling_modes"]) + "（逐一求解取最优，含散热系统投资年化，并自动允许冷机增容）" if spec.get("cooling_modes") else ""))
    L.append("运行约束（逐时）：电力平衡、风/光可发上限、电池/蓄冷/蓄热 SOC（日内+日间链接）、冷量平衡、冷机 N+1 可用冷量、批处理日电量、热泵/余热上限、热网需求")
    L.append("时间分辨率：" + ("全年 8760h" if spec.get("resolution") in ("full", None, 365) else f"{spec['resolution']} 个代表日（k-means，取离中心最近的真实日，储能时序链接）"))
    return L

def _cases(spec):
    base = A.build_case(spec["preset"], spec.get("year", 2024), spec.get("wind_scale", 1.0), spec.get("carbon_basis", "marginal"), spec.get("carbon_price"))
    modes = spec.get("cooling_modes") or []
    if not modes: return [(None, base, 0.0)]
    from ..tools import cooling as CL
    out = []
    for md in modes:
        c = copy.deepcopy(base)
        for d in c["dcs"]: d.thermal = CL.apply_mode(d.thermal, md, cap_it=d.cap_it_mw)
        lo, hi = [float(v) for v in CL.MODES[md]["capex_cny_kw"].split("-")]
        capex = sum(d.cap_it_mw for d in c["dcs"])*1000*(lo + hi)/2*(A.crf(15) + 0.02)
        out.append((md, c, capex))
    return out

def _rows(M, spec, base_op=None):
    V = M["vec"]; R = []; cp = M["case"]["carbon_price"]
    for c in spec["constraints"]:
        k, val = c["key"], float(c["value"])
        if k == "green": R.append((V["grid"] - (1 - val)*V["load"], (1 - val)*M["load_const"], f"绿电占比≥{val:.0%}"))
        elif k == "carbon": R.append((V["carbon"], val, f"碳排放≤{val:.0f}t"))
        elif k == "cost": R.append((A.objective_vec(M, "cost"), val - M["const_cost"] - M.get("mode_capex", 0), f"年成本≤{val:.3g}元"))
        elif k == "peak": R.append((V["peak"], val, f"峰值购电≤{val:.0f}MW"))
        elif k == "pue": R.append((V["dce"], val*M["it_const"] - M["load_const"], f"PUE≤{val}"))
        elif k == "thermal_margin" and V["margin"] is not None: R.append((V["margin"], -val, f"热安全裕度≥{val:.0%}"))
        elif k == "payback" and base_op is not None:
            op = V["energy"] + cp*V["carbon"]
            R.append((V["invest"] + val*op, val*(base_op - M["const_cost"]), f"回收期≤{val:.0f}年"))
    return R

def _val(M, key, x):
    if key == "thermal_margin": return float(x[M["mvar"][0]])
    v = A.obj_value(M, key, x)
    return v + (M.get("mode_capex", 0) if key in ("cost", "npv") else 0)

def _capcn(nm):
    k = nm if nm.startswith("bat") else nm.split("_")[0]
    return A.CAPEX.get(k, {"cn": nm})["cn"]

def _scheme(M, r, label, spec, extra_names=()):
    x = r["x"]; K = A.kpis(M, x); K["cost_total"] += M.get("mode_capex", 0); K["mode_capex_ann"] = M.get("mode_capex", 0)
    b = M.get("base_op")
    if b is not None and K["invest"] > 1:
        sav = b - (K["cost_total"] - K["capex_ann"] - K["mode_capex_ann"]); K["annual_saving"] = sav
        K["payback_y"] = K["invest"]/sav if sav > 0 else None
        K["npv_20y"] = -K["invest"] + sav*(1 - 1.06**-20)/0.06
    lp = M["lp"]; lb, ub = lp.bounds(); atub = []
    for nm, idx in lp.names.items():
        if nm.startswith("d_") and idx.size == 1 and 0 < ub[idx[0]] < np.inf and x[idx[0]] >= ub[idx[0]]*(1 - 1e-6) - 1e-6: atub.append(_capcn(nm[2:]) + "新增上限")
    return dict(label=label, kpi={k: (round(v, 4) if isinstance(v, float) else v) for k, v in K.items()}, mode=M.get("mode_name"),
                binding=list(r["groups"].keys())[:6], at_upper=atub, duals=[(n, round(d, 4)) for n, d in zip(extra_names, r.get("extra_duals", []))], solve_s=round(r["time"], 2))

def verify_full(spec, scheme, progress=None):
    """代表日规划 → 固定容量后在完整 8760h 上重新优化运行，给出“降维误差”。"""
    s2 = copy.deepcopy(spec); base = None
    for md, case, mcap in _cases(s2):
        if md != scheme.get("mode"): continue
        M = A.build(case, k=None, fixed=dict(scheme["kpi"]["caps"]), need_margin=False); M["mode_capex"] = mcap
        r = A.solve(M, A.objective_vec(M, "cost"))
        if r["x"] is None: return dict(status=r["status"])
        K = A.kpis(M, r["x"]); K["cost_total"] += mcap
        return dict(status="optimal", kpi=K, time=r["time"],
                    err={k: (K[k] - scheme["kpi"][k])/max(abs(K[k]), 1e-9) for k in ("cost_total", "carbon_net_t", "green_share", "pue", "heat_mwh") if abs(K[k]) > 1e-6})
    return dict(status="mode-not-found")

def run(spec, progress=None):
    if spec.get("dt_hours",1)!=1: raise ValueError("年度投资/代表日优化只支持1h；15min须常规日调度，禁止隐式按1h")
    t0 = time.time(); spec = copy.deepcopy(spec); log = []; say = progress or (lambda *_: None)
    res = None if spec.get("resolution") in ("full", None, 365) else int(spec["resolution"])
    need_m = any(o["key"] == "thermal_margin" for o in spec["objectives"]) or any(c["key"] == "thermal_margin" for c in spec["constraints"])
    mode = spec["mode"]; objs = sorted(spec["objectives"], key=lambda z: z.get("priority", 1))
    keys = list(dict.fromkeys([o["key"] for o in objs] + ([spec["pareto"]["x"], spec["pareto"]["y"]] if mode == "pareto" else [])))
    out = dict(spec=spec, formulation=formulation(spec), log=log, schemes=[], front=[])
    models = []
    for md, case, mcap in _cases(spec):
        plan = plan_bounds(case, spec["decisions"])
        if md and "chiller" not in plan: plan["chiller"] = 1.0*sum(d.cap_it_mw for d in case["dcs"])   # 换散热方式须允许冷机重新选型
        M = A.build(case, k=res, plan=plan, need_margin=need_m); M["mode_capex"] = mcap; M["mode_name"] = md
        M0 = A.build(case, k=res, plan={}, need_margin=False); r0 = A.solve(M0, A.objective_vec(M0, "cost"))   # 基线：不新增投资，仅运行优化
        M["base_op"] = A.obj_value(M0, "cost", r0["x"]) if r0["x"] is not None else None
        M["baseline"] = _scheme(M0, r0, "现状(仅运行优化)", spec) if r0["x"] is not None else None
        R = _rows(M, spec, M["base_op"]); M["R"] = R
        M["S"] = A.Session(M, [v for v, _, _ in R] + [A.objective_vec(M, k) for k in keys]); M["keys"] = keys
        models.append(M); log.append(f"模型[{md or '现状散热方式'}]: 变量 {M['lp'].n:,}，约束 {M['lp'].m['le'] + M['lp'].m['eq']:,}，组装 {M['build_s']:.1f}s")
        say("build", log[-1])
    def solve_min(M, key, caps=None):
        """caps: {目标key: 上限}（ε/字典序行）。"""
        rhs = [b for _, b, _ in M["R"]] + [None if not caps or k not in caps else caps[k] - (M["const_cost"] + M.get("mode_capex", 0) if k in ("cost", "npv") else 0) for k in M["keys"]]
        c = A.objective_vec(M, key) if not isinstance(key, np.ndarray) else key
        r = M["S"].solve(c, rhs)
        if r["x"] is not None:
            r["named_duals"] = [(n, d) for (_, _, n), d in zip(M["R"], r["extra_duals"])] + [(f"{OBJ[k][0]}≤ε", d) for k, d in zip(M["keys"], r["extra_duals"][len(M["R"]):]) if caps and k in caps]
        return r
    def sch(M, r, label):
        s = _scheme(M, r, label, spec); s["duals"] = [(n, round(d, 4)) for n, d in r.get("named_duals", [])]; return s
    if mode in ("single", "lexicographic", "weighted"):
        best = None
        for M in models:
            if mode == "single" or len(objs) == 1: r = solve_min(M, objs[0]["key"])
            elif mode == "lexicographic":
                caps = {}
                for o in objs:
                    r = solve_min(M, o["key"], caps)
                    if r["x"] is None: break
                    v = _val(M, o["key"], r["x"]) if o["key"] != "thermal_margin" else float(A.objective_vec(M, o["key"]) @ r["x"])
                    caps[o["key"]] = v + abs(v)*0.01 + 1e-6
            else:
                pay = {o["key"]: solve_min(M, o["key"]) for o in objs}; c = np.zeros(M["lp"].n)
                for o in objs:
                    cv = A.objective_vec(M, o["key"]); vals = [float(cv @ pay[p]["x"]) for p in pay if pay[p]["x"] is not None]
                    c += o.get("weight", 1.0)*cv/max(max(vals) - min(vals), 1e-6)
                r = solve_min(M, c)
            if r["x"] is None: log.append(f"[{M['mode_name']}] 求解失败：{r['status']}"); continue
            s = sch(M, r, "最优方案"); say("point", f"[{M['mode_name'] or '现状'}] 最优解 {r['time']:.1f}s")
            if best is None or _key(s, objs[0]["key"]) < _key(best, objs[0]["key"]): best = s
        if best: best["tag"] = "optimum"; best["why"] = explain(best, spec, "optimum"); out["schemes"].append(best)
    else:
        px, py = spec["pareto"]["x"], spec["pareto"]["y"]; n = max(3, int(spec["pareto"].get("n", 7))); pts = []
        for M in models:
            rx = solve_min(M, px); ry = solve_min(M, py)
            if rx["x"] is None or ry["x"] is None: log.append(f"[{M['mode_name']}] 端点不可行：{rx['status']} / {ry['status']}"); continue
            ylo, yhi = _val(M, py, ry["x"]), _val(M, py, rx["x"])
            sgn = -1 if py == "thermal_margin" else 1
            if py == "thermal_margin": ylo, yhi = -ylo, -yhi    # 统一为“越小越好”的 ε 行（margin 向量为 −m）
            ry2 = solve_min(M, px, {py: ylo + abs(ylo)*1e-4 + 1e-3})
            if ry2["x"] is not None: ry = ry2
            say("point", f"[{M['mode_name'] or '现状'}] 端点：{OBJ[px][0]}最优 {rx['time']:.0f}s / {OBJ[py][0]}最优 {ry['time']:.0f}s")
            for i, e in enumerate(np.linspace(yhi, ylo, n)):
                if i == 0: r = rx
                elif i == n - 1: r = ry
                else: r = solve_min(M, px, {py: float(e)}); say("point", f"ε{i}/{n - 1}：{OBJ[py][0]} ≤ {sgn*e:,.1f}，{r['time']:.0f}s")
                if r["x"] is None: continue
                s = sch(M, r, f"P{i}"); s["x"] = _val(M, px, r["x"]); s["y"] = _val(M, py, r["x"])
                s["eps_dual"] = round(r["extra_duals"][-1 if M["keys"][-1] == py else len(M["R"]) + M["keys"].index(py)], 3) if 0 < i < n - 1 else None
                pts.append(s)
            if M.get("baseline"): out.setdefault("baselines", []).append(M["baseline"])
        pts = _nondominated(pts, py); pts.sort(key=lambda s: s["x"])
        for i, s in enumerate(pts): s["label"] = f"方案{i + 1}"
        if pts:
            pts[0]["tag"] = "cost_opt" if px in ("cost", "npv") else "x_opt"; pts[-1]["tag"] = "carbon_opt" if py == "carbon" else "y_opt"
            k = _knee(pts)
            if k is not None: pts[k]["tag"] = "knee"
            for i in range(1, len(pts)):
                dx, dy = pts[i]["x"] - pts[i - 1]["x"], pts[i - 1]["y"] - pts[i]["y"]
                pts[i]["mac_seg"] = round(abs(dx/dy), 1) if abs(dy) > 1e-9 else None
            for s in pts: s["why"] = explain(s, spec, s.get("tag"))
        out["front"] = pts; out["schemes"] = [s for s in pts if s.get("tag")]
    if res is not None and spec.get("verify_full", True):
        for s in out["schemes"]:
            v = verify_full(spec, s); s["verify"] = {k: (round(x, 4) if isinstance(x, float) else x) for k, x in v.items() if k != "kpi"}
            if v.get("kpi"): s["verify"]["kpi"] = {k: round(v["kpi"][k], 4) for k in ("cost_total", "carbon_net_t", "green_share", "pue", "heat_mwh")}
            say("verify", f"{s['label']} 8760h 复核 {v.get('time', 0):.1f}s")
    if models and models[0].get("baseline"): out["baseline"] = models[0]["baseline"]
    out["runtime_s"] = round(time.time() - t0, 1)
    if models: out["carbon_stats"] = models[0]["case"]["carbon_stats"]; out["case_source"] = models[0]["case"]["source"]
    for M in models: M.pop("S", None)
    return out

def _key(s, k):
    m = {"cost": "cost_total", "npv": "cost_total", "carbon": "carbon_net_t", "peak": "peak_mw", "green": "grid_mwh"}
    return -(s["kpi"]["margin"] or 0) if k == "thermal_margin" else s["kpi"][m[k]]

def _nondominated(pts, py):
    sg = -1 if py == "thermal_margin" else 1; out = []
    for p in pts:
        if not any((q["x"] <= p["x"] + 1e-6 and sg*q["y"] <= sg*p["y"] + 1e-6) and (q["x"] < p["x"] - 1e-6 or sg*q["y"] < sg*p["y"] - 1e-6) for q in pts): out.append(p)
    uniq = []
    for p in out:
        if not any(abs(p["x"] - q["x"]) <= 1e-4*max(1, abs(q["x"])) and abs(p["y"] - q["y"]) <= 1e-4*max(1, abs(q["y"])) for q in uniq): uniq.append(p)
    return uniq

def _knee(pts):
    if len(pts) < 3: return None
    x = np.array([p["x"] for p in pts]); y = np.array([p["y"] for p in pts])
    xn = (x - x.min())/max(np.ptp(x), 1e-9); yn = (y - y.min())/max(np.ptp(y), 1e-9)
    a, b = np.array([xn[0], yn[0]]), np.array([xn[-1], yn[-1]]); d = b - a
    dist = np.abs(d[0]*(yn - a[1]) - d[1]*(xn - a[0]))/max(np.hypot(*d), 1e-9)
    k = int(np.argmax(dist)); return k if 0 < k < len(pts) - 1 else None

def explain(s, spec, tag):
    k = s["kpi"]; caps = "、".join(f"{_capcn(n)} +{v:g}" for n, v in k["caps"].items()) or "不新增投资"
    head = {"cost_opt": "成本最优：所有硬约束下年化总成本最低", "carbon_opt": "碳最优：年净碳排放最低（并在此前提下成本最低）",
            "knee": "折中（膝点）：归一化前沿上离“成本最优—碳最优”连线最远的点；越过它，每多减 1 吨碳的代价明显变陡",
            "optimum": "按目标规格求得的最优解"}.get(tag, "前沿上的中间方案")
    t = [head, "新增容量：" + caps + (f"；散热方式 {s['mode']}" if s.get("mode") else "")]
    if s.get("binding"): t.append("起作用的约束（对偶值非零，按影响排序）：" + "、".join(s["binding"][:5]))
    if s.get("at_upper"): t.append("触及规划上限：" + "、".join(s["at_upper"]) + "（放宽上限可能继续改善）")
    if s.get("eps_dual") not in (None, 0.0) and spec.get("mode") == "pareto":
        t.append(f"ε 约束对偶（该点边际代价）≈ {s['eps_dual']:,.1f} {OBJ[spec['pareto']['x']][1].split('/')[0]}/{OBJ[spec['pareto']['y']][1].split('/')[0]}")
    if s.get("mac_seg") is not None: t.append(f"与上一方案间平均边际代价 ≈ {s['mac_seg']:,.0f} {OBJ[spec['pareto']['x']][1].split('/')[0]}/{OBJ[spec['pareto']['y']][1].split('/')[0]}")
    if k.get("payback_y"): t.append(f"相对现状：投资 {k['invest']/1e8:.2f} 亿元，年节省 {k['annual_saving']/1e4:,.0f} 万元，静态回收期 {k['payback_y']:.1f} 年")
    return t

def abatement(result, pct=0.10, ref=None):
    """“再降 x% 碳要多花多少钱”：从参考方案（默认膝点/最优）出发，重解 min 成本 s.t. 碳 ≤ (1−pct)·C_ref。"""
    spec = copy.deepcopy(result["spec"]); pts = result.get("front") or result.get("schemes") or []
    refs = [s for s in pts if s.get("label") == ref] or [s for s in pts if s.get("tag") == "knee"] or [s for s in pts if s.get("tag") in ("optimum", "cost_opt")] or pts[:1]
    if not refs: return dict(ok=False, msg="还没有可参考的方案")
    r0 = refs[0]; C0 = r0["kpi"]["carbon_net_t"]; target = C0 - abs(C0)*pct
    spec["mode"] = "single"; spec["objectives"] = [dict(key="cost", weight=1, priority=1)]
    spec["constraints"] = [c for c in spec["constraints"] if c["key"] != "carbon"] + [dict(key="carbon", value=target)]
    if r0.get("mode"): spec["cooling_modes"] = [r0["mode"]]
    rr = run(spec); s = rr["schemes"][0] if rr["schemes"] else None
    if s is None: return dict(ok=False, ref=r0, target=target, msg="目标碳排放在当前决策空间内不可行（已低于碳最优下限）")
    dc = s["kpi"]["cost_total"] - r0["kpi"]["cost_total"]; dC = C0 - s["kpi"]["carbon_net_t"]
    du = [d for n, d in s["duals"] if n.startswith("碳排放")]
    return dict(ok=True, ref=r0, target=target, scheme=s, d_cost=dc, d_carbon=dC, avg_mac=dc/max(dC, 1e-9), marginal_mac=(du[0] if du else None), runtime_s=rr["runtime_s"])
