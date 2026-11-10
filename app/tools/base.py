"""可插拔工具注册表。每个仿真器 = 一个 Tool(name, description, JSON-schema 参数, 函数)。
schema 与 OpenAI function-calling / MCP tool 定义格式兼容，可直接导出为 MCP server。"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Callable, Dict

@dataclass
class Session:
    id: str
    artifact_dir: str
    state: Dict[str, Any] = field(default_factory=dict)   # scenario / results / kpis ...
    messages: list = field(default_factory=list)
    artifacts: list = field(default_factory=list)

@dataclass
class Tool:
    name: str
    description: str
    parameters: dict
    fn: Callable[..., dict]   # fn(session, **args) -> dict (JSON 可序列化)

    def openai_spec(self):
        return {"type": "function", "function": {"name": self.name, "description": self.description,
                                                  "parameters": self.parameters}}
    def mcp_spec(self):
        return {"name": self.name, "description": self.description, "inputSchema": self.parameters}

REGISTRY: Dict[str, Tool] = {}

def tool(name: str, description: str, parameters: dict | None = None):
    def deco(fn):
        REGISTRY[name] = Tool(name, description, parameters or {"type": "object", "properties": {}}, fn)
        return fn
    return deco

def call_tool(session: Session, name: str, args: dict) -> dict:
    if name not in REGISTRY:
        raise KeyError(f"未知工具: {name}; 可用: {list(REGISTRY)}")
    import time
    from .. import transparency as tr
    t0 = time.time()
    try:
        res = REGISTRY[name].fn(session, **(args or {}))
    except Exception as e:
        tr.log_entry(session, name, args, False, None, time.time() - t0, f"{type(e).__name__}: {e}"); raise
    if name == "build_scenario": tr.mark_build_sources(session, args or {})
    tr.log_entry(session, name, args, True, res, time.time() - t0)
    return res
