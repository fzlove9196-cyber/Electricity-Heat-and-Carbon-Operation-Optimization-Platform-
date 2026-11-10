"""自然语言 → 结构化目标规格（ObjectiveSpec）。真实 LLM 走函数调用 submit_objective_spec；Mock/失败时用本规则解析器。"""
import re, copy
from .engine import default_spec, OBJ

SITES = [(("乌兰察布", "中金", "ulanqab"), "ulanqab_cicdata_summer"), (("韶关", "华南数谷", "shaoguan", "广东"), "shaoguan_summer"),
         (("欧登塞", "odense", "丹麦", "meta"), "odense_meta_winter"), (("中卫", "宁夏", "zhongwei"), "zhongwei_summer_coupled"),
         (("和林格尔", "helinger"), "helinger_typical_day")]
KW = {"cost": ("经济性", "经济", "成本", "费用", "省钱", "花钱", "电费", "投资最省"), "carbon": ("碳排", "碳最", "碳权重", "低碳", "减碳", "碳中和", "零碳", "排放"),
      "peak": ("峰值购电", "需量", "峰值功率", "购电峰值"), "green": ("绿电占比最高", "绿电最大", "绿电最多", "绿电比例最高"),
      "thermal_margin": ("热安全", "冷量裕度", "安全裕度", "热裕度"), "npv": ("净现值", "npv", "NPV")}
INTENT = ("寻优", "经济性最优", "碳排放最优", "碳最优", "成本最优", "容量规划", "配置寻优", "8760", "多花多少钱", "【目标规格】",
          "全年规划", "全年优化", "帕累托前沿", "折中方案", "膝点")
def is_opt(text): return any(k in text for k in INTENT)

def _num(pat, t, f=float):
    m = re.search(pat, t, re.I); return f(m.group(1)) if m else None

def parse(text, prev=None, preset_hint=None):
    """返回 (spec, notes)。prev：上一轮规格（多轮对话中“在此基础上”修改）。"""
    t = text.strip(); notes = []
    sp = copy.deepcopy(prev) if prev else None
    pre = next((p for kws, p in SITES if any(k.lower() in t.lower() for k in kws)), None)
    if sp is None or (pre and pre != sp["preset"]):
        sp = default_spec(pre or (prev or {}).get("preset") or preset_hint or "zhongwei_summer_coupled"); sp["constraints"] = []
        notes.append(f"案例：{sp['preset']}" + ("（按地名识别）" if pre else "（沿用当前/默认）"))
    found = [k for k, kws in KW.items() if any(w in t for w in kws)]
    if "绿电" in t and "green" not in found and re.search(r"绿电[^，,。；]*?(最大|最高|尽量高)", t): found.append("green")
    if "npv" in found and "cost" in found: found.remove("npv")
    # 约束（硬）——出现“不低于/不超过/≤/≥/以内”等即视为硬约束，从目标里剔除
    cons = {c["key"]: c for c in sp["constraints"]}
    def put(k, v, why): cons[k] = dict(key=k, value=v); notes.append(f"硬约束 {why}")
    v = _num(r"绿电(?:占比|比例)?\s*(?:不低于|不少于|至少|达到|≥|>=|大于等于|高于)\s*(\d+(?:\.\d+)?)\s*%", t)
    if v is not None: put("green", v/100, f"绿电占比 ≥ {v:g}%")
    m = re.search(r"碳排放?(?:量)?\s*(?:不超过|不高于|≤|<=|低于|控制在)\s*(\d+(?:\.\d+)?)\s*(万)?\s*吨", t)
    if m: put("carbon", float(m.group(1))*(1e4 if m.group(2) else 1), f"年碳排放 ≤ {m.group(1)}{m.group(2) or ''}吨")
    v = _num(r"回收期\s*(?:不超过|不高于|≤|<=|小于|低于|在)?\s*(\d+(?:\.\d+)?)\s*年", t)
    if v is not None: put("payback", v, f"投资回收期 ≤ {v:g} 年")
    v = _num(r"峰值购电\s*(?:不超过|≤|<=|低于|控制在)\s*(\d+(?:\.\d+)?)\s*MW", t)
    if v is not None: put("peak", v, f"峰值购电 ≤ {v:g} MW"); found = [k for k in found if k != "peak"] if "最" not in t.split("峰值")[0][-3:] else found
    v = _num(r"PUE\s*(?:不超过|不高于|≤|<=|低于|小于)\s*(\d\.\d+)", t)
    if v is not None: put("pue", v, f"年均 PUE ≤ {v:g}")
    v = _num(r"(?:热安全|冷量)?裕度\s*(?:不低于|≥|>=|至少)\s*(\d+(?:\.\d+)?)\s*%", t)
    if v is not None: put("thermal_margin", v/100, f"热安全裕度 ≥ {v:g}%"); found = [k for k in found if k != "thermal_margin"]
    m = re.search(r"(?:预算|年化?成本|总成本)\s*(?:不超过|≤|<=|控制在|以内)?\s*(\d+(?:\.\d+)?)\s*(亿|万)元?", t)
    if m and re.search(r"不超过|≤|<=|控制在|以内", t): put("cost", float(m.group(1))*(1e8 if m.group(2) == "亿" else 1e4), f"年化成本 ≤ {m.group(1)}{m.group(2)}元"); found = [k for k in found if k != "cost"]
    if "green" in cons and found == ["green"]: found = []
    if "carbon" in cons and "carbon" in found and not re.search(r"碳[^，,。]*最", t): found.remove("carbon")
    for k in re.findall(r"(?:去掉|取消|不要)(绿电|碳排放|回收期|峰值|PUE|裕度)约束", t):
        kk = {"绿电": "green", "碳排放": "carbon", "回收期": "payback", "峰值": "peak", "PUE": "pue", "裕度": "thermal_margin"}[k]; cons.pop(kk, None); notes.append(f"移除约束 {k}")
    sp["constraints"] = list(cons.values())
    # 目标与模式
    if found:
        pri = sorted(found, key=lambda k: min(t.find(w) for w in KW.get(k, ("绿电",)) if w in t) if any(w in t for w in KW.get(k, ("绿电",))) else 99)
        sp["objectives"] = [dict(key=k, weight=1.0, priority=i + 1) for i, k in enumerate(pri)]
        for o in sp["objectives"]:
            w = _num(OBJ_W.get(o["key"], "^$"), t)
            if w is not None: o["weight"] = w
        if len(pri) >= 2:
            if "加权" in t or "权重" in t: sp["mode"] = "weighted"
            elif re.search(r"优先|首先|先.{0,8}再|其次", t): sp["mode"] = "lexicographic"
            else: sp["mode"] = "pareto"; sp["pareto"] = dict(x=pri[0] if pri[0] != "thermal_margin" else pri[1], y=pri[1] if pri[0] != "thermal_margin" else pri[0], n=sp["pareto"].get("n", 7))
        else:
            sp["mode"] = "single"
        if sp["mode"] == "pareto" and "cost" in pri and pri[0] != "cost": sp["pareto"] = dict(x="cost", y=[k for k in pri if k != "cost"][0], n=sp["pareto"].get("n", 7))
        notes.append("目标：" + "、".join(OBJ[k][0] for k in pri) + f"；模式 {sp['mode']}")
    elif any(k in t for k in ("帕累托", "权衡", "前沿", "折中")):
        sp["mode"] = "pareto"; notes.append("模式 pareto（成本-碳）")
    n = _num(r"(\d+)\s*个(?:点|方案)", t, int)
    if n: sp["pareto"]["n"] = max(3, min(15, n))
    # 决策变量
    for cn, k in (("风电", "wind"), ("光伏", "pv"), ("电池", "bat_e"), ("储能", "bat_e"), ("蓄冷", "tes"), ("储冷", "tes"), ("蓄热", "hs"), ("储热", "hs"), ("热泵", "hp"), ("冷机", "chiller")):
        if re.search(rf"(?:不新增|不建|不加|不扩|不考虑|不投资?)\s*{cn}", t):
            sp["decisions"][k] = False; notes.append(f"不新增{cn}")
            if k == "bat_e": sp["decisions"]["bat_p"] = False
        m = re.search(rf"{cn}\s*(?:新增)?(?:上限|最多|不超过)\s*(\d+(?:\.\d+)?)\s*(MW|MWh)?", t)
        if m: sp["decisions"][k] = float(m.group(1)); notes.append(f"{cn}新增上限 {m.group(1)}")
        elif re.search(rf"(?<!不)(?:考虑|加上|允许|新增|扩建)\s*{cn}", t): sp["decisions"][k] = True
    if re.search(r"只(?:优化)?运行|不新增投资|不投资|现有设备", t):
        sp["decisions"] = {k: False for k in sp["decisions"]}; notes.append("仅运行优化（无容量决策）")
    if re.search(r"散热方式|冷却方式|液冷|风冷", t) and re.search(r"选|比较|枚举|对比|考虑|哪种", t):
        sp["cooling_modes"] = ["air_chw", "air_iec", "liquid_cold_plate", "liquid_immersion"]; notes.append("散热方式枚举 4 种")
    if "平均碳因子" in t or "平均因子" in t or "平均排放因子" in t: sp["carbon_basis"] = "average"; notes.append("碳因子：省级平均")
    elif "边际" in t: sp["carbon_basis"] = "marginal"; notes.append("碳因子：逐时边际")
    v = _num(r"碳价\s*[=为:：]?\s*(\d+(?:\.\d+)?)", t)
    if v is not None: sp["carbon_price"] = v; notes.append(f"碳价 {v:g} 元/t")
    k = _num(r"(\d+)\s*个?代表日", t, int)
    if k: sp["resolution"] = k
    elif re.search(r"8760|全年逐时|精确|完整全年", t): sp["resolution"] = "full"
    elif "快速" in t: sp["resolution"] = 24
    elif prev is None or found: sp["resolution"] = 48 if sp["mode"] == "pareto" else "full"
    v = _num(r"风(?:电|速)?(?:校准|放大|系数)\s*[=为:：×x]?\s*(\d+(?:\.\d+)?)", t)
    if v is not None: sp["wind_scale"] = v
    return sp, notes

OBJ_W = {"cost": r"成本(?:的)?权重\s*[=为:：]?\s*(\d+(?:\.\d+)?)", "carbon": r"碳(?:排放)?(?:的)?权重\s*[=为:：]?\s*(\d+(?:\.\d+)?)",
         "peak": r"峰值(?:的)?权重\s*[=为:：]?\s*(\d+(?:\.\d+)?)", "thermal_margin": r"裕度(?:的)?权重\s*[=为:：]?\s*(\d+(?:\.\d+)?)"}

def followup(text):
    """识别追问：('abate', pct) / ('show', label) / ('why', label) / None"""
    m = re.search(r"再(?:降|减|少)\s*(\d+(?:\.\d+)?)\s*%\s*(?:的)?碳", text) or re.search(r"碳(?:排放)?再(?:降|减)\s*(\d+(?:\.\d+)?)\s*%", text)
    if m: return ("abate", float(m.group(1))/100)
    m = re.search(r"(?:查看|看看|展开|详情)\s*(方案\s*\d+)", text)
    if m: return ("show", m.group(1).replace(" ", ""))
    m = re.search(r"为什么.*?(方案\s*\d+|成本最优|碳最优|折中|膝点)", text)
    if m: return ("why", m.group(1).replace(" ", ""))
    return None
