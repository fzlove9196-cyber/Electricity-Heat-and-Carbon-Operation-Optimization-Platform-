"""LP 紧约束 / 对偶（影子价格）分析：对 Pyomo ConstraintList 按“约束所在列表 + 涉及变量族”自动分组。
确定性、无需 LLM。dual 单位 = 目标函数(元) / 约束右端单位（MW、MWh、K …），符号按最小化问题约定。"""
from __future__ import annotations
from collections import defaultdict

VAR_CN = {"pg": "机组/外购出力", "gx": "外网反送", "th": "母线相角", "pv": "新能源出力", "bt": "批处理算力", "mg": "跨DC迁移", "ch": "储能充电",
          "dis": "储能放电", "soc": "储能SOC", "pj": "作业功率", "un": "作业未完成", "pk": "需量峰值", "Ta": "机房入口温度", "Tm": "结构温度",
          "qch": "冷机冷量", "qfree": "自然冷却", "tes_c": "蓄冷充", "tes_d": "蓄冷放", "tes_s": "蓄冷SOC", "qhp": "热泵供热", "exc": "超推荐温度",
          "hdel": "供热量", "hboost": "调峰补热", "hs": "热网蓄热SOC", "hsc": "蓄热充", "hsd": "蓄热放", "dr": "需求响应量", "drs": "DR缺额"}

def _label(lst, fams):
    f = set(fams)
    if lst == "drc": return "需求响应约束（承诺量/上限）" if "dr" in f else "需求响应基线约束"
    if lst == "thc":
        if {"Ta", "Tm"} <= f and ("qch" in f or "qfree" in f): return "机房热平衡（RC 模型）"
        if f == {"Ta"} or f == {"Ta", "exc"}: return "入口温度上下限/温变率/推荐上限"
        if "qch" in f and len(f) <= 2: return "冷机可用冷量上限（N+1）"
        if f <= {"qfree"}: return "自然冷却可用冷量"
        if f & {"tes_s", "tes_c", "tes_d"}: return "蓄冷罐容量/功率"
        if f & {"hdel", "hs", "hsc", "hsd", "hboost"}: return "供热网热平衡/蓄热/需求上限"
        if "qhp" in f: return "热泵容量/余热回收上限"
        return "热管理约束"
    if f & {"soc", "ch", "dis"} and not (f & {"pg", "th"}): return "储能 SOC/功率"
    if "th" in f and ("pg" in f or "pv" in f or "bt" in f): return "节点功率平衡（DC-OPF）"
    if f == {"th"}: return "线路潮流限值"
    if f & {"pj", "un"}: return "作业截止/功率约束"
    if "mg" in f: return "迁移带宽/日迁移量"
    if "bt" in f: return "批处理算力日能量/容量"
    if "pv" in f: return "新能源可用出力"
    if "pg" in f or "gx" in f: return "机组/外网出力限值"
    return "其它约束"

def analyze(m, tol=1e-6, top=10):
    import pyomo.environ as pyo
    from pyomo.core.expr.visitor import identify_variables
    if not hasattr(m, "dual"): return []
    G = defaultdict(lambda: dict(n=0, n_binding=0, dual_abs_sum=0.0, dual_max=0.0, hours=set(), fams=set()))
    for c in m.component_data_objects(pyo.Constraint, active=True):
        lst = c.parent_component().name
        fams = tuple(sorted({v.parent_component().name for v in identify_variables(c.body, include_fixed=False)}))
        if not fams: continue
        lab = _label(lst, fams); g = G[lab]; g["n"] += 1; g["fams"].update(fams)
        d = m.dual.get(c)
        if d is None or abs(d) <= tol: continue
        g["n_binding"] += 1; g["dual_abs_sum"] += abs(d)
        if abs(d) > abs(g["dual_max"]): g["dual_max"] = float(d)
        for v in identify_variables(c.body, include_fixed=False):
            ix = v.index(); h = ix[-1] if isinstance(ix, tuple) and ix else ix
            if isinstance(h, int) and 0 <= h < 48: g["hours"].add(h)
            break
    out = [dict(group=k, n=v["n"], n_binding=v["n_binding"], dual_abs_sum=round(v["dual_abs_sum"], 3), dual_max=round(v["dual_max"], 3),
                hours=sorted(v["hours"])[:24], vars=[VAR_CN.get(x, x) for x in sorted(v["fams"])][:6]) for k, v in G.items() if v["n_binding"]]
    out.sort(key=lambda x: -x["dual_abs_sum"])
    return out[:top]
