"""submit_objective_spec 的 JSON Schema（LLM 函数调用）+ 校验/合并。"""
import copy
from .engine import default_spec, OBJ, CONS

OBJ_KEYS = list(OBJ); CON_KEYS = list(CONS)
SPEC_SCHEMA = {"type": "object", "properties": {
    "preset": {"type": "string", "description": "案例预置名：zhongwei_summer_coupled / ulanqab_cicdata_summer / shaoguan_summer / odense_meta_winter / helinger_typical_day"},
    "mode": {"type": "string", "enum": ["single", "weighted", "lexicographic", "pareto"], "description": "单目标/加权和/字典序(优先级)/ε-约束帕累托"},
    "objectives": {"type": "array", "items": {"type": "object", "properties": {"key": {"type": "string", "enum": OBJ_KEYS}, "weight": {"type": "number"}, "priority": {"type": "integer"}}, "required": ["key"]},
                   "description": "目标（cost=年化总成本, carbon=年净碳排放, green=外购电量最小≈绿电最大, peak=峰值购电, thermal_margin=热安全裕度最大, npv=净现值）"},
    "constraints": {"type": "array", "items": {"type": "object", "properties": {"key": {"type": "string", "enum": CON_KEYS}, "value": {"type": "number"}}, "required": ["key", "value"]},
                    "description": "硬约束：green 绿电占比下限(0-1)、carbon 年碳排上限 t、cost 年化成本上限 元、peak 峰值购电上限 MW、payback 回收期上限 年、thermal_margin 裕度下限(0-1)、pue 年均 PUE 上限"},
    "pareto": {"type": "object", "properties": {"x": {"type": "string", "enum": OBJ_KEYS}, "y": {"type": "string", "enum": OBJ_KEYS}, "n": {"type": "integer"}}},
    "decisions": {"type": "object", "description": "容量决策：wind/pv/bat_e/bat_p/tes/hs/chiller/hp → true(默认上限)/false/数值上限"},
    "cooling_modes": {"type": "array", "items": {"type": "string"}, "description": "散热方式枚举（空=保持现状）"},
    "carbon_basis": {"type": "string", "enum": ["marginal", "average"]}, "carbon_price": {"type": "number"},
    "resolution": {"description": "'full'=8760h，或代表日数（整数，如 48）"}}}

def validate(raw, base=None):
    sp = copy.deepcopy(base) if base else default_spec((raw or {}).get("preset") or "zhongwei_summer_coupled")
    raw = raw or {}; err = []
    for k in ("preset", "mode", "carbon_basis", "carbon_price", "resolution", "wind_scale", "year", "dt_hours"):
        if k in raw and raw[k] is not None: sp[k] = raw[k]
    if "objectives" in raw:
        ob = [o for o in raw["objectives"] if o.get("key") in OBJ]
        err += [f"未知目标 {o.get('key')}" for o in raw["objectives"] if o.get("key") not in OBJ]
        if ob: sp["objectives"] = [dict(key=o["key"], weight=float(o.get("weight", 1.0)), priority=int(o.get("priority", i + 1))) for i, o in enumerate(ob)]
    if "constraints" in raw:
        sp["constraints"] = [dict(key=c["key"], value=float(c["value"])) for c in raw["constraints"] if c.get("key") in CONS and c.get("value") is not None]
    if "pareto" in raw: sp["pareto"].update({k: v for k, v in raw["pareto"].items() if v is not None})
    if "decisions" in raw: sp["decisions"].update(raw["decisions"])
    if "cooling_modes" in raw: sp["cooling_modes"] = list(raw["cooling_modes"] or [])
    if sp["mode"] not in ("single", "weighted", "lexicographic", "pareto"): err.append(f"未知模式 {sp['mode']}"); sp["mode"] = "single"
    if sp["mode"] == "pareto" and (sp["pareto"].get("x") not in OBJ or sp["pareto"].get("y") not in OBJ or sp["pareto"]["x"] == sp["pareto"]["y"]):
        ks = [o["key"] for o in sp["objectives"]]; sp["pareto"] = dict(x=ks[0] if ks else "cost", y=(ks[1] if len(ks) > 1 else "carbon"), n=sp["pareto"].get("n", 7))
    return sp, err
