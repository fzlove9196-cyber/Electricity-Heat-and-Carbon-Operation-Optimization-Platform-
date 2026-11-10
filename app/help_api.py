"""产品内在线帮助（用户使用手册）。

纯本地静态内容：Markdown 页面位于 app/help/pages/，目录/关键词/上下文映射位于 app/help/manifest.json。
不调用 LLM、不访问外网、不读写用户数据（data/、知识库、会话均不触碰），Mock 模式可离线阅读。
"""
from __future__ import annotations
import json, os, re
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

ROOT = os.path.dirname(os.path.abspath(__file__))
HELP = os.path.join(ROOT, "help")
PAGES = os.path.join(HELP, "pages")
IMG = os.path.join(HELP, "img")
SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
IMG_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,80}\.(png|jpg|jpeg|svg)$")
router = APIRouter()


def manifest() -> dict:
    with open(os.path.join(HELP, "manifest.json"), encoding="utf-8") as f:
        return json.load(f)


def page_text(slug: str) -> str:
    if not SLUG.match(slug or ""): raise HTTPException(404, "帮助页面不存在")
    p = os.path.join(PAGES, slug + ".md")
    if not os.path.isfile(p): raise HTTPException(404, "帮助页面不存在")
    with open(p, encoding="utf-8") as f: return f.read()


def headings(md: str) -> list[dict]:
    out = []
    for line in md.splitlines():
        m = re.match(r"^(#{2,3})\s+(.+?)\s*$", line)
        if m: out.append(dict(level=len(m.group(1)), text=m.group(2)))
    return out


def params_of(md: str) -> list[str]:
    """表格首列中的反引号字段名，用于“参数名”搜索。"""
    names = []
    for line in md.splitlines():
        if line.startswith("|"):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if cells: names += re.findall(r"`([A-Za-z_][A-Za-z0-9_.*\[\]]*)`", cells[0])
    return list(dict.fromkeys(names))


def index() -> list[dict]:
    m = manifest(); out = []
    for slug, meta in m["pages"].items():
        md = page_text(slug)
        out.append(dict(slug=slug, title=meta["title"], section=meta.get("section"), keywords=meta.get("keywords", []),
                        headings=headings(md), params=params_of(md), text=re.sub(r"-{3,}|[#>*`|!\[\]()]+", " ", md)))
    return out


def search(q: str, limit: int = 20) -> list[dict]:
    q = (q or "").strip().lower()
    if not q: return []
    terms = [t for t in re.split(r"\s+", q) if t]
    res = []
    for it in index():
        score = 0; hits = []
        for t in terms:
            s = 0
            if t in it["title"].lower(): s += 30
            if any(t in k.lower() for k in it["keywords"]): s += 15
            if any(t in p.lower() for p in it["params"]): s += 12; hits += [p for p in it["params"] if t in p.lower()][:3]
            hh = [h["text"] for h in it["headings"] if t in h["text"].lower()]
            if hh: s += 8; hits += hh[:2]
            c = it["text"].lower().count(t)
            if c: s += min(c, 10)
            if not s: score = 0; break   # 多词按“与”匹配
            score += s
        if score:
            txt = it["text"]; i = txt.lower().find(terms[0])
            snip = re.sub(r"\s+", " ", txt[max(0, i - 40): i + 80]).strip() if i >= 0 else ""
            res.append(dict(slug=it["slug"], title=it["title"], score=score, hits=list(dict.fromkeys(hits))[:4], snippet=snip))
    return sorted(res, key=lambda r: -r["score"])[:limit]


def _shell():
    r = FileResponse(os.path.join(ROOT, "static", "help.html"))
    r.headers["Cache-Control"] = "no-cache"
    return r


@router.get("/help")
def help_home(): return _shell()


@router.get("/help/img/{name}")
def help_img(name: str):
    if not IMG_NAME.match(name or ""): raise HTTPException(404, "图片不存在")
    p = os.path.join(IMG, name)
    if not os.path.isfile(p): raise HTTPException(404, "图片不存在")
    return FileResponse(p)


@router.get("/help/{slug}")
def help_page(slug: str):
    page_text(slug)   # 不存在的 slug 返回 404，而不是空白页
    return _shell()


@router.get("/api/help/manifest")
def api_manifest(): return manifest()


@router.get("/api/help/pages/{slug}")
def api_page(slug: str):
    m = manifest()
    if slug not in m["pages"]: raise HTTPException(404, "帮助页面不存在")
    md = page_text(slug)
    return dict(slug=slug, **m["pages"][slug], markdown=md, headings=headings(md), params=params_of(md))


@router.get("/api/help/index")
def api_index(): return index()


@router.get("/api/help/search")
def api_search(q: str = "", limit: int = 20): return search(q, max(1, min(int(limit), 50)))
