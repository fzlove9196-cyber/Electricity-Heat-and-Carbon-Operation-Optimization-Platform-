"""知识库 / 技能卡工具（供 Agent 调用）。"""
from .base import tool, Session
from .. import knowledge as kb

@tool("search_knowledge", "检索知识库（用户上传的文档）与技能卡，返回带来源的片段。回答时引用 source。", {
    "type": "object", "properties": {"query": {"type": "string"}, "k": {"type": "integer", "default": 4}}, "required": ["query"]})
def search_knowledge(s: Session, query: str, k: int = 4):
    r = kb.retrieve(query, k)
    s.state.setdefault("citations", []).extend(d["source"] for d in r["docs"])
    return {"ok": True, "docs": [{**d, "text": d["text"][:500]} for d in r["docs"]],
            "cards": [{f: c.get(f) for f in ["id", "title", "task_type", "steps", "params", "checks"]} for c in r["cards"]]}

@tool("save_skill_card", "当用户教授建模方法或说“记住/学习”时，把方法保存为结构化技能卡，供以后类似任务自动检索。", {
    "type": "object", "properties": {
        "title": {"type": "string"}, "task_type": {"type": "string"}, "keywords": {"type": "string"},
        "steps": {"type": "string", "description": "步骤（可含工具调用顺序）"}, "params": {"type": "string"},
        "checks": {"type": "string", "description": "结果校验要点"}, "example": {"type": "string", "description": "示例脚本/调用"}},
    "required": ["title", "steps"]})
def save_skill_card(s: Session, **card):
    c = kb.save_card(card); return {"ok": True, "card_id": c["id"], "title": c["title"]}
