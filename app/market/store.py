"""沙盘持久化 + 哈希链审计日志（DATA_DIR/market/）。"""
from __future__ import annotations
import hashlib, json, os, threading, time
from .. import settings

_LOCK = threading.Lock()

def root():
    d = os.path.join(settings.DATA_DIR, "market"); os.makedirs(d, exist_ok=True); return d

def _p(name): return os.path.join(root(), name)

def load(name, default):
    try:
        with open(_p(name), encoding="utf-8") as f: return json.load(f)
    except Exception: return default

def save(name, obj):
    with _LOCK:
        tmp = _p(name) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f: json.dump(obj, f, ensure_ascii=False, indent=1, default=float)
        os.replace(tmp, _p(name))

def audit(action: str, actor: str = "system", obj_id: str = "", detail: dict | None = None, ok: bool = True) -> dict:
    """追加审计记录：每条含上一条哈希（篡改可检测）。"""
    with _LOCK:
        path = _p("audit.jsonl"); prev = "0" * 16
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                lines = f.read().strip().splitlines()
            if lines:
                try: prev = json.loads(lines[-1])["hash"]
                except Exception: pass
        rec = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "actor": actor, "action": action, "obj": obj_id,
               "ok": ok, "mode": "sandbox", "detail": detail or {}, "prev": prev}
        rec["hash"] = hashlib.sha256((prev + json.dumps(rec, ensure_ascii=False, sort_keys=True, default=str)).encode()).hexdigest()[:16]
        with open(path, "a", encoding="utf-8") as f: f.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
        return rec

def audit_list(limit=200, obj_id=None):
    path = _p("audit.jsonl")
    if not os.path.exists(path): return []
    with open(path, encoding="utf-8") as f: rows = [json.loads(l) for l in f if l.strip()]
    if obj_id: rows = [r for r in rows if r.get("obj") == obj_id or obj_id in json.dumps(r.get("detail", {}), ensure_ascii=False)]
    return rows[-limit:]

def audit_verify():
    rows = audit_list(10 ** 9); prev = "0" * 16
    for i, r in enumerate(rows):
        h = r.pop("hash")
        if r.get("prev") != prev: return {"ok": False, "broken_at": i}
        calc = hashlib.sha256((prev + json.dumps(r, ensure_ascii=False, sort_keys=True, default=str)).encode()).hexdigest()[:16]
        if calc != h: return {"ok": False, "broken_at": i}
        prev = h
    return {"ok": True, "n": len(rows)}
