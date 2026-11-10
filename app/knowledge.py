"""知识层：文档上传 -> 解析 -> 分块 -> 混合检索（本地 bge-m3 稠密向量 + jieba BM25，RRF 融合，bge-reranker 重排）。
原文/技能卡存 SQLite，向量存 LanceDB（不可用时回退 SQLite）；OpenAI 兼容 embeddings 可通过配置替代本地模型。"""
from __future__ import annotations
import json, math, os, re, sqlite3, subprocess, time, uuid
from collections import Counter
import numpy as np
from . import settings

DB = os.path.join(settings.DATA_DIR, "knowledge.db")
DOC_DIR = os.path.join(settings.DATA_DIR, "docs"); os.makedirs(DOC_DIR, exist_ok=True)
ALLOWED = {".pdf", ".docx", ".md", ".txt", ".csv", ".py", ".mo", ".m", ".mos", ".json"}

def _db():
    c = sqlite3.connect(DB); c.row_factory = sqlite3.Row
    c.executescript("""create table if not exists docs(id text primary key, name text, path text, created real, n_chunks int, embed text);
    create table if not exists chunks(id integer primary key, doc_id text, idx int, text text, emb blob);
    create table if not exists cards(id text primary key, title text, task_type text, keywords text, steps text, params text,
        checks text, example text, created real, updated real, uses int default 0);
    create table if not exists vecs(key text primary key, kind text, ref text, model text, emb blob);""")
    return c

# ---------- 解析 / 分块 ----------
def extract_text(path: str) -> str:
    ext = os.path.splitext(path)[1].lower()
    if ext == ".pdf":
        try:
            return subprocess.run(["pdftotext", "-layout", path, "-"], capture_output=True, text=True, timeout=120).stdout
        except Exception:
            from pypdf import PdfReader; return "\n".join(p.extract_text() or "" for p in PdfReader(path).pages)
    if ext == ".docx":
        import docx; d = docx.Document(path)
        return "\n".join([p.text for p in d.paragraphs] + ["\t".join(c.text for c in r.cells) for t in d.tables for r in t.rows])
    return open(path, encoding="utf-8", errors="ignore").read()

def chunk(text: str, size=600, overlap=100):
    text = re.sub(r"\n{3,}", "\n\n", text).strip(); out = []; i = 0
    while i < len(text):
        out.append(text[i:i+size]); i += size - overlap
    return [c for c in out if c.strip()]

# ---------- 嵌入 / 重排（可配置） ----------
# RAG_EMBED_BACKEND: local(默认, 本地 bge-m3) | openai(OpenAI 兼容 embeddings API) | none(仅 BM25)
# RAG_RERANK: 1/0 是否启用交叉编码器重排（本地 bge-reranker）；RAG_VECTOR_STORE: lancedb(默认) | sqlite
_MODELS = {}
LOCAL_EMBED_DEFAULT = "BAAI/bge-m3"; RERANK_DEFAULT = "BAAI/bge-reranker-v2-m3"   # 低内存可改 BAAI/bge-reranker-base

def _cfg():
    return dict(backend=settings.get("RAG_EMBED_BACKEND", "local").lower(),
                local_model=settings.get("LOCAL_EMBED_MODEL", LOCAL_EMBED_DEFAULT),
                rerank=settings.get("RAG_RERANK", "1") == "1",
                rerank_model=settings.get("RERANK_MODEL", RERANK_DEFAULT),
                store=settings.get("RAG_VECTOR_STORE", "lancedb").lower())

def _embed_cfg():
    key = settings.get("EMBED_API_KEY") or settings.get("LLM_API_KEY"); model = settings.get("EMBED_MODEL")
    if not key or not model: return None
    return dict(base_url=settings.get("EMBED_BASE_URL") or settings.get("LLM_BASE_URL") or None, api_key=key, model=model)

def _hf_env():
    # huggingface.co 不可达时可设置 HF_ENDPOINT=https://hf-mirror.com（或预先用 ModelScope 下载到本地路径）
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

def _local_model(kind):
    c = _cfg(); name = c["local_model"] if kind == "embed" else c["rerank_model"]
    key = (kind, name)
    if key not in _MODELS:
        _hf_env()
        try:
            import torch; torch.set_num_threads(max(1, min(8, os.cpu_count() or 1)))
            from sentence_transformers import SentenceTransformer, CrossEncoder
            mk = (lambda **kw: SentenceTransformer(name, device="cpu", **kw)) if kind == "embed" else \
                 (lambda **kw: CrossEncoder(name, device="cpu", max_length=512, **kw))
            try: _MODELS[key] = mk(local_files_only=True)      # 已缓存则离线加载
            except Exception: _MODELS[key] = mk()               # 首次下载（可设 HF_ENDPOINT 镜像）
        except Exception as e:
            print(f"[knowledge] 本地模型 {name} 加载失败: {e}"); _MODELS[key] = None
    return _MODELS[key]

def embed_model_id():
    """当前向量空间标识（切换模型后需重建索引）。None 表示无向量（仅 BM25）。"""
    c = _cfg()
    if c["backend"] == "local": return "local:" + c["local_model"] if _local_model("embed") is not None else None
    if c["backend"] == "openai":
        e = _embed_cfg(); return ("openai:" + e["model"]) if e else None
    return None

def embed(texts, query=False):
    c = _cfg()
    if not texts: return None
    if c["backend"] == "local":
        m = _local_model("embed")
        if m is None: return None
        return np.asarray(m.encode(list(texts), normalize_embeddings=True, batch_size=8), dtype=np.float32)
    if c["backend"] == "openai":
        cfg = _embed_cfg()
        if not cfg: return None
        try:
            from openai import OpenAI
            cl = OpenAI(base_url=cfg["base_url"], api_key=cfg["api_key"])
            vs = [d.embedding for d in cl.embeddings.create(model=cfg["model"], input=list(texts)).data]
            a = np.array(vs, dtype=np.float32); return a/np.linalg.norm(a, axis=1, keepdims=True)
        except Exception as e:
            print("[knowledge] embedding 失败，回退 BM25:", e); return None
    return None

def rerank(query, texts):
    if not _cfg()["rerank"] or not texts: return None
    m = _local_model("rerank")
    if m is None: return None
    return np.asarray(m.predict([(query, t) for t in texts], batch_size=16), dtype=float)   # sigmoid 概率 0-1

def backend_info():
    c = _cfg()
    return dict(embed=embed_model_id() or "none(BM25 only)", rerank=c["rerank_model"] if c["rerank"] and _local_model("rerank") is not None else "off",
                tokenizer="jieba" if _jieba() else "char-bigram", store=_store_name())

_JB = []
# 领域词典（电力/算力/碳）：提升 jieba 对专业术语的切分质量
DOMAIN_WORDS = """算电协同 数据中心 碳强度 碳感知 碳排放 碳排放因子 排放因子 碳价 绿电 绿电占比 储能 削峰 填谷 峰谷电价 分时电价 需求响应
时延 迁移 空间迁移 时间平移 截止时间 截止期 批处理 交互负载 功率波动 爬坡 调频 辅助服务 弃光 光伏 潮流 最优潮流 暂态稳定
分布鲁棒 机会约束 鲁棒优化 随机规划 不确定性 东数西算 枢纽节点 算力 智算 训练 推理 集群 数据集 参考值 技能卡""".split()
def _jieba():
    if not _JB:
        try:
            import jieba, logging; jieba.setLogLevel(logging.WARNING); jieba.initialize()
            for w in DOMAIN_WORDS: jieba.add_word(w, freq=20000)
            _JB.append(jieba)
        except Exception: _JB.append(None)
    return _JB[0]

_STOP = set("的 了 和 与 及 或 在 是 为 对 中 等 一般 怎么 如何 什么 一下 请 帮 我 the a an of and or to in for on with is are by".split())

def tokens(s: str):
    """BM25 分词：jieba 搜索模式（中文词 + 子词）+ 英文/数字词；无 jieba 时回退汉字 unigram/bigram。"""
    s = s.lower(); jb = _jieba()
    if jb is None:
        words = re.findall(r"[a-z0-9_.]+", s); han = re.findall(r"[\u4e00-\u9fff]", s)
        return words + han + ["".join(han[i:i+2]) for i in range(len(han)-1)]
    out = []
    for w in jb.cut_for_search(s):
        w = w.strip()
        if not w or w in _STOP or not re.search(r"[a-z0-9\u4e00-\u9fff]", w): continue
        out.append(w)
    return out

def bm25(query, docs, k1=1.5, b=0.75):
    q = tokens(query); D = [tokens(d) for d in docs]
    if not D: return []
    N = len(D); avg = sum(map(len, D))/N or 1; df = Counter(t for d in D for t in set(d))
    sc = []
    for d in D:
        tf = Counter(d); s = 0
        for t in q:
            if t in tf:
                idf = math.log(1 + (N - df[t] + .5)/(df[t] + .5))
                s += idf*tf[t]*(k1+1)/(tf[t] + k1*(1-b+b*len(d)/avg))
        sc.append(s)
    return sc

# ---------- 向量存储：LanceDB（失败回退 SQLite blob） ----------
VEC_DIR = os.path.join(settings.DATA_DIR, "lancedb")

def _lance():
    if _cfg()["store"] != "lancedb": return None
    try:
        import lancedb; return lancedb.connect(VEC_DIR)
    except Exception as e:
        print("[knowledge] LanceDB 不可用，回退 SQLite:", e); return None

def _tables(db):
    try:
        r = db.list_tables(); names = getattr(r, "tables", r)
        return list(names)
    except AttributeError:
        return list(db.table_names())

def _store_name(): return "lancedb" if _lance() is not None else "sqlite"

def _tname(mid): return "vec_" + re.sub(r"[^a-z0-9]+", "_", mid.lower()).strip("_")

def _vec_upsert(items):
    """items: [(key, kind, ref, vector)]；key 形如 doc:<chunk_id> / card:<card_id>。"""
    mid = embed_model_id()
    if not items or not mid: return
    db = _lance()
    if db is not None:
        rows = [dict(key=k, kind=kind, ref=str(ref), vector=v.astype(np.float32).tolist()) for k, kind, ref, v in items]
        tn = _tname(mid)
        if tn in _tables(db):
            t = db.open_table(tn); keys = ",".join("'" + r["key"] + "'" for r in rows)
            t.delete(f"key IN ({keys})"); t.add(rows)
        else: db.create_table(tn, data=rows)
        return
    with _db() as c:
        for k, kind, ref, v in items:
            c.execute("insert or replace into vecs(key, kind, ref, model, emb) values(?,?,?,?,?)", (k, kind, str(ref), mid, v.astype(np.float32).tobytes()))

def _vec_delete(keys):
    if not keys: return
    db = _lance()
    if db is not None:
        for tn in _tables(db):
            db.open_table(tn).delete("key IN (" + ",".join("'" + k + "'" for k in keys) + ")")
    with _db() as c:
        c.executemany("delete from vecs where key=?", [(k,) for k in keys])

def _vec_search(qv, kind, n=20):
    """返回 {key: cosine}。"""
    mid = embed_model_id()
    if qv is None or not mid: return {}
    db = _lance()
    if db is not None:
        tn = _tname(mid)
        if tn not in _tables(db): return {}
        res = db.open_table(tn).search(qv.tolist()).metric("cosine").where(f"kind = '{kind}'", prefilter=True).limit(n).to_list()
        return {r["key"]: 1 - float(r["_distance"]) for r in res}
    with _db() as c:
        rows = c.execute("select key, emb from vecs where kind=? and model=?", (kind, mid)).fetchall()
    sims = {r["key"]: float(np.frombuffer(r["emb"], np.float32) @ qv) for r in rows}
    return dict(sorted(sims.items(), key=lambda x: -x[1])[:n])

def _card_text(cd): return " ".join(str(cd.get(f) or "") for f in CARD_FIELDS)

def reindex_all() -> dict:
    """用当前嵌入后端重建全部文档块与技能卡的向量索引（不改动原文与卡片）。"""
    t0 = time.time()
    with _db() as c:
        chunks = [dict(r) for r in c.execute("select id, text from chunks")]
    cards = list_cards() + [BUILTIN]
    mid = embed_model_id()
    if not mid: return dict(ok=False, error="未配置可用的嵌入后端（RAG_EMBED_BACKEND）", n_chunks=len(chunks))
    db = _lance()
    if db is not None and _tname(mid) in _tables(db): db.drop_table(_tname(mid))
    items = []
    for i in range(0, len(chunks), 32):
        part = chunks[i:i+32]; vs = embed([x["text"] for x in part])
        items += [(f"doc:{x['id']}", "doc", x["id"], v) for x, v in zip(part, vs)]
    vs = embed([_card_text(cd) for cd in cards])
    items += [(f"card:{cd['id']}", "card", cd["id"], v) for cd, v in zip(cards, vs)]
    _vec_upsert(items)
    with _db() as c: c.execute("update docs set embed=?", (mid,))
    return dict(ok=True, model=mid, store=_store_name(), n_chunks=len(chunks), n_cards=len(cards), seconds=round(time.time()-t0, 1))

def _rrf(*rankings, k=60):
    sc = {}
    for rk in rankings:
        for i, key in enumerate(rk): sc[key] = sc.get(key, 0) + 1/(k + i + 1)
    return sorted(sc, key=lambda x: -sc[x])

# ---------- 文档 ----------
def add_document(path: str, name: str | None = None) -> dict:
    name = name or os.path.basename(path)
    if os.path.splitext(name)[1].lower() not in ALLOWED: raise ValueError(f"不支持的文件类型: {name}")
    text = extract_text(path); chs = chunk(text)
    if not chs: raise ValueError("文档无可提取文本")
    embs = embed(chs); did = uuid.uuid4().hex[:10]; mid = embed_model_id() if embs is not None else None
    ids = []
    with _db() as c:
        c.execute("insert into docs values(?,?,?,?,?,?)", (did, name, path, time.time(), len(chs), mid or "bm25"))
        for i, t in enumerate(chs):
            ids.append(c.execute("insert into chunks(doc_id,idx,text,emb) values(?,?,?,?)", (did, i, t, None)).lastrowid)
    if embs is not None: _vec_upsert([(f"doc:{cid}", "doc", cid, v) for cid, v in zip(ids, embs)])
    return dict(id=did, name=name, n_chunks=len(chs), index=mid or "bm25")

def list_documents():
    with _db() as c: return [dict(r) for r in c.execute("select id,name,created,n_chunks,embed from docs order by created desc")]

def delete_document(did):
    with _db() as c:
        r = c.execute("select path from docs where id=?", (did,)).fetchone()
        keys = [f"doc:{x['id']}" for x in c.execute("select id from chunks where doc_id=?", (did,))]
        c.execute("delete from chunks where doc_id=?", (did,)); c.execute("delete from docs where id=?", (did,))
    _vec_delete(keys)
    if r and r["path"].startswith(DOC_DIR) and os.path.exists(r["path"]): os.remove(r["path"])
    return bool(r)

def search_docs(query: str, k=4, min_score=3.0, n_cand=20, n_rerank=8, min_rerank=0.05, debug=False):
    """混合检索：BM25(jieba) top-N ∪ 稠密向量 top-N → RRF 融合 → 交叉编码器重排 → top-k。
    无向量/重排模型时退化为 BM25（绝对阈值 min_score 过滤弱相关）。"""
    with _db() as c:
        rows = [dict(r) for r in c.execute("select chunks.id, doc_id, idx, text, docs.name from chunks join docs on docs.id=doc_id")]
    if not rows: return []
    byid = {r["id"]: r for r in rows}
    bm = np.array(bm25(query, [r["text"] for r in rows]), float)
    bm_rank = [rows[i]["id"] for i in np.argsort(-bm)[:n_cand] if bm[i] >= min_score]
    qv = embed([query], query=True)
    dense = _vec_search(qv[0] if qv is not None else None, "doc", n_cand)
    dense_rank = [int(key.split(":")[1]) for key in dense if int(key.split(":")[1]) in byid]
    if not dense_rank:   # 纯 BM25 回退（与旧版一致）
        sc = bm.copy(); sc[sc < min_score] = 0
        if sc.max() > 0: sc = sc/sc.max()
        return [dict(source=f"{rows[i]['name']}#{rows[i]['idx']}", doc_id=rows[i]["doc_id"], score=round(float(sc[i]), 3), text=rows[i]["text"])
                for i in np.argsort(-sc)[:k] if sc[i] > 0]
    fused = _rrf(bm_rank, dense_rank)[:max(n_rerank, 2 * k)]
    rr = rerank(query, [byid[i]["text"] for i in fused])
    if rr is not None:
        order = [fused[i] for i in np.argsort(-rr)]; scores = {fused[i]: float(rr[i]) for i in range(len(fused))}
        order = [i for i in order if scores[i] >= min_rerank]
    else:
        order = [i for i in fused if dense.get(f"doc:{i}", 0) >= 0.45 or i in bm_rank]
        scores = {i: dense.get(f"doc:{i}", 0) for i in fused}
    out = []
    for i in order[:k]:
        r = byid[i]; d = dict(source=f"{r['name']}#{r['idx']}", doc_id=r["doc_id"], score=round(scores[i], 3), text=r["text"])
        if debug: d.update(dense=round(dense.get(f"doc:{i}", 0), 3), bm25=round(float(bm[rows.index(r)]), 3))
        out.append(d)
    return out

# ---------- 技能卡 ----------
CARD_FIELDS = ["title", "task_type", "keywords", "steps", "params", "checks", "example"]
BUILTIN = dict(id="builtin_sdco", title="算电协同标准流程", task_type="算电协同调度", keywords="数据中心 储能 峰谷 调度 优化",
               steps="build_scenario -> run_dispatch(optimized) -> run_dispatch(baseline) -> run_ac_check -> compute_kpis -> compare_baseline -> make_plots -> write_report",
               params="n_dc, storage_mwh, price_kind", checks="LP optimal; AC 收敛; 电压 0.94-1.10; 负载率<100%", example="")

def _ser(v): return v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)

def save_card(card: dict) -> dict:
    cid = card.get("id")
    if not cid and card.get("title"):   # 同名卡片视为更新
        with _db() as c:
            r = c.execute("select id from cards where title=?", (card["title"],)).fetchone()
            cid = r["id"] if r else None
    cid = cid or uuid.uuid4().hex[:10]; now = time.time()
    vals = {f: _ser(card.get(f, "")) for f in CARD_FIELDS}
    with _db() as c:
        if c.execute("select 1 from cards where id=?", (cid,)).fetchone():
            c.execute(f"update cards set {','.join(f+'=?' for f in CARD_FIELDS)}, updated=? where id=?", (*vals.values(), now, cid))
        else:
            c.execute("insert into cards(id,title,task_type,keywords,steps,params,checks,example,created,updated) values(?,?,?,?,?,?,?,?,?,?)",
                      (cid, *vals.values(), now, now))
    cd = get_card(cid)
    try:
        v = embed([_card_text(cd)])
        if v is not None: _vec_upsert([(f"card:{cid}", "card", cid, v[0])])
    except Exception as e: print("[knowledge] 技能卡向量化失败:", e)
    return cd

def get_card(cid):
    with _db() as c: r = c.execute("select * from cards where id=?", (cid,)).fetchone()
    return dict(r) if r else None

def list_cards():
    with _db() as c: return [dict(r) for r in c.execute("select * from cards order by updated desc")]

def delete_card(cid):
    with _db() as c: ok = c.execute("delete from cards where id=?", (cid,)).rowcount > 0
    _vec_delete([f"card:{cid}"]); return ok

def search_cards(query: str, k=3, min_dense=0.55, min_rerank=0.3):
    """技能卡混合检索。score 字段保持 BM25 分值（Mock 技能复用阈值依赖它）；排序用重排分（若可用）。"""
    cards = list_cards() + [BUILTIN]
    texts = [_card_text(cd) for cd in cards]
    sc = bm25(query, texts)
    qv = embed([query], query=True)
    dense = _vec_search(qv[0] if qv is not None else None, "card", 10)
    cand = [i for i in range(len(cards)) if sc[i] > 0 or dense.get(f"card:{cards[i]['id']}", 0) >= min_dense]
    rr = rerank(query, [texts[i] for i in cand]) if cand else None
    if rr is not None:
        keep = [(i, float(r)) for i, r in zip(cand, rr) if r >= min_rerank or sc[i] >= 2]
        keep.sort(key=lambda x: -x[1])
        out = [cards[i] | {"score": round(sc[i], 3), "rerank": round(r, 3)} for i, r in keep[:k]]
    else:
        out = [cards[i] | {"score": round(sc[i], 3)} for i in np.argsort(-np.array(sc))[:k] if sc[i] > 0]
    if out:
        with _db() as c:
            for cd in out: c.execute("update cards set uses=uses+1 where id=?", (cd["id"],))
    return out

def retrieve(query: str, k: int = 3) -> dict:
    """Agent 调用入口：返回相关技能卡 + 文档片段（带来源）。"""
    return dict(cards=search_cards(query, k), docs=search_docs(query, k+1))
