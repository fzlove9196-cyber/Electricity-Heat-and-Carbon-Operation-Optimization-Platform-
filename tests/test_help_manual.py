"""在线帮助 / 用户使用手册：路由、目录、上下文映射、链接完整性、无密钥、诚实声明。"""
import json, os, re
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app import help_api as H

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC = os.path.join(ROOT, "app", "static")
c = TestClient(app)
M = H.manifest()
STEPS = ["goal", "params", "model", "solver", "run", "results", "research"]


def _read(p):
    with open(p, encoding="utf-8") as f: return f.read()


def _views():
    return re.findall(r'<section id="v-([a-z]+)" class="view', _read(os.path.join(STATIC, "index.html")))


def test_help_routes():
    for u in ["/help", "/help/welcome", "/help/quickstart", "/help/params-solver"]:
        r = c.get(u); assert r.status_code == 200 and "help.js" in r.text, u
    assert c.get("/help/no-such-page").status_code == 404
    assert c.get("/help/..%2Fmain").status_code == 404
    assert c.get("/api/help/manifest").json()["pages"]
    p = c.get("/api/help/pages/quickstart").json()
    assert p["title"] and p["markdown"].startswith("#") and p["headings"]
    assert c.get("/api/help/pages/nope").status_code == 404
    assert len(c.get("/api/help/index").json()) == len(M["pages"])
    for f in ["help.js", "help.css", "help_widget.js"]:
        assert c.get("/static/" + f).status_code == 200


def test_manifest_and_all_pages_exist():
    listed = [s for sec in M["sections"] for s in sec["pages"]]
    assert len(listed) == len(set(listed)) == len(M["pages"]) >= 40
    assert set(listed) == set(M["pages"])
    files = {f[:-3] for f in os.listdir(H.PAGES) if f.endswith(".md")}
    assert files == set(listed), "页面文件与目录不一致"
    views = set(_views())
    for slug, meta in M["pages"].items():
        md = H.page_text(slug)
        assert md.startswith("# ") and meta["title"] == md.splitlines()[0][2:].strip()
        assert meta["keywords"] and meta["view"] in views
        assert meta.get("step") in (None, *STEPS)


def test_context_map_covers_all_views_and_steps():
    ctx = M["context"]; views = _views()
    assert len(views) >= 14
    for v in views: assert ctx.get(v) in M["pages"], v
    for s in STEPS: assert (ctx.get("chat:" + s) or ctx["chat"]) in M["pages"], s
    assert ctx["default"] in M["pages"]


def test_links_images_and_deeplinks_resolve():
    views = set(_views())
    for slug in M["pages"]:
        md = H.page_text(slug)
        for t in re.findall(r"\]\(/help/([a-z0-9-]+)(?:#[^)]*)?\)", md): assert t in M["pages"], (slug, t)
        for img in re.findall(r"\]\(/help/img/([^)]+)\)", md):
            assert c.get("/help/img/" + img).status_code == 200, (slug, img)
        for v, st in re.findall(r"\]\(/\?view=([a-z]+)(?:&step=([a-z]+))?\)", md):
            assert v in views, (slug, v); assert st in ("", *STEPS), (slug, st)
    assert c.get("/help/img/..%2F..%2Fmain.py").status_code == 404


SECRET = [r"sk-[A-Za-z0-9]{16,}", r"AKIA[0-9A-Z]{16}", r"gh[pousr]_[A-Za-z0-9]{20,}", r"xox[abprs]-[A-Za-z0-9-]{10,}",
          r"-----BEGIN [A-Z ]*PRIVATE KEY-----", r"(?i)(api[_-]?key|secret|token|password|passwd)\s*[:=]\s*['\"]?[A-Za-z0-9_\-]{12,}",
          r"Bearer\s+[A-Za-z0-9._\-]{16,}"]


def test_no_secrets_in_help_content():
    blobs = [H.page_text(s) for s in M["pages"]] + [json.dumps(M, ensure_ascii=False)]
    blobs += [_read(os.path.join(STATIC, f)) for f in ["help.html", "help.js", "help_widget.js"]]
    for b in blobs:
        for pat in SECRET: assert not re.search(pat, b), pat
        assert not re.search(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[a-z]{2,}", b), "手册不应包含邮箱/账号"


def test_key_honesty_statements():
    lim = H.page_text("limitations"); allp = "\n".join(H.page_text(s) for s in M["pages"])
    assert "403" in lim and "沙盘" in lim
    assert "非结算级" in lim
    assert "合成" in lim
    assert "PDF" in lim and "拓扑" in lim
    assert "15min" in lim and "拒绝" in lim
    assert "论文未全部复现" in lim
    for s in ["2026-11-07", "401", "392", "6 项失败", "3 项跳过", "并非全绿"]: assert s in lim, s
    assert "视觉验收" in lim and "B10" in lim
    for bad in ["全部复现", "通过产品化验收", "全部测试通过", "测试全绿"]:   # 只允许出现在否定语境中
        for m in re.finditer(bad, allp):
            assert re.search("[未不非没无]", allp[max(0, m.start() - 6):m.start()]), (bad, allp[m.start() - 20:m.end() + 10])
    for s in ["已实现", "部分实现", "未实现"]: assert s in H.page_text("capabilities")


def test_search_titles_headings_keywords_params():
    top = lambda q: [r["slug"] for r in H.search(q, 5)]
    assert "params-solver" in top("time_limit_s")
    assert "params-datacenter" in top("pue")[:3]
    assert "binding" in top("axis_mismatch")[:3]
    assert "faq-errors" in top("报错")
    assert "params-overview" in top("参数配置手册")
    assert H.search("zzzz-not-exist") == [] and H.search("") == []
    assert c.get("/api/help/search", params={"q": "储能 SOC"}).json()


def test_product_entries_wired():
    html = _read(os.path.join(STATIC, "index.html")); nav = _read(os.path.join(STATIC, "nav.js"))
    app_js = _read(os.path.join(STATIC, "app.js")); w = _read(os.path.join(STATIC, "help_widget.js"))
    assert 'data-jump="help"' in html and 'id="helpTopBtn"' in html and 'id="helpOpenFull"' in html
    assert "/static/help_widget.js" in html and 'id="helpTip"' in html
    assert '["help", "使用帮助"' in nav and "帮助 / 使用手册" in nav and "参数配置手册" in nav and 'v === "help"' in nav
    assert "openDeepLink" in app_js and 'QP.get("step")' in app_js
    for s in ['"F1"', '"Escape"', '"?"', "embed=1", "ctx-help", "IA.go"]: assert s in w, s
    assert c.get("/").status_code == 200 and c.get("/health").status_code == 200
