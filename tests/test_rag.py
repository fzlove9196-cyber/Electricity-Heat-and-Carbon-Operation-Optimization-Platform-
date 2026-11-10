"""中文 RAG：本地 bge-m3 + bge-reranker + jieba BM25 + LanceDB 混合检索（模型未缓存时跳过）。"""
import glob, os, shutil, tempfile
import pytest
from app import knowledge as kb

SEED = sorted(glob.glob(os.path.join(os.path.dirname(__file__), "..", "knowledge_seed", "*.md")))

@pytest.fixture
def local_rag(monkeypatch):
    monkeypatch.setenv("RAG_EMBED_BACKEND", "local"); monkeypatch.setenv("RAG_RERANK", "1")
    if kb._local_model("embed") is None: pytest.skip("本地 bge-m3 不可用")
    ids = []
    for p in SEED:
        tmp = os.path.join(tempfile.mkdtemp(), os.path.basename(p)); shutil.copy(p, tmp)
        ids.append(kb.add_document(tmp)["id"])
    yield
    for i in ids: kb.delete_document(i)

def test_jieba_tokens():
    t = kb.tokens("碳感知调度 碳强度 Alibaba GPU trace 数据集")
    assert "碳强度" in t and "alibaba" in t and "数据集" in t and "的" not in t

@pytest.mark.parametrize("q,exp", [("Alibaba GPU trace 数据集", "cluster-trace-gpu-v2020"), ("PUE 参考值", "PUE"),
                                   ("碳感知调度 碳强度", "碳"), ("AI训练 功率波动", "功率")])
def test_hybrid_hits(local_rag, q, exp):
    info = kb.backend_info(); assert info["embed"].startswith("local:") and info["tokenizer"] == "jieba"
    docs = kb.search_docs(q, k=3, debug=True); print("\n", q, [(d["source"], d["score"], d["dense"], d["bm25"]) for d in docs])
    assert docs and any(exp in d["text"] for d in docs[:3])

def test_reindex_and_cards(local_rag):
    c = kb.save_card(dict(title="成本-碳排放双目标权衡（测试卡）", task_type="碳感知调度", keywords="碳排放 碳价 成本 权衡 Pareto",
                          steps="build_scenario -> run_pareto_sweep -> write_report", checks="排放随碳权重单调下降"))
    r = kb.reindex_all(); print("\nREINDEX", r)
    assert r["ok"] and r["n_chunks"] >= 20 and r["store"] in ("lancedb", "sqlite")
    cards = kb.search_cards("成本和碳排放怎么权衡")
    assert cards and cards[0]["id"] == c["id"]
    assert kb.delete_card(c["id"])

def test_openai_backend_optional(monkeypatch):
    monkeypatch.setenv("RAG_EMBED_BACKEND", "openai"); monkeypatch.setenv("EMBED_MODEL", ""); monkeypatch.setenv("LLM_API_KEY", "")
    assert kb.embed_model_id() is None and kb.embed(["x"]) is None     # 未配置时安全回退 BM25
