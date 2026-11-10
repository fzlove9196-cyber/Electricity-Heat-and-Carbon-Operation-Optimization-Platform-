"""研究编排的 LLM 接口（OpenAI 兼容 function calling，供应商无关）。
Mock 模式或调用失败 → 返回 None，编排器走确定性规则；LLM 只负责“决策/解释”，所有数字来自仿真结果。"""
from __future__ import annotations
import json
from .. import settings

def is_mock() -> bool:
    return settings.get("LLM_MOCK", "0") == "1" or not (settings.get("LLM_API_KEY") or settings.get("LLM_BASE_URL"))

SCHEMAS = {
    "submit_problem_card": {
        "description": "把用户的中文研究问题形式化为研究问题卡，并列出需要澄清的关键缺失信息（每项给 2-4 个选项与默认值）。",
        "parameters": {"type": "object", "required": ["topic", "research_question", "decision_variables", "constraints", "kpis", "assumptions"], "properties": {
            "topic": {"type": "string", "enum": ["heat_recovery", "heatwave_dr", "generic"], "description": "研究模板"},
            "research_question": {"type": "string"},
            "decision_variables": {"type": "array", "items": {"type": "string"}},
            "constraints": {"type": "array", "items": {"type": "string"}},
            "kpis": {"type": "array", "items": {"type": "string"}},
            "scenarios": {"type": "array", "items": {"type": "string"}},
            "assumptions": {"type": "array", "items": {"type": "string"}},
            "missing_info": {"type": "array", "items": {"type": "object", "required": ["id"], "properties": {
                "id": {"type": "string", "description": "必须取自给定的候选澄清问题 id"}, "why": {"type": "string"}}}}}}},
    "decide_next": {
        "description": "根据诊断结果决定研究下一步。只能从 candidates 中选择一个 id。",
        "parameters": {"type": "object", "required": ["choice", "rationale"], "properties": {
            "choice": {"type": "string", "description": "候选动作 id"}, "rationale": {"type": "string", "description": "中文理由（≤80字），不得编造数字"}}}},
    "narrate_conclusions": {
        "description": "为已计算好的工程结论写中文解读；只能引用 evidence 中给出的数字。",
        "parameters": {"type": "object", "required": ["items"], "properties": {"items": {"type": "array", "items": {"type": "object", "required": ["id", "narrative"], "properties": {
            "id": {"type": "string"}, "narrative": {"type": "string"}}}}}}},
}

def call(fn: str, system: str, user: dict | str):
    """强制调用指定函数；返回 arguments dict 或 None（Mock/失败）。"""
    if is_mock(): return None
    try:
        from ..llm import OpenAILLM
        L = OpenAILLM(); sp = SCHEMAS[fn]
        tools = [{"type": "function", "function": {"name": fn, **sp}}]
        msgs = [{"role": "system", "content": system}, {"role": "user", "content": user if isinstance(user, str) else json.dumps(user, ensure_ascii=False)}]
        try:
            r = L.client.chat.completions.create(model=L.model, messages=msgs, tools=tools, tool_choice={"type": "function", "function": {"name": fn}}, temperature=0.1)
        except Exception:   # 部分兼容端点不支持强制 tool_choice
            r = L.client.chat.completions.create(model=L.model, messages=msgs, tools=tools, tool_choice="auto", temperature=0.1)
        m = r.choices[0].message
        for tc in m.tool_calls or []:
            if tc.function.name == fn: return json.loads(tc.function.arguments or "{}")
        txt = (m.content or "").strip().strip("`").removeprefix("json")
        return json.loads(txt[txt.find("{"): txt.rfind("}") + 1]) if "{" in txt else None
    except Exception as e:
        print("[research.llm] fallback:", type(e).__name__, str(e)[:200]); return None
