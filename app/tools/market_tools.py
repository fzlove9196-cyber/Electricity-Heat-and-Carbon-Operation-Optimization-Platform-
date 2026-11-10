"""对话入口：运营沙盘（组合台账/申报/闭环/审批/审计）。真实下单不可执行。"""
from __future__ import annotations
import json, os
from .base import tool, Session
from ..market import core as M, store

def _w(s, name, obj):
    os.makedirs(s.artifact_dir, exist_ok=True)
    with open(os.path.join(s.artifact_dir, name), "w", encoding="utf-8") as f: json.dump(obj, f, ensure_ascii=False, indent=1, default=float)
    if name not in s.artifacts: s.artifacts.append(name)
    return name

def _case(text_or_key):
    t = str(text_or_key or "")
    for k, al in {"zhongwei": ["zhongwei", "中卫"], "ulanqab": ["ulanqab", "乌兰察布"], "shaoguan": ["shaoguan", "韶关"]}.items():
        if any(a in t for a in al): return k
    return None

@tool("market_portfolio", "运营沙盘：从案例（中卫/乌兰察布/韶关）建立聚合资源台账，返回可调能力与热安全；跨省资源按规则包剔除。",
      {"type": "object", "properties": {"case": {"type": "string", "enum": list(M.CASE_FILES)}}, "required": ["case"]})
def market_portfolio(s: Session, case="zhongwei"):
    p = M.portfolio_from_case(_case(case) or case, "chat"); cap = M.capability(p)
    return {"ok": True, "portfolio": p["id"], "rule": p["rule_id"], "excluded": p["excluded"], "capability": cap["resources"],
            "artifacts": [_w(s, f"market_portfolio_{p['id']}.json", cap)]}

@tool("market_closed_loop", "运营沙盘闭环：日前组合量价申报+物理可行检查→审批→沙盘出清→日内调整→实时指令分解跟踪→DR基线考核→结算复盘（示范规则【假设】，非真实交易）。",
      {"type": "object", "properties": {"case": {"type": "string", "enum": list(M.CASE_FILES)}, "seed": {"type": "integer", "default": 7}}, "required": ["case"]})
def market_closed_loop(s: Session, case="zhongwei", seed=7):
    o = M.run_closed_loop("pf-" + (_case(case) or case), actor="chat", seed=seed)
    return {"ok": True, "portfolio": o["portfolio"], "rule": o["rule_label"], "kpi": o["kpi"],
            "day_ahead_bid": o["day_ahead"]["bid_id"], "intra_day_bid": o["intra_day"]["bid_id"],
            "disclaimer": o["disclaimer"], "artifacts": [_w(s, f"market_loop_{o['portfolio']}.json", o)]}

@tool("market_bid_action", "运营沙盘审批流：submitted/approved/rejected/sandbox_cleared/settled；external_submit 永远拒绝（真实外部下单不可执行）。",
      {"type": "object", "properties": {"bid_id": {"type": "string"}, "to": {"type": "string"}, "actor": {"type": "string"}}, "required": ["bid_id", "to"]})
def market_bid_action(s: Session, bid_id, to, actor="chat"):
    try: b = M.transition(bid_id, to, actor)
    except PermissionError as e: return {"ok": False, "refused": True, "message": str(e)}
    except M.MarketError as e: return {"ok": False, "message": str(e)}
    return {"ok": True, "status": b["status"]}

@tool("market_audit", "运营沙盘审计记录（哈希链）与完整性校验。", {"type": "object", "properties": {"limit": {"type": "integer", "default": 20}}})
def market_audit(s: Session, limit=20):
    return {"ok": True, "verify": store.audit_verify(), "records": store.audit_list(limit)}
