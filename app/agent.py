"""Agent 循环：plan -> build -> run -> check -> fix。
run_turn_events 产出事件流（供 SSE 流式前端）；run_turn 为同步封装。
每轮自动检索知识库/技能卡注入上下文（RAG）；工具异常回灌 LLM 修正，超过重试次数则终止。"""
from __future__ import annotations
import json, time, traceback
from .tools import REGISTRY, Session, call_tool
from .llm import get_llm
from . import knowledge

MAX_STEPS = 20
MAX_FIX_RETRIES = 3

SYSTEM = """你是电力系统仿真智能体（中文），擅长“算电协同”（数据中心算力负荷与电网协同）以及通用电力系统仿真。
可用仿真器工具及适用场景：
- build_scenario/run_dispatch/run_ac_check/compute_kpis/compare_baseline/make_plots/write_report：输电网算电协同 24h 优化调度(Pyomo+HiGHS)与 pandapower 交流校核
- run_matpower：MATPOWER/Octave 标准算例潮流与最优潮流
- run_andes_tds：ANDES 暂态稳定/频率响应（负荷阶跃）
- run_opendss：OpenDSS 配电馈线时序潮流（电压越限、网损）
- run_openmodelica：Modelica 物理动态模型仿真
- run_paraview_render：3D 可视化（可选）
- get_carbon_profile / run_pareto_sweep：碳强度曲线（默认 0.5306 kgCO2/kWh×合成形状）与成本-碳 Pareto 扫描（build_scenario/run_dispatch 的 carbon_weight 参数设定双目标）
- generate_jobs / load_job_trace：任务级作业（释放/截止时间/能量/最大功率/允许DC/时延敏感），链路时延/带宽/迁移能耗约束；build_scenario(n_jobs=..) 亦可直接生成
- plot_topology / plot_energy_flow：系统拓扑单线图（电压等级着色、假设/来源标注，with_flows=true 叠加交流潮流）与能流桑基图+逐时供需堆叠图（交互 ECharts）；用户问“拓扑/单线图/能流/桑基/电量去向”时使用
- show_model_topology：通用“模型拓扑+能流”视图（任意网络：母线/电压等级、支路、风/光/火/外网装机、储能、数据中心与迁移链路、电气岛、装机汇总；求解后叠加潮流与桑基）。build_scenario/run_dispatch 已自动生成，建模后请提示用户在“模型拓扑”页核对模型
- search_knowledge：检索用户上传文档与技能卡；save_skill_card：用户教授方法或说“记住/学习”时保存技能卡
工作流程：先给出简短计划，再依次调用工具；工具报错时根据错误修正参数重试；最后用中文总结关键数字。
默认数据均为合成数据，需注明。引用知识库内容时用 [来源: 文件名#块号] 标注。"""

def _jsonable(o):
    return json.loads(json.dumps(o, default=lambda x: x.item() if hasattr(x, "item") else str(x), ensure_ascii=False))

def _context_msg(user_text):
    r = knowledge.retrieve(user_text)
    lite = dict(cards=[{k: c.get(k) for k in ["id", "title", "task_type", "steps", "params", "checks", "example", "score"]} for c in r["cards"]],
                docs=[{"source": d["source"], "text": d["text"][:400]} for d in r["docs"]])
    return r, {"role": "system", "content": "[知识上下文]\n" + json.dumps(lite, ensure_ascii=False)}

def edit_context(session) -> str:
    sc = session.state["scenario"]; log = session.state.get("edit_log", [])[-15:]
    try:
        from .tools.model_viz import build_model_graph, brief
        b = brief(session.state.get("model_graph") or build_model_graph(sc))
    except Exception as e: b = {"error": str(e)}
    lr = session.state.get("last_rerun")
    return ("[模型编辑同步] 用户在“模型拓扑”页直接编辑了当前会话模型（已写入会话场景；build_scenario 不带 preset/scenario 参数时将保留该编辑后模型）。\n"
            "编辑记录：" + "；".join(f"{x['t']} {x['desc']}" for x in log) + "\n当前模型摘要：" + json.dumps(_jsonable(b), ensure_ascii=False)[:3000]
            + ("\n最近一次重新仿真前后对比：" + json.dumps(_jsonable(lr), ensure_ascii=False)[:1500] if lr else ""))

def run_turn_events(session: Session, user_text: str, llm=None):
    llm = llm or get_llm()
    if not session.messages:
        session.messages.append({"role": "system", "content": SYSTEM})
    if session.state.get("edit_unsent") and "scenario" in session.state:   # 拓扑编辑器的修改同步给智能体
        session.messages.append({"role": "system", "content": edit_context(session)}); session.state["edit_unsent"] = False
    session.messages.append({"role": "user", "content": user_text})
    start = len(session.messages) - 1
    r, ctx = _context_msg(user_text)
    if r["cards"] or r["docs"]:
        session.messages.append(ctx)
        yield {"type": "retrieval", "cards": [c["title"] for c in r["cards"]], "docs": [d["source"] for d in r["docs"]]}
    tools = [t.openai_spec() for t in REGISTRY.values()]; fails = {}
    for _ in range(MAX_STEPS):
        try:
            out = llm.chat(session.messages, tools)
        except Exception as e:
            msg = {"role": "assistant", "content": f"LLM 调用失败：{type(e).__name__}: {e}。请在“设置”中检查 LLM 配置，或启用 Mock 模式。"}
            session.messages.append(msg); yield {"type": "message", "content": msg["content"]}; break
        msg = {"role": "assistant", "content": out["content"]}
        if out["tool_calls"]:
            msg["tool_calls"] = [{"id": c["id"], "type": "function", "function": {
                "name": c["name"], "arguments": json.dumps(c["arguments"], ensure_ascii=False)}} for c in out["tool_calls"]]
        session.messages.append(msg)
        if out["content"]: yield {"type": "message", "content": out["content"], "final": not out["tool_calls"]}
        if not out["tool_calls"]: break
        abort = False; paused = False
        from . import transparency as tr
        for c in out["tool_calls"]:
            if paused or (c["name"] in tr.RUN_TOOLS and session.state.get("confirm_required") and not session.state.get("auto_run")
                          and "scenario" in session.state and not session.state.get("params_confirmed")):
                if not paused:
                    session.state["pending_calls"] = [dict(name=x["name"], args=x["arguments"]) for x in out["tool_calls"][out["tool_calls"].index(c):]]
                    session.state["wf_step"] = "params"
                paused = True
                session.messages.append({"role": "tool", "tool_call_id": c["id"], "name": c["name"],
                                         "content": json.dumps({"ok": False, "paused": True, "note": "等待用户在参数表中确认参数后再运行"}, ensure_ascii=False)})
                continue
            if out["content"]: session.state["_why"] = out["content"][:300]
            yield {"type": "tool_start", "id": c["id"], "name": c["name"], "args": c["arguments"], "step": tr.TOOL_STEP.get(c["name"], "run"),
                   "why": out["content"] or tr.TOOL_WHY.get(c["name"], "")}
            t0 = time.time()
            try:
                if "__parse_error__" in c["arguments"]: raise ValueError("工具参数不是合法 JSON")
                res = _jsonable(call_tool(session, c["name"], c["arguments"]))
            except Exception as e:
                fails[c["name"]] = fails.get(c["name"], 0) + 1
                res = {"ok": False, "error": f"{type(e).__name__}: {e}", "retry": fails[c["name"]],
                       "hint": "请根据错误修正参数后重试", "trace": traceback.format_exc(limit=2)[-600:]}
                if fails[c["name"]] > MAX_FIX_RETRIES: abort = True
            session.messages.append({"role": "tool", "tool_call_id": c["id"], "name": c["name"],
                                     "content": json.dumps(res, ensure_ascii=False)})
            yield {"type": "tool_end", "id": c["id"], "name": c["name"], "ok": bool(res.get("ok")),
                   "elapsed_s": round(time.time()-t0, 2), "result": res, "artifacts": list(session.artifacts), "step": tr.TOOL_STEP.get(c["name"], "run"),
                   "log": (session.state.get("runlog") or [None])[-1]}
        if paused:
            m = ("⏸ 模型与参数已准备好，**运行前需要你确认**。请在右侧「② 输入参数」核对参数（橙色=智能体推断，灰色=默认值），"
                 "必要时修改，然后点击「✅ 确认参数并运行」。若希望以后自动运行，可打开「自动运行」开关。")
            session.messages.append({"role": "assistant", "content": m})
            yield {"type": "confirm_needed", "pending": [x["name"] for x in session.state["pending_calls"]]}
            yield {"type": "message", "content": m, "final": True}; break
        if abort:
            m = f"工具多次失败（>{MAX_FIX_RETRIES} 次），已停止。请检查场景参数。"
            session.messages.append({"role": "assistant", "content": m}); yield {"type": "message", "content": m, "final": True}
            break
    cites = sorted(set(session.state.pop("citations", []) + [d["source"] for d in r["docs"]]))
    yield {"type": "done", "citations": cites, "artifacts": list(session.artifacts), "new_messages": session.messages[start:]}

def run_turn(session: Session, user_text: str, llm=None) -> list:
    for ev in run_turn_events(session, user_text, llm):
        if ev["type"] == "done": return ev["new_messages"]
    return []
