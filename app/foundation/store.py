"""Transactional JSON documents. Immutable records can only be inserted once."""
import contextlib, hashlib, json, os, sqlite3, threading, uuid
from datetime import datetime
from zoneinfo import ZoneInfo
from .. import settings
LOCK = threading.RLock()
def now(): return datetime.now(ZoneInfo('Asia/Shanghai')).isoformat()
def digest(x):
    def canonical(v):
        if isinstance(v,dict): return {str(k):canonical(val) for k,val in v.items()}
        if isinstance(v,(tuple,list)): return [canonical(val) for val in v]
        return v
    return hashlib.sha256(json.dumps(canonical(x), sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode()).hexdigest()
def uid(): return uuid.uuid4().hex[:16]
@contextlib.contextmanager
def db():
    os.makedirs(settings.DATA_DIR, exist_ok=True)
    c = sqlite3.connect(os.path.join(settings.DATA_DIR, 'foundation.sqlite3'), timeout=30)
    c.execute('CREATE TABLE IF NOT EXISTS records (kind TEXT, id TEXT, body TEXT NOT NULL, PRIMARY KEY(kind,id))')
    try:
        with LOCK, c: yield c
    finally: c.close()
def put(kind, d, replace=False):
    with db() as c:
        if replace and kind not in ('project', 'scenario', 'task'): raise ValueError('历史版本不可覆盖')
        if replace and kind=='task':
            prev=c.execute('SELECT body FROM records WHERE kind=? AND id=?',(kind,d['id'])).fetchone()
            if prev:
                old=json.loads(prev[0])
                if old['status'] in ('completed','failed') and digest(old)!=digest(d): raise ValueError('已完成任务和结果不可覆盖')
                if old['input_hash']!=d['input_hash'] or digest(old['snapshot'])!=digest(d['snapshot']): raise ValueError('任务输入快照不可覆盖')
        c.execute(('INSERT OR REPLACE'  if replace else 'INSERT')+' INTO records VALUES (?,?,?)', (kind,d['id'],json.dumps(d,ensure_ascii=False,allow_nan=False)))
    return d
def get(kind, id):
    with db() as c: r=c.execute('SELECT body FROM records WHERE kind=? AND id=?',(kind,id)).fetchone()
    if not r: raise KeyError(f'{kind}/{id} 不存在')
    return json.loads(r[0])
def all(kind):
    with db() as c: return [json.loads(x[0]) for x in c.execute('SELECT body FROM records WHERE kind=? ORDER BY rowid',(kind,))]
