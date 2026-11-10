"""LLM 客户端：OpenAI 兼容接口 + 确定性 Mock（LLM_MOCK=1）。
统一返回: {"content": str|None, "tool_calls": [{"id","name","arguments"(dict)}]}"""
from __future__ import annotations
import json, os, re
from . import settings

class OpenAILLM:
    def __init__(self):
        from openai import OpenAI
        self.client = OpenAI(base_url=settings.get("LLM_BASE_URL") or None, api_key=settings.get("LLM_API_KEY") or "none")
        self.model = settings.get("LLM_MODEL", "gpt-4o-mini")

    def chat(self, messages, tools):
        r = self.client.chat.completions.create(model=self.model, messages=messages, tools=tools,
                                                tool_choice="auto", temperature=0.2)
        m = r.choices[0].message
        calls = []
        for tc in m.tool_calls or []:
            try: args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError: args = {"__parse_error__": tc.function.arguments}
            calls.append(dict(id=tc.id, name=tc.function.name, arguments=args))
        return {"content": m.content, "tool_calls": calls}

CN_NUM = {"一": 1, "两": 2, "二": 2, "三": 3}

def parse_request(text: str) -> dict:
    a = {}
    from .scenario import preset_from_text
    pre = preset_from_text(text)
    th = thermal_args(text)
    if pre:
        a["preset"] = pre
        if th.get("dr_mw") is not None: a["dr_mw"] = th["dr_mw"]
        if th.get("dr_window"): a["dr_window"] = th["dr_window"]
        m = re.search(r"碳权重\s*[=为:：]?\s*(\d+(?:\.\d+)?)", text)
        if m: a["carbon_weight"] = float(m.group(1))
        m = re.search(r"碳价\s*[=为:：]?\s*(\d+(?:\.\d+)?)", text)
        if m: a["carbon_price_cny_t"] = float(m.group(1))
        return a
    m = re.search(r"([一两二三123])\s*个数据中心", text)
    if m: a["n_dc"] = CN_NUM.get(m.group(1)) or int(m.group(1))
    m = re.search(r"(\d+(?:\.\d+)?)\s*MWh", text, re.I)
    if m and ("储能" in text or "电池" in text): a["storage_mwh"] = float(m.group(1))
    m = re.search(r"(\d+)\s*号?母线", text)
    if m and "storage_mwh" in a: a["storage_bus"] = int(m.group(1))
    if "峰谷" in text or "分时" in text: a["price_kind"] = "peak_valley"
    elif "平价" in text or "固定电价" in text: a["price_kind"] = "flat"
    # ---- Phase 1：碳 / 任务 ----
    if is_carbon(text):
        m = re.search(r"碳权重\s*[=为:：]?\s*(\d+(?:\.\d+)?)", text)
        a["carbon_weight"] = float(m.group(1)) if m else 5.0
        m = re.search(r"碳价\s*[=为:：]?\s*(\d+(?:\.\d+)?)", text)
        if m: a["carbon_price_cny_t"] = float(m.group(1))
        if any(k in text for k in ["多区域", "西部", "跨区域", "两区域"]): a["multi_region"] = True
    if is_jobs(text):
        m = re.search(r"(\d+)\s*个(?:任务|作业)", text)
        a["n_jobs"] = int(m.group(1)) if m else 30
    a.update(th)
    # VCC / 硬件功率（写入 scenario JSON 字段；build_scenario 透传）
    if is_vcc(text):
        a["vcc_mode"] = "carbon"
        if any(k in text for k in ["电价", "电费", "峰谷"]): a["vcc_mode"] = "price"
        if "加权" in text: a["vcc_mode"] = "weighted"
        a["vcc_stage"] = "day_ahead" if any(k in text for k in ["日前", "两阶段", "day-ahead", "day_ahead"]) else "joint"
    if is_pwr(text):
        a["power_model"] = "pdu_pwl" if "PDU" in text or "pdu" in text else "idle_dynamic"
        m = re.search(r"idle\s*[=为:：]?\s*(\d+(?:\.\d+)?)\s*%", text, re.I)
        if m: a["idle_frac"] = float(m.group(1))/100.0
        else:
            m = re.search(r"idle\s*[=为:：]?\s*0?\.(\d+)", text, re.I)
            if m: a["idle_frac"] = float("0."+m.group(1))
            else: a["idle_frac"] = 0.4
    return a

THERMAL_KW = ["虚拟储冷", "虚冷", "预冷", "蓄冷", "余热", "供热", "供暖", "虚拟储热", "虚热", "需求响应", "削峰", "热安全", "入口温度", "pue", "热耦合",
              "算电热碳", "算-电-热", "冷却", "热浪", "高温"]
def is_thermal(text): return any(k in text.lower() for k in THERMAL_KW)

def thermal_args(text: str) -> dict:
    """算-电-热-碳 耦合关键词 -> build_scenario 参数（Mock 解析）。"""
    if not is_thermal(text): return {}
    a = {"thermal": True}
    if any(k in text for k in ["余热", "供热", "供暖", "虚拟储热", "虚热"]): a["heat_recovery"] = True
    if any(k in text for k in ["热浪", "高温", "压力测试"]): a["heatwave"] = True
    if any(k in text for k in ["蓄冷", "虚拟储冷", "虚冷"]): a["tes"] = True
    if any(k in text for k in ["需求响应", "削峰", "DR"]):
        m = re.search(r"(\d+(?:\.\d+)?)\s*MW", text, re.I); a["dr_mw"] = float(m.group(1)) if m else None
        m = re.search(r"(\d{1,2})\s*[-–~到至]\s*(\d{1,2})\s*[点时]", text)
        if m: a["dr_window"] = [int(m.group(1)), int(m.group(2))]
    return a

PARETO_KW = ["pareto", "帕累托", "权衡", "碳权重扫描", "多目标"]
JOB_KW = ["任务", "作业", "截止时间", "截止期", "deadline", "迁移带宽", "时延约束"]
VCC_KW = ["VCC", "vcc", "虚拟容量", "碳智能", "日前整形", "容量曲线", "Carbon-Intelligent"]
PWR_KW = ["idle功率", "空载功率", "硬件功率", "功率模型", "PDU功率", "idle+动态", "Fan功率"]
TIER_KW = ["日前基线", "定基线", "保存基线", "日内滚动", "滚动校准", "滚动重调度", "可行响应域", "灵活包络",
           "上下调", "实时跟踪", "MPC-lite", "mpc-lite", "预测补丁", "风电少", "光伏少", "负载率冷却", "耦合报告",
           "三级优化", "reoptimize", "envelope", "SOC实测", "SOC测量", "荷电状态实测",
           "配置UPS", "接入柴发", "备用电源", "UPS参数", "柴发参数", "断电应急", "进入应急", "退出应急"]
MARKET_KW = ["运营沙盘", "沙盘申报", "量价申报", "日前申报", "聚合台账", "资源聚合", "需求响应基线", "结算复盘", "偏差考核", "申报审批", "审计记录", "交易闭环", "运营闭环"]
def is_market(text): return any(k in text for k in MARKET_KW)
def is_tier(text): return any(k in text for k in TIER_KW)
def is_pareto(text): return any(k in text.lower() for k in PARETO_KW)
def is_carbon(text): return "碳" in text or is_pareto(text) or "carbon" in text.lower()
def is_jobs(text): return any(k in text.lower() for k in JOB_KW)
def is_vcc(text): return any(k in text for k in VCC_KW)
def is_pwr(text): return any(k in text for k in PWR_KW)
def is_phase1(text): return is_carbon(text) or is_jobs(text) or is_thermal(text) or is_vcc(text) or is_pwr(text)

PLAN = [("build_scenario", None), ("run_dispatch", {"case": "optimized"}), ("run_dispatch", {"case": "baseline"}),
        ("run_ac_check", {}), ("compute_kpis", {"case": "optimized"}), ("compare_baseline", {}),
        ("make_plots", {}), ("write_report", {})]

def route(text: str) -> list:
    """中文意图 -> 工具计划（Mock 用；真实 LLM 由工具 description 自行选择）。"""
    t = text.lower(); plans = []
    if any(k in text for k in ["记住", "学习", "学会"]):
        return [("save_skill_card", teach_card(text))]
    from .tools.cfg_tools import parse_cfg_text
    from .opt import nl as _onl
    if is_market(text):
        from .tools.market_tools import _case
        cs = [k for k in ("zhongwei", "ulanqab", "shaoguan") if _case(text) == k] or ["zhongwei"]
        if any(a in text for a in ["乌兰察布"]) and "ulanqab" not in cs: cs.append("ulanqab")
        if "韶关" in text and "shaoguan" not in cs: cs.append("shaoguan")
        if "中卫" in text and "zhongwei" not in cs: cs.insert(0, "zhongwei")
        if any(k in text for k in ["审计记录"]) and not any(k in text for k in ["闭环", "申报", "结算"]):
            return [("market_audit", {})]
        if any(k in text for k in ["聚合台账", "资源聚合"]) and not any(k in text for k in ["闭环", "申报", "结算"]):
            return [("market_portfolio", {"case": c}) for c in cs]
        return [("market_closed_loop", {"case": c}) for c in cs] + [("market_audit", {"limit": 5})]
    if is_tier(text):
        plans = []
        if any(k in text for k in ["预测补丁", "风电少", "光伏少", "风光少", "负荷上涨", "电价涨"]):
            plans.append(("apply_forecast_patch", {"text": text}))
        if any(k in text for k in ["日前基线", "定基线", "保存基线"]):
            plans.append(("save_day_ahead_baseline", {}))
        if any(k in text for k in ["配置UPS", "接入柴发", "备用电源", "UPS与柴发", "柴发与UPS"]):
            plans.append(("configure_backup_resources", {
                "ups": True if any(k in text for k in ["UPS", "ups", "备用电源"]) else None,
                "diesel": True if any(k in text for k in ["柴发", "柴油", "备用电源"]) else None,
                "emergency_mode": True if any(k in text for k in ["应急", "断电"]) else None,
            }))
        if any(k in text for k in ["UPS参数", "柴发参数", "备用资源"]):
            plans.append(("list_backup_resources", {}))
        if any(k in text for k in ["进入应急", "断电模式", "断电应急"]) and "退出" not in text:
            plans.append(("set_emergency_mode", {"enabled": True}))
        if any(k in text for k in ["退出应急"]):
            plans.append(("set_emergency_mode", {"enabled": False}))
        if any(k in text for k in ["日内滚动", "滚动校准", "滚动重调度", "reoptimize", "SOC实测", "SOC测量", "荷电状态实测"]):
            if not any(x[0] == "save_day_ahead_baseline" for x in plans):
                plans.append(("save_day_ahead_baseline", {}))
            plans.append(("reoptimize_intraday", {"text_patch": text, "from_t": 8}))
            plans.append(("report_load_cooling_coupling", {"case": "intra_day"}))
        if any(k in text for k in ["可行响应域", "灵活包络", "上下调", "envelope"]):
            if not any(x[0] == "save_day_ahead_baseline" for x in plans):
                plans.append(("save_day_ahead_baseline", {}))
            st = "real_time" if "实时" in text else ("intra_day" if any(k in text for k in ["日内", "滚动"]) else "day_ahead")
            plans.append(("compute_flexibility_envelope", {"stage": st, "stride": 2}))
        if any(k in text for k in ["实时跟踪", "MPC-lite", "mpc-lite", "秒级跟踪", "冷却跟踪"]):
            plans.append(("run_realtime_track", {"mode": "rules" if "规则" in text else "mpc_lite"}))
        if any(k in text for k in ["负载率冷却", "耦合报告", "双层对照"]):
            plans.append(("report_load_cooling_coupling", {}))
        if any(k in text for k in ["三级优化", "三级时间线"]):
            plans = [("save_day_ahead_baseline", {}), ("reoptimize_intraday", {"text_patch": text, "from_t": 8}),
                     ("compute_flexibility_envelope", {"stage": "day_ahead", "stride": 4}),
                     ("compute_flexibility_envelope", {"stage": "intra_day", "stride": 4}),
                     ("run_realtime_track", {"mode": "mpc_lite"}), ("get_tier_timeline", {})]
        if plans:
            plans.append(("get_tier_timeline", {}))
            return plans
    if _onl.is_opt(text):
        fu = _onl.followup(text)
        if fu and fu[0] == "abate": return [("query_abatement", {"pct": fu[1]})]
        return [("submit_objective_spec", {"text": text}), ("run_optimization", {})]
    if any(k in text for k in ["余热供暖", "末端温度", "供暖靠谱", "余热可行"]) and any(k in text for k in ["可行", "靠谱", "满足", "末端"]):
        return [("build_config", {"set": parse_cfg_text(text)}), ("heat_feasibility_study", {})]
    if any(k in text for k in ["散热方式", "风冷", "液冷", "冷板", "浸没", "配置对比", "参数扫描", "容量扫描"]) and any(k in text for k in ["对比", "比较", "扫描", "sweep"]):
        sw = {"params": [{"path": "battery.energy_mwh", "values": [0, 100, 200, 400]}]} if ("储能" in text and "扫描" in text) else {}
        return [("build_config", {"set": parse_cfg_text(text)}), ("run_config_sweep", sw)]
    if any(k in text for k in ["配置构建", "新建配置", "从零配置", "自定义配置"]):
        return [("build_config", {"set": parse_cfg_text(text)}), ("run_dispatch", {"case": "optimized"}), ("compute_kpis", {"case": "optimized"})]
    if any(k in text for k in ["建模", "模型拓扑", "核对模型", "装机"]) and "matpower" not in t:   # 通用建模视图：先建模核对，可选求解
        pl = [("build_scenario", parse_request(text)), ("show_model_topology", {})]
        if any(k in text for k in ["调度", "优化", "运行", "求解", "能流"]): pl += [("run_dispatch", {"case": "optimized"}), ("show_model_topology", {})]
        return pl
    if any(k in text for k in ["拓扑", "单线图", "能流", "桑基", "sankey"]) and "matpower" not in t:
        return [("build_scenario", parse_request(text)), ("run_dispatch", {"case": "optimized"}), ("run_dispatch", {"case": "baseline"}),
                ("plot_topology", {"with_flows": "潮流" in text}), ("plot_energy_flow", {})]
    if any(k in text for k in ["知识库", "文档", "资料", "根据上传"]):
        plans.append(("search_knowledge", {"query": text}))
    num = lambda pat, d: float(m.group(1)) if (m := re.search(pat, text, re.I)) else d
    if any(k in t for k in ["matpower", "octave"]) or ("最优潮流" in text and "数据中心" not in text):
        case = (re.search(r"case\s*(\d+)", t) or re.search(r"(\d+)\s*节点", text))
        mode = "runpf" if ("潮流" in text and "最优" not in text) else "runopf"
        plans.append(("run_matpower", {"case": f"case{case.group(1)}" if case else "case14", "mode": mode}))
    if "andes" in t or (any(k in t for k in ["暂态", "稳定", "频率响应", "时域"]) and "modelica" not in t):
        plans.append(("run_andes_tds", {"step_mw": num(r"(\d+(?:\.\d+)?)\s*MW", 50)}))
    if any(k in t for k in ["opendss", "配网", "配电", "馈线"]):
        a = {"dc_kw": num(r"(\d+(?:\.\d+)?)\s*kW", 3000)}
        if "储能" in text: a["storage_kwh"] = num(r"(\d+(?:\.\d+)?)\s*kWh", 4000)
        plans.append(("run_opendss", a))
    if any(k in t for k in ["modelica", "openmodelica", "omc"]):
        plans.append(("run_openmodelica", {"model_name": "PowerSystems.Examples.PowerWorld.PowerWorld", "stop_time": 60}
                      if "powersystems" in t or "powerworld" in t else {"step_pu": num(r"(\d+(?:\.\d+)?)\s*pu", 0.1)}))
    if len(plans) > 1 or (plans and plans[0][0] != "search_knowledge"):
        if any(k in t for k in ["paraview", "3d", "三维"]):
            plans = [("build_scenario", {}), ("run_dispatch", {}), ("run_ac_check", {})] + plans + [("run_paraview_render", {})]
        return plans
    if any(k in t for k in ["paraview", "3d", "三维"]):
        return [("build_scenario", parse_request(text)), ("run_dispatch", {}), ("run_ac_check", {}), ("run_paraview_render", {})]
    if plans and not any(k in text for k in ["调度", "优化", "仿真", "分析"]):
        return plans
    plan = [(n, parse_request(text) if a is None else a) for n, a in PLAN]
    if is_carbon(text):
        plan.insert(1, ("get_carbon_profile", {}))
    if is_pareto(text):
        plan.insert(2, ("run_pareto_sweep", {}))
    return plans + plan

def plan_from_cards(messages) -> list | None:
    """若本轮知识上下文中有高分技能卡且其步骤列出了工具名，则按卡片步骤执行（技能复用）。"""
    from .tools import REGISTRY
    ctx = [m for m in messages if m["role"] == "system" and m["content"].startswith("[知识上下文]")]
    if not ctx: return None
    try: cards = json.loads(ctx[-1]["content"].split("\n", 1)[1])["cards"]
    except Exception: return None
    builtin = max([c.get("score", 0) for c in cards if c.get("id") == "builtin_sdco"] or [0])
    for c in cards:
        if c.get("id") == "builtin_sdco" or c.get("score", 0) < 2 or c.get("score", 0) <= builtin: continue
        names = [n for n in re.findall(r"[a-z_]+", c.get("steps", "")) if n in REGISTRY]
        if names:
            args = {}
            try: args = json.loads(c.get("params") or "{}")
            except Exception: pass
            return [(n, args.get(n, {})) for n in names]
    return None

def teach_card(text: str) -> dict:
    """Mock：从“记住：<标题>。步骤：...；参数：...；校验：...”中抽取技能卡字段。"""
    body = re.sub(r"^.*?(记住|学习|学会)[：:，, ]*", "", text, count=1)
    grab = lambda k: (m.group(1).strip().rstrip("。；;，, ") if (m := re.search(k + r"[：:](.*?)(?=(步骤|参数|校验|检查|示例|关键词)[：:]|$)", body, re.S)) else "")
    title = re.split(r"[。；;\n]|步骤[：:]", body)[0].strip()[:40] or "用户技能"
    return dict(title=title, task_type=grab("类型") or title, keywords=grab("关键词") or title,
                steps=grab("步骤") or body, params=grab("参数"), checks=grab("校验") or grab("检查"), example=grab("示例"))

class MockLLM:
    """确定性：根据本轮已完成的工具调用推进固定计划；工具报错时做一次“修复”（回退默认参数）。"""
    def chat(self, messages, tools):
        last_user = max(i for i, m in enumerate(messages) if m["role"] == "user")
        user = messages[last_user]["content"]; turn = messages[last_user+1:]
        done = [m for m in turn if m["role"] == "tool"]
        ok_names = [m["name"] for m in done if json.loads(m["content"]).get("ok")]
        if done and not json.loads(done[-1]["content"]).get("ok"):
            failed = done[-1]["name"]
            if failed == "build_scenario":   # 修复：回退到默认场景
                return self._call(len(done), "build_scenario", {"n_dc": 3}, "参数有误，改用默认场景重试。")
        plan = route(user)
        pure_qa = [n for n, _ in plan] == ["search_knowledge"]        # 纯知识问答不套用技能卡流程
        from .scenario import preset_from_text
        if plan[0][0] != "save_skill_card" and not is_phase1(user) and not pure_qa and not preset_from_text(user):   # 预设项目场景也走内置计划   # Phase 1 关键词优先走内置计划
            plan = plan_from_cards(messages) or plan
        step = len(ok_names)   # 每成功一步推进一步
        if step >= len(plan):
            txt = "已完成：" + " → ".join(n for n, _ in plan) + "。结果见 artifacts（默认数据为合成数据）。"
            for m in done:
                r = json.loads(m["content"])
                if m["name"] == "search_knowledge" and r.get("docs"):
                    d = r["docs"][0]; txt = f"根据知识库检索结果：\n\n> {d['text'][:300]}\n\n[来源: {d['source']}]\n\n" + txt
                if m["name"] == "save_skill_card": txt = f"已记住，保存为技能卡「{r['title']}」（id {r['card_id']}），类似任务将自动复用。"
            return {"content": txt, "tool_calls": []}
        name, args = plan[step]
        content = f"计划：{' → '.join(n for n, _ in plan)}" if step == 0 else None
        return self._call(len(done), name, args, content)

    @staticmethod
    def _call(i, name, args, content=None):
        return {"content": content, "tool_calls": [dict(id=f"mock_{i}_{name}", name=name, arguments=args)]}

def get_llm():
    return MockLLM() if settings.get("LLM_MOCK", "0") == "1" else OpenAILLM()
