"""服务端设置（LLM 配置），保存在 data/settings.json；环境变量为默认值。"""
import json, os
DATA_DIR = os.path.abspath(os.getenv("DATA_DIR", os.path.join(os.path.dirname(__file__), "..", "data")))
os.makedirs(DATA_DIR, exist_ok=True)
PATH = os.path.join(DATA_DIR, "settings.json")
KEYS = ["LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL", "LLM_MOCK", "EMBED_MODEL", "EMBED_BASE_URL", "EMBED_API_KEY",
        "RAG_EMBED_BACKEND", "LOCAL_EMBED_MODEL", "RAG_RERANK", "RERANK_MODEL", "RAG_VECTOR_STORE",
        "CARBON_SOURCE", "CARBON_AWARE_URL", "CARBON_LOCATION", "CARBON_FILE", "CARBON_URL", "WATTTIME_USER", "WATTTIME_PASSWORD"]

def get(k, default=""):
    try: d = json.load(open(PATH))
    except Exception: d = {}
    v = d.get(k)
    return v if v not in (None, "") else os.getenv(k, default)

def all_masked():
    out = {k: get(k) for k in KEYS}
    for k in out:
        if ("KEY" in k or "PASSWORD" in k) and out[k]: out[k] = out[k][:3] + "****" + out[k][-4:] if len(out[k]) > 8 else "****"
    return out

def update(d: dict):
    try: cur = json.load(open(PATH))
    except Exception: cur = {}
    for k, v in d.items():
        if k in KEYS and v is not None and "****" not in str(v): cur[k] = v   # 掩码值不覆盖
    json.dump(cur, open(PATH, "w"), indent=2); os.chmod(PATH, 0o600)
