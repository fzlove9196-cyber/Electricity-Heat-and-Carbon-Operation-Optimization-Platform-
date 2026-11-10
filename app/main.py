"""FastAPI 入口：API + 静态前端（单一可部署服务）。"""
from __future__ import annotations
import json, os, shutil, subprocess, time, uuid, importlib.util
from dotenv import load_dotenv
load_dotenv()
from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.responses import FileResponse, StreamingResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from .tools import Session, REGISTRY
from .agent import run_turn_events
from . import knowledge as kb, settings
from .scenario import Scenario, build_default

ROOT = os.path.dirname(os.path.abspath(__file__))
ART_ROOT = os.path.abspath(os.getenv("ARTIFACT_DIR", os.path.join(ROOT, "..", "artifacts")))
SESS_DIR = os.path.join(settings.DATA_DIR, "sessions"); os.makedirs(SESS_DIR, exist_ok=True)
app = FastAPI(title="算电协同仿真智能体")
SESSIONS: dict[str, Session] = {}

def _sess_path(sid): return os.path.join(SESS_DIR, f"{sid}.json")

def get_session(sid: str | None) -> Session:
    sid = sid or uuid.uuid4().hex[:12]
    if not sid.isalnum(): raise HTTPException(400, "bad session id")
    if sid in SESSIONS: return SESSIONS[sid]
    s = Session(sid, os.path.join(ART_ROOT, sid))
    if os.path.exists(_sess_path(sid)):   # 从磁盘恢复（仿真中间状态不持久化）
        d = json.load(open(_sess_path(sid))); s.messages = d["messages"]; s.artifacts = d["artifacts"]
        s.state["title"] = d.get("title"); s.state["events"] = d.get("events", [])
        sp = os.path.join(s.artifact_dir, "scenario.json")   # 恢复最近一次场景（含拓扑编辑），结果需重新求解
        if os.path.isfile(sp):
            try: s.state["scenario"] = Scenario.model_validate_json(open(sp, encoding="utf-8").read()); s.state["results"] = {}
            except Exception: pass
        s.state["model_edited"] = bool(d.get("model_edited")); s.state["edit_log"] = d.get("edit_log", [])
        for k, v in (d.get("wf") or {}).items():
            if v is not None: s.state[k] = v
        if d.get("study"): s.state["study"] = d["study"]
    SESSIONS[sid] = s; return s

def save_session(s: Session):
    # All legacy edit paths invalidate derived results on model changes.
    from .foundation.store import digest
    sc = s.state.get("scenario")
    if sc is not None:
        h = digest(sc.model_dump())
        old = s.state.get("foundation_model_hash")
        if old and old != h and s.state.get("foundation_result_model_hash") != h:
            s.state["results"] = {}
            for key in ("kpis", "compare", "model_graph", "attribution"):
                s.state.pop(key, None)
            s.state["foundation_results_stale"] = True
        s.state["foundation_model_hash"] = h
    title = s.state.get("title") or next((m["content"][:30] for m in s.messages if m["role"] == "user"), "新会话")
    s.state["title"] = title
    json.dump(dict(id=s.id, title=title, updated=time.time(), messages=s.messages, artifacts=s.artifacts,
                   events=s.state.get("events", []), model_edited=bool(s.state.get("model_edited")), edit_log=s.state.get("edit_log", [])[-50:],
                   wf={k: s.state.get(k) for k in ("runlog", "param_src", "origin", "params_confirmed", "solver_cfg", "auto_run", "confirm_required", "config_spec", "levers", "last_sweep", "foundation_context", "foundation_task_id", "foundation_model_hash", "foundation_results_stale")},
                   study=_study_persist(s.state.get("study"))),
              open(_sess_path(s.id), "w"), ensure_ascii=False)

def _study_persist(st):
    if not st: return None
    d = {k: v for k, v in st.items()}
    d["runs"] = {k: {a: b for a, b in r.items() if not a.startswith("_")} for k, r in st.get("runs", {}).items()}
    return json.loads(json.dumps(d, default=str))

def _events(s, body):
    from .research import orchestrator as RO
    if RO.route(s, body.message, force=bool(body.research)):
        def g():
            for e in RO.chat_events(s, body.message, force=bool(body.research)): yield e
            yield {"type": "done", "citations": [], "artifacts": list(s.artifacts), "new_messages": []}
        return g()
    return run_turn_events(s, body.message)

def _arts(s): return [{"name": a, "url": f"/artifacts/{s.id}/{a}"} for a in s.artifacts]

class ChatIn(BaseModel):
    message: str
    session_id: str | None = None
    scenario: dict | None = None   # 前端参数面板：预置场景
    auto_run: bool | None = None   # 界面传入：False=运行前暂停等待“确认参数”；None（API 默认）=不暂停
    research: bool | None = None   # 研究模式：问题形式化→澄清→计划→执行/诊断/修订→结论（研究编排器）

def _prep(body: ChatIn):
    s = get_session(body.session_id)
    if body.auto_run is not None: s.state["confirm_required"] = True; s.state["auto_run"] = bool(body.auto_run)
    if body.scenario:
        from .tools import call_tool
        s.state["_actor"] = "用户（场景面板）"; s.state["_actor_build"] = "用户"
        call_tool(s, "build_scenario", {"scenario": body.scenario}); s.state["preset"] = True; s.state.pop("_actor_build", None)
    return s

def _strip(ev):
    return {k: v for k, v in ev.items() if k != "new_messages"}

@app.post("/api/chat")
@app.post("/chat")
def chat(body: ChatIn):
    s = _prep(body); evs = []
    for ev in _events(s, body): evs.append(ev)
    done = evs[-1]; s.state.setdefault("events", []).append([_strip(e) for e in evs]); save_session(s)
    return {"session_id": s.id, "messages": done["new_messages"], "events": [_strip(e) for e in evs],
            "reply": next((e["content"] for e in reversed(evs) if e["type"] == "message"), ""),
            "citations": done["citations"], "artifacts": _arts(s)}

@app.post("/api/chat/stream")
def chat_stream(body: ChatIn):
    s = _prep(body)
    def gen():
        evs = []
        yield f"data: {json.dumps({'type': 'session', 'session_id': s.id})}\n\n"
        for ev in _events(s, body):
            e = _strip(ev); evs.append(e)
            if e["type"] == "done": e["artifacts"] = _arts(s)
            yield f"data: {json.dumps(e, ensure_ascii=False, default=str)}\n\n"
        s.state.setdefault("events", []).append(evs); save_session(s)
    return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

# ---------------- 研究模式 ----------------
@app.get("/api/sessions/{sid}/study")
def study_get(sid: str):
    from .research import orchestrator as RO
    s = get_session(sid); return {"ok": True, "study": RO.public(RO.get(s))}

class PlanEditIn(BaseModel):
    steps: list = []
    auto_revise: bool | None = None

@app.patch("/api/sessions/{sid}/study/plan")
def study_plan(sid: str, b: PlanEditIn):
    from .research import orchestrator as RO
    s = get_session(sid); st = RO.get(s)
    if not st: raise HTTPException(404, "当前会话没有研究")
    if b.auto_revise is not None: st["auto_revise"] = b.auto_revise
    out = RO.edit_plan(s, {"steps": b.steps}); save_session(s); return {"ok": True, "study": out}

@app.get("/api/sessions/{sid}/study/run/{rid}")
def study_run(sid: str, rid: str):
    from .research import orchestrator as RO, experiments as EX
    s = get_session(sid); st = RO.get(s)
    if not st or rid not in st.get("runs", {}): raise HTTPException(404, f"没有运行 {rid}")
    return {"ok": True, "run": EX.public_run(st["runs"][rid])}

@app.get("/api/sessions")
def sessions():
    out = []
    for f in os.listdir(SESS_DIR):
        try: d = json.load(open(os.path.join(SESS_DIR, f))); out.append(dict(id=d["id"], title=d["title"], updated=d["updated"]))
        except Exception: pass
    return sorted(out, key=lambda x: -x["updated"])

@app.get("/api/sessions/{sid}")
def session_get(sid: str):
    if not os.path.exists(_sess_path(sid)) and sid not in SESSIONS: raise HTTPException(404)
    s = get_session(sid)
    return dict(id=s.id, title=s.state.get("title"), artifacts=_arts(s), events=s.state.get("events", []),
                messages=[m for m in s.messages if m["role"] in ("user", "assistant") and m.get("content")])

@app.delete("/api/sessions/{sid}")
def session_del(sid: str):
    SESSIONS.pop(sid, None)
    if os.path.exists(_sess_path(sid)): os.remove(_sess_path(sid))
    if sid.isalnum(): shutil.rmtree(os.path.join(ART_ROOT, sid), ignore_errors=True)
    return {"ok": True}

@app.get("/api/sessions/{sid}/model")
def session_model(sid: str):
    """当前会话模型的“拓扑 + 能流”图数据（随 build_scenario / run_dispatch 实时更新）。"""
    s = get_session(sid)
    if "scenario" in s.state:
        from .tools.model_viz import refresh
        g = s.state.get("model_graph") or refresh(s)
        return {"ok": True, "graph": g, "html": f"/artifacts/{sid}/model_topology.html", "png": f"/artifacts/{sid}/model_topology.png"}
    p = os.path.join(ART_ROOT, sid, "model_topology.json")   # 服务重启后：读取最近一次落盘结果
    if os.path.isfile(p):
        return {"ok": True, "graph": json.load(open(p, encoding="utf-8")), "html": f"/artifacts/{sid}/model_topology.html", "png": f"/artifacts/{sid}/model_topology.png"}
    return {"ok": False, "error": "该会话尚未建模（请先让智能体构建场景）"}

@app.post("/api/model/preview")
def model_preview(scenario: dict | None = None):
    """场景参数面板实时预览：直接由场景 JSON 生成模型图（未求解，仅容量）。"""
    from .tools.model_viz import build_model_graph
    from .tools import sdco_engine as eng
    try:
        sc = Scenario.model_validate(scenario) if scenario else build_default(3, 50)
        errs = eng.validate(sc)
        return {"ok": True, "graph": build_model_graph(sc), "warnings": errs}
    except Exception as e:
        raise HTTPException(400, f"{type(e).__name__}: {e}")

# ---------- 模型拓扑编辑（与对话共享会话场景） ----------
from .tools import model_edit as me

def _edit_state(s, extra=None):
    from .tools.model_viz import refresh
    sc = s.state["scenario"]; g = refresh(s)
    out = {"ok": True, "session_id": s.id, "graph": g, "validation": me.check_model(sc), "network_case": sc.network_case,
           "can_undo": bool(s.state.get("edit_undo")), "can_redo": bool(s.state.get("edit_redo")),
           "foundation": __import__("app.foundation.api", fromlist=["session_context"]).session_context(s), "edit_log": s.state.get("edit_log", [])[-20:], "solved": g.get("solved", False),
           "html": f"/artifacts/{s.id}/model_topology.html", "png": f"/artifacts/{s.id}/model_topology.png"}
    if extra: out.update(extra)
    return out

def _need_sc(s):
    if "scenario" not in s.state: raise HTTPException(400, "该会话尚未建模：请先在对话中构建场景，或在本页选择预设/默认场景开始编辑")
    return s.state["scenario"]

def _commit(s, new_sc, desc):
    if s.state.get("foundation_context"):
        from .foundation.service import checked
        try: checked(new_sc.model_dump())
        except ValueError as e: raise HTTPException(400, f"项目模型修改未通过校验：{e}")
    from .tools.sim_tools import _art
    old = s.state["scenario"]
    s.state.setdefault("edit_undo", []).append(old.model_dump_json()); s.state["edit_undo"] = s.state["edit_undo"][-50:]
    s.state["edit_redo"] = []
    if "edit_base" not in s.state:   # 首次编辑：记录“编辑前”模型（及已求解指标）供对比
        s.state["edit_base"] = old.model_dump_json()
        r = s.state.get("results", {}).get("optimized")
        s.state["edit_base_metrics"] = me.metrics(old, r) if r else None
    s.state["scenario"] = new_sc; s.state["results"] = {}; s.state.pop("model_graph", None)
    s.state["model_edited"] = True
    s.state.setdefault("edit_log", []).append(dict(t=time.strftime("%H:%M:%S"), desc=desc)); s.state["edit_unsent"] = True
    with open(_art(s, "scenario.json"), "w") as f: f.write(new_sc.model_dump_json(indent=2))
    save_session(s)

class InitIn(BaseModel):
    preset: str | None = None; scenario: dict | None = None; default: bool = False

@app.post("/api/sessions/{sid}/model/init")
def model_init(sid: str, b: InitIn):
    """在拓扑页直接开始：加载预设/场景 JSON/默认场景到会话（等同 build_scenario）。sid='new' 时新建会话。"""
    from .tools import call_tool
    s = get_session(None if sid == "new" else sid)
    s.state["_actor"] = "用户（界面）"; s.state["_actor_build"] = "用户"
    try:
        if b.scenario: call_tool(s, "build_scenario", {"scenario": b.scenario})
        elif b.preset: call_tool(s, "build_scenario", {"preset": b.preset})
        else: call_tool(s, "build_scenario", {"n_dc": 3, "storage_mwh": 50})
    except Exception as e: raise HTTPException(400, f"{type(e).__name__}: {e}")
    finally: s.state.pop("_actor_build", None)
    for k in ("edit_undo", "edit_redo", "edit_base", "edit_base_metrics"): s.state.pop(k, None)
    s.state["model_edited"] = False; s.state.setdefault("edit_log", []).append(dict(t=time.strftime("%H:%M:%S"), desc=f"载入模型 {s.state['scenario'].name}"))
    if not s.state.get("title"): s.state["title"] = f"拓扑编辑：{s.state['scenario'].name}"
    save_session(s); return _edit_state(s)

@app.get("/api/sessions/{sid}/model/edit")
def model_edit_get(sid: str):
    s = get_session(sid); _need_sc(s); return _edit_state(s, {"scenario": s.state["scenario"].model_dump()})

@app.post("/api/sessions/{sid}/model/convert")
def model_convert(sid: str):
    """IEEE14 等标准算例 -> 等值自定义网络（便于逐元件编辑；DC-OPF 结果一致），可撤销。"""
    s = get_session(sid); sc = _need_sc(s)
    if sc.network_case == "custom": return _edit_state(s, {"message": "已是自定义网络"})
    _commit(s, me.to_custom(sc), "IEEE14 转换为可编辑的自定义等值网络"); return _edit_state(s, {"message": "已转换为可编辑自定义网络"})

class ElemIn(BaseModel):
    type: str; params: dict = {}; x: float | None = None; y: float | None = None

def _freeze_layout(s, sc):
    """首次拓扑编辑前，把当前自动布局写入 sc.layout，后续增删元件不再整体重排。"""
    g = s.state.get("model_graph")
    if not g or any(k.startswith("b") for k in sc.layout): return
    for b in g["buses"]: sc.layout[f"b{b['i']}"] = [b["x"], b["y"]]

def _do(s, op):
    sc = _need_sc(s)
    if op.get("type") in ("bus", "line", "trafo") or (op.get("action") == "delete"): _freeze_layout(s, sc)
    try: new, desc = me.apply_op(sc, op)
    except HTTPException: raise
    except Exception as e: raise HTTPException(400, f"{e}")
    _commit(s, new, desc); return _edit_state(s, {"message": desc})

@app.post("/api/sessions/{sid}/model/element")
def model_elem_add(sid: str, b: ElemIn):
    op = {"action": "add", "type": b.type, "params": b.params}
    s = get_session(sid)
    if b.x is not None: op.update(x=b.x, y=b.y)
    elif b.type == "bus" and s.state.get("model_graph"):   # 新母线默认放在图右侧空白处（避免与已有母线重叠）
        bs = s.state["model_graph"]["buses"]; pts = [(x["x"], x["y"]) for x in bs] + [(d.get("x"), d.get("y")) for d in s.state["model_graph"]["devices"] if d.get("x") is not None]
        cands = [(cx, cy) for cx in (0.5, 0.3, 0.7, 0.1, 0.9, 1.1) for cy in (0.05, 0.25, 0.45, 0.65, 0.85, 1.05)]
        x, y = max(cands, key=lambda c: min([((c[0]-px)**2 + (c[1]-py)**2) for px, py in pts] or [1]))   # 离已有元件最远的空位
        op.update(x=x, y=y)
    return _do(s, op)

@app.get("/api/sessions/{sid}/model/element/{typ}/{key}")
def model_elem_get(sid: str, typ: str, key: str):
    s = get_session(sid)
    try: return {"ok": True, "type": me._norm_type(typ), "key": key, "params": me.get_element(_need_sc(s), typ, key)}
    except HTTPException: raise
    except Exception as e: raise HTTPException(404, str(e))

@app.patch("/api/sessions/{sid}/model/element/{typ}/{key}")
def model_elem_patch(sid: str, typ: str, key: str, params: dict):
    return _do(get_session(sid), {"action": "update", "type": typ, "key": key, "params": params})

@app.delete("/api/sessions/{sid}/model/element/{typ}/{key}")
def model_elem_del(sid: str, typ: str, key: str, cascade: int = 0):
    return _do(get_session(sid), {"action": "delete", "type": typ, "key": key, "cascade": bool(cascade)})

class LayoutIn(BaseModel):
    positions: dict; reset: bool = False

@app.post("/api/sessions/{sid}/model/layout")
def model_layout(sid: str, b: LayoutIn):
    """保存拖拽布局（b<i> 或 dev:<id> -> [x,y]，0..1 归一化坐标）；不进入撤销栈。"""
    from .tools.sim_tools import _art
    s = get_session(sid); sc = _need_sc(s)
    if b.reset: sc.layout = {}
    for k, v in b.positions.items(): sc.layout[str(k)] = [round(float(v[0]), 4), round(float(v[1]), 4)]
    with open(_art(s, "scenario.json"), "w") as f: f.write(sc.model_dump_json(indent=2))
    from .tools.model_viz import refresh
    refresh(s); return {"ok": True, "n": len(sc.layout)}

@app.post("/api/sessions/{sid}/model/undo")
def model_undo(sid: str):
    s = get_session(sid); sc = _need_sc(s)
    if not s.state.get("edit_undo"): raise HTTPException(400, "没有可撤销的编辑")
    s.state.setdefault("edit_redo", []).append(sc.model_dump_json())
    s.state["scenario"] = Scenario.model_validate_json(s.state["edit_undo"].pop()); s.state["results"] = {}
    s.state.setdefault("edit_log", []).append(dict(t=time.strftime("%H:%M:%S"), desc="撤销")); s.state["edit_unsent"] = True
    save_session(s); return _edit_state(s, {"message": "已撤销"})

@app.post("/api/sessions/{sid}/model/redo")
def model_redo(sid: str):
    s = get_session(sid); sc = _need_sc(s)
    if not s.state.get("edit_redo"): raise HTTPException(400, "没有可重做的编辑")
    s.state.setdefault("edit_undo", []).append(sc.model_dump_json())
    s.state["scenario"] = Scenario.model_validate_json(s.state["edit_redo"].pop()); s.state["results"] = {}
    s.state.setdefault("edit_log", []).append(dict(t=time.strftime("%H:%M:%S"), desc="重做")); s.state["edit_unsent"] = True
    save_session(s); return _edit_state(s, {"message": "已重做"})

@app.get("/api/sessions/{sid}/model/validate")
def model_validate(sid: str):
    s = get_session(sid); return me.check_model(_need_sc(s))

class RerunIn(BaseModel):
    ac: bool = True; baseline: bool = False

@app.post("/api/sessions/{sid}/model/rerun")
def model_rerun(sid: str, b: RerunIn):
    """按编辑后的模型重新调度（+可选交流校核），返回编辑前/后关键指标对比，并刷新能流图。"""
    from .tools import call_tool
    from .tools import sdco_engine as eng
    s = get_session(sid); sc = _need_sc(s)
    v = me.check_model(sc)
    if v["errors"]: raise HTTPException(400, "模型校验未通过：" + "；".join(v["errors"]))
    before = s.state.get("edit_base_metrics")
    if before is None and s.state.get("edit_base"):
        try:
            b0 = Scenario.model_validate_json(s.state["edit_base"]); before = me.metrics(b0, eng.solve(b0, optimize=True))
        except Exception as e: before = None
    t0 = time.time()
    try:
        if b.baseline: call_tool(s, "run_dispatch", {"case": "baseline"})
        call_tool(s, "run_dispatch", {"case": "optimized"})
    except Exception as e: raise HTTPException(400, f"重新仿真失败：{e}")
    r = s.state["results"]["optimized"]; after = me.metrics(sc, r); ac = None
    if b.ac:
        try:
            a = call_tool(s, "run_ac_check", {}); ac = {k: a[k] for k in ("hour", "converged", "vmin_pu", "vmax_pu", "max_branch_loading_pct", "voltage_ok", "loading_ok", "losses_mw")}
        except Exception as e: ac = {"converged": False, "error": f"{type(e).__name__}: {e}"}
    cmp_ = me.compare(before, after)
    s.state["edit_base"] = sc.model_dump_json(); s.state["edit_base_metrics"] = after   # 本次结果成为下一轮“编辑前”基准
    s.state.setdefault("edit_log", []).append(dict(t=time.strftime("%H:%M:%S"), desc="重新仿真：" + "，".join((f"{c['metric']} {c['before']}→{c['after']}" if c['before'] is not None else f"{c['metric']} {c['after']}") for c in cmp_[:5])))
    s.state["edit_unsent"] = True; s.state["last_rerun"] = dict(compare=cmp_, ac=ac); save_session(s)
    return _edit_state(s, {"compare": cmp_, "before": before, "after": after, "ac": ac, "seconds": round(time.time() - t0, 2)})

@app.get("/api/sessions/{sid}/model/scenario.json")
def model_scenario_dl(sid: str):
    s = get_session(sid); sc = _need_sc(s)
    from fastapi.responses import Response
    return Response(sc.model_dump_json(indent=2), media_type="application/json",
                    headers={"Content-Disposition": f'attachment; filename="{sc.name}_edited.json"'})

@app.post("/api/sessions/{sid}/model/load")
def model_load(sid: str, scenario: dict):
    """加载场景 JSON（如先前保存的编辑模型）到当前会话，可撤销。"""
    s = get_session(sid)
    from .tools import sdco_engine as eng
    try:
        sc = Scenario.model_validate(scenario); errs = eng.validate(sc)
        if errs: raise ValueError("；".join(errs))
    except Exception as e: raise HTTPException(400, f"场景 JSON 不合法：{e}")
    if "scenario" not in s.state: return model_init(s.id, InitIn(scenario=scenario))
    _commit(s, sc, f"加载场景 JSON {sc.name}"); return _edit_state(s, {"message": f"已加载 {sc.name}"})

# ---------- 透明化工作流：步骤 / 参数表 / 数学模型 / 运行日志 / 结果解释 / 运行包 ----------
from . import transparency as tr

def _wf(s):
    steps, cur = tr.step_status(s)
    return dict(ok=True, session_id=s.id, steps=steps, current=cur, has_scenario="scenario" in s.state,
                scenario=s.state["scenario"].name if "scenario" in s.state else None,
                confirmed=bool(s.state.get("params_confirmed")), auto_run=bool(s.state.get("auto_run")),
                pending=[c["name"] for c in s.state.get("pending_calls", [])], solver_cfg={**tr.DEFAULT_SOLVER, **(s.state.get("solver_cfg") or {})},
                solved="optimized" in s.state.get("results", {}), runlog_n=len(s.state.get("runlog", [])))

@app.get("/api/sessions/{sid}/workflow")
def wf_get(sid: str): return _wf(get_session(sid))

@app.get("/api/sessions/{sid}/params")
def params_get(sid: str):
    s = get_session(sid); _need_sc(s); return tr.param_sheet(s)

class ParamIn(BaseModel):
    path: str; value: object = None

@app.patch("/api/sessions/{sid}/params")
def params_patch(sid: str, b: ParamIn):
    s = get_session(sid); _need_sc(s)
    prior = dict(s.state)
    if "scenario" in prior: prior["scenario"] = prior["scenario"].model_copy(deep=True)
    try:
        tr.set_param(s, b.path, b.value)
        if s.state.get("foundation_context") and not b.path.startswith("solver."):
            from .foundation.service import checked
            checked(s.state["scenario"].model_dump())
    except Exception as e:
        s.state.clear(); s.state.update(prior)
        raise HTTPException(400, f"参数 {b.path} 修改失败：{e}。请输入范围内的数值后重试。")
    # Legacy routes retain their established validation behavior.
    if not b.path.startswith("solver."):
        from .tools.sim_tools import _art
        with open(_art(s, "scenario.json"), "w") as f: f.write(s.state["scenario"].model_dump_json(indent=2))
        s.state.setdefault("edit_log", []).append(dict(t=time.strftime("%H:%M:%S"), desc=f"参数表修改 {b.path}={b.value}")); s.state["edit_unsent"] = True
        s.state.setdefault("runlog", []).append(dict(i=len(s.state.get("runlog", [])) + 1, ts=time.strftime("%H:%M:%S"), tool="edit_param", title="修改参数",
                                                     step="params", actor="用户（参数表）", why="用户在参数表中修改", args={"path": b.path, "value": b.value}, ok=True, duration_s=0, outputs={}))
    save_session(s); return tr.param_sheet(s)

class SolverIn(BaseModel):
    cfg: dict

@app.put("/api/sessions/{sid}/solver")
def solver_put(sid: str, b: SolverIn):
    s = get_session(sid)
    bad = [k for k in b.cfg if k not in tr.DEFAULT_SOLVER]
    if bad: raise HTTPException(400, f"未知求解配置项 {bad}；可用：{list(tr.DEFAULT_SOLVER)}")
    s.state.setdefault("solver_cfg", {}).update(b.cfg); return _wf(s)

class ConfirmIn(BaseModel):
    auto_run: bool | None = None

@app.post("/api/sessions/{sid}/workflow/confirm")
def wf_confirm(sid: str, b: ConfirmIn):
    s = get_session(sid); sc = _need_sc(s)
    from .tools import sdco_engine as eng
    errs = eng.validate(sc)
    if errs: raise HTTPException(400, "参数校验未通过，无法确认：" + "；".join(errs))
    s.state["params_confirmed"] = True; s.state["wf_step"] = "solver"
    if b.auto_run is not None: s.state["auto_run"] = b.auto_run
    s.state.setdefault("runlog", []).append(dict(i=len(s.state.get("runlog", [])) + 1, ts=time.strftime("%H:%M:%S"), tool="confirm", title="确认参数",
                                                 step="params", actor="用户", why="用户核对参数表后确认", args={}, ok=True, duration_s=0, outputs={}))
    save_session(s); return _wf(s)

def _pipeline(s):
    from .tools import call_tool
    cfg = {**tr.DEFAULT_SOLVER, **(s.state.get("solver_cfg") or {})}
    plan = [("run_dispatch", {"case": "optimized"}, "求解优化方案")]
    if cfg["run_baseline"]: plan.append(("run_dispatch", {"case": "baseline"}, "求解无协同基线"))
    std = {"build_scenario", "run_dispatch", "run_ac_check", "compute_kpis", "compare_baseline", "make_plots", "write_report", "show_model_topology"}
    for c in s.state.pop("pending_calls", []):
        if c["name"] not in std: plan.append((c["name"], c.get("args") or {}, "智能体计划中的附加分析"))
    if cfg["ac_check"]: plan.append(("run_ac_check", {"hour": cfg["ac_hour"]} if cfg.get("ac_hour") not in (None, "") else {}, "交流潮流校核"))
    plan.append(("compute_kpis", {"case": "optimized"}, "计算 KPI"))
    if cfg["run_baseline"]: plan.append(("compare_baseline", {}, "基线对比"))
    plan += [("make_plots", {}, "生成图表"), ("write_report", {}, "撰写报告")]
    n = len(plan) + (1 if cfg["attribution"] and cfg["run_baseline"] else 0)
    for i, (name, args, why) in enumerate(plan):
        yield dict(type="progress", i=i + 1, n=n, name=name, title=tr.TOOL_CN.get(name, name), why=why)
        s.state["_actor"] = "用户（工作流）"; s.state["_why"] = why
        try: call_tool(s, name, args)
        except Exception as e:
            yield dict(type="error", name=name, error=f"{type(e).__name__}: {e}", log=s.state["runlog"][-1],
                       hint="请回到「② 输入参数」检查容量/负荷/约束是否过紧，或在「④ 求解配置」放宽时间上限后重试。"); return
        yield dict(type="log", log=s.state["runlog"][-1])
    if cfg["attribution"] and cfg["run_baseline"]:
        yield dict(type="progress", i=n, n=n, name="attribution", title="收益归因（反事实求解）", why="分解收益来源")
        t0 = time.time()
        try:
            r = s.state["results"]; s.state["attribution"] = tr.attribution(s.state["scenario"], r["baseline"], r["optimized"], dict(time_limit_s=cfg["time_limit_s"]))
            e = dict(i=len(s.state["runlog"]) + 1, ts=time.strftime("%H:%M:%S"), tool="attribution", title="收益归因", step="results", actor="用户（工作流）",
                     why="额外求解 2 个反事实 LP（仅时移；时移+迁移），分解收益来源", args={}, ok=True, duration_s=round(time.time() - t0, 3),
                     outputs={"total_saving": s.state["attribution"]["total_saving"], "parts": {p["id"]: p["saving"] for p in s.state["attribution"]["parts"]}})
            s.state["runlog"].append(e); yield dict(type="log", log=e)
        except Exception as ex: yield dict(type="log", log=dict(title="收益归因", ok=False, error=str(ex)))
    s.state["wf_step"] = "results"
    k = s.state.get("kpis", {}).get("optimized", {}); c = s.state.get("compare") or {}
    s.messages.append({"role": "assistant", "content": f"[工作流] 已按用户确认的参数完成运行：目标函数 {k.get('total_objective_cny')} 元，" + (f"较基线节省 {c.get('saving_pct')}%。" if c else "")})
    yield dict(type="done")

@app.post("/api/sessions/{sid}/workflow/run")
def wf_run(sid: str, stream: int = 1):
    s = get_session(sid); sc = _need_sc(s)
    if not s.state.get("params_confirmed"): raise HTTPException(400, "请先在「② 输入参数」点击「确认参数」，再运行。")
    if not stream:
        evs = list(_pipeline(s)); save_session(s); return {"ok": evs[-1]["type"] == "done", "events": evs, **_wf(s)}
    def gen():
        for e in _pipeline(s): yield f"data: {json.dumps(e, ensure_ascii=False, default=str)}\n\n"
        save_session(s); yield f"data: {json.dumps({'type': 'end', 'artifacts': _arts(s)}, ensure_ascii=False)}\n\n"
    return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

@app.get("/api/sessions/{sid}/formulation")
def formulation_get(sid: str):
    s = get_session(sid); sc = _need_sc(s); return tr.formulation(sc, s.state.get("results", {}).get("optimized"))

@app.get("/api/sessions/{sid}/runlog")
def runlog_get(sid: str):
    s = get_session(sid); res = s.state.get("results", {})
    return dict(ok=True, log=s.state.get("runlog", []), solver={k: v.get("solver") for k, v in res.items()}, ac=s.state.get("ac", {}))

def _series(r):
    df = r["df"]; dc = [c for c in df if c.endswith("_grid_MW")]
    out = dict(hours=df.hour.tolist(),dt_hours=r.get("solver",{}).get("resolution_h",1),dc_total=df[dc].sum(axis=1).round(3).tolist(), pv_avail=df.pv_avail.round(3).tolist(), pv_used=df.pv_used.round(3).tolist(),
               hour_cost=df.hour_cost.round(1).tolist(), grid_import=df.grid_import_MW.round(3).tolist() if "grid_import_MW" in df else None,
               storage={st: dict(ch=df[f"{st}_ch"].round(3).tolist(), dis=df[f"{st}_dis"].round(3).tolist(), soc=df[f"{st}_soc"].round(3).tolist()) for st in r["storage"]})
    th = r.get("thermal")
    if th:
        L = lambda c: df[c].round(3).tolist()
        out["thermal"] = {d: dict(tin=L(f"{d}_Tin_C"), tout=L(f"{d}_Tout_C"), pue=L(f"{d}_PUE"), cool=L(f"{d}_cool_MW"), it=L(f"{d}_IT_MW"),
                                  cop=L(f"{d}_COP"), chiller=L(f"{d}_chiller_MWth"), free=L(f"{d}_free_MWth"), tes_soc=L(f"{d}_tes_soc_MWh"),
                                  hp_heat=L(f"{d}_hp_heat_MWth"), cool_avail=L(f"{d}_cool_avail_MWth"), summary=x) for d, x in th["dcs"].items()}
        out["heat"] = dict(delivered=L("heat_delivered_MWth"), demand=L("heat_demand_MWth"), store=L("heat_store_MWh"), summary=th.get("heat")) if th.get("heat") else None
        out["thermal_violations"] = th["violations"]
    if r.get("dr"):
        out["dr"] = dict(events=r["dr"], delivered=L2(df, "dr_delivered_MW"), request=L2(df, "dr_request_MW"), baseline=L2(df, "dr_baseline_MW"))
    return out

def L2(df, c): return df[c].round(3).tolist() if c in df else None

@app.get("/api/sessions/{sid}/results")
def results_get(sid: str):
    s = get_session(sid); sc = _need_sc(s); res = s.state.get("results", {})
    if "optimized" not in res: return {"ok": False, "error": "尚无结果：请完成「⑤ 运行与校核」。"}
    from .tools.sim_tools import _kpis
    ko = _kpis(sc, res["optimized"]); kb = _kpis(sc, res["baseline"]) if "baseline" in res else None
    ac = s.state.get("ac", {}).get("optimized")
    return dict(ok=True, kpis=tr.kpi_cards(ko, kb), compare=s.state.get("compare"), attribution=s.state.get("attribution"),
                warnings=tr.warnings(sc, ac, res["optimized"]), ac=ac, solver={k: v.get("solver") for k, v in res.items()},
                audit={k:{key:v.get(key) for key in ("market_clearing","network_mapping","network_dispatch","job_admission","allocations","migration_audit","lifecycle_ledger","execution_context","time_axis","integer_tasks","migration_cleanup","heat_network_audit","heat_boundary_audit","execution_serialization")} for k,v in res.items()},
                cost_terms={k: v.get("cost_terms") for k, v in res.items()}, term_cn=tr.TERM_CN,
                price=list(sc.price_cny_kwh), series={k: _series(v) for k, v in res.items()},
                thermal_limits={d.name: dict(t_min=d.thermal.t_min_c, t_rec=d.thermal.t_rec_max_c, t_allow=d.thermal.t_allow_max_c) for d in sc.data_centers if d.thermal is not None},
                report=f"/artifacts/{sid}/report.md" if "report.md" in s.artifacts else None, plots=s.state.get("plots", []))

@app.get("/api/sessions/{sid}/export.zip")
def export_zip(sid: str):
    s = get_session(sid); sc = _need_sc(s)
    if "optimized" not in s.state.get("results", {}): raise HTTPException(400, "请先完成运行再导出运行包")
    from fastapi.responses import Response
    data = tr.export_package(s, os.path.abspath(os.path.join(ROOT, "..")))
    return Response(data, media_type="application/zip", headers={"Content-Disposition": f'attachment; filename="run_{sc.name}_{sid}.zip"'})

@app.get("/artifacts/{sid}/{name}")
def artifact(sid: str, name: str, download: int = 0):
    p = os.path.abspath(os.path.join(ART_ROOT, sid, name))
    if not p.startswith(ART_ROOT + os.sep) or not os.path.isfile(p): raise HTTPException(404)
    return FileResponse(p, filename=name if download else None)

# ---------- 知识库 ----------
@app.post("/api/kb/docs")
async def kb_upload(file: UploadFile = File(...)):
    name = os.path.basename(file.filename or "upload.txt")
    if os.path.splitext(name)[1].lower() not in kb.ALLOWED: raise HTTPException(400, f"不支持的类型，允许: {sorted(kb.ALLOWED)}")
    path = os.path.join(kb.DOC_DIR, f"{uuid.uuid4().hex[:8]}_{name}")
    with open(path, "wb") as f: f.write(await file.read())
    try: return kb.add_document(path, name)
    except Exception as e: os.remove(path); raise HTTPException(400, str(e))

@app.get("/api/kb/docs")
def kb_docs(): return kb.list_documents()

@app.delete("/api/kb/docs/{did}")
def kb_del(did: str): return {"ok": kb.delete_document(did)}

@app.get("/api/kb/search")
def kb_search(q: str):
    t = time.time(); r = kb.retrieve(q, 4); r["latency_ms"] = round((time.time()-t)*1000); r["backend"] = kb.backend_info(); return r

@app.get("/api/kb/info")
def kb_info(): return kb.backend_info()

@app.post("/api/kb/reindex")
def kb_reindex(): return kb.reindex_all()

class CardIn(BaseModel):
    title: str; task_type: str = ""; keywords: str = ""; steps: str = ""; params: str = ""; checks: str = ""; example: str = ""

@app.get("/api/cards")
def cards(): return kb.list_cards()

@app.post("/api/cards")
def card_new(c: CardIn): return kb.save_card(c.model_dump())

@app.put("/api/cards/{cid}")
def card_put(cid: str, c: CardIn):
    if not kb.get_card(cid): raise HTTPException(404)
    return kb.save_card(c.model_dump() | {"id": cid})

@app.delete("/api/cards/{cid}")
def card_del(cid: str): return {"ok": kb.delete_card(cid)}

# ---------- 设置 / 场景 / 仿真器 ----------
@app.get("/api/settings")
def settings_get(): return settings.all_masked()

@app.put("/api/settings")
def settings_put(d: dict): settings.update(d); return settings.all_masked()

@app.get("/api/scenario/default")
def scenario_default(storage_mwh: float = 50): return build_default(3, storage_mwh).model_dump()

class JobsIn(BaseModel):
    scenario: dict | None = None; n_jobs: int = 30; seed: int = 42; latency_sensitive_share: float = 0.3

@app.post("/api/jobs/generate")
def jobs_generate(b: JobsIn):
    """为场景参数面板生成合成任务与默认链路（不运行调度）。"""
    from .scenario import generate_jobs, Link, DEFAULT_LINKS
    sc = Scenario.model_validate(b.scenario) if b.scenario else build_default(3)
    sc.jobs = generate_jobs(sc, b.n_jobs, b.seed, b.latency_sensitive_share)
    names = {d.name for d in sc.data_centers}
    if not sc.links: sc.links = [Link(**l) for l in DEFAULT_LINKS if l["a"] in names and l["b"] in names]
    if not sc.mig_energy_mwh_per_mwh: sc.mig_energy_mwh_per_mwh = 0.03
    return sc.model_dump()

@app.post("/api/carbon/profile")
def carbon_profile_api(scenario: dict | None = None):
    from .scenario import carbon_profile, region_of
    sc = Scenario.model_validate(scenario) if scenario else build_default(3)
    return {f"{d.name}({region_of(sc, d.bus)})": [round(float(x), 4) for x in carbon_profile(sc, d.bus)] for d in sc.data_centers}

@app.get("/api/scenario/presets")
def scenario_presets():
    from .scenario import list_presets
    return {"presets": list_presets()}

@app.get("/api/scenario/preset/{name}")
def scenario_preset(name: str):
    from .scenario import load_preset
    try: return load_preset(name).model_dump()
    except ValueError as e: raise HTTPException(404, str(e))

@app.get("/api/scenario/schema")
def scenario_schema(): return Scenario.model_json_schema()

_SIMS = [("pandapower + Pyomo/HiGHS (算电协同调度/交流校核)", "pandapower", None, ["build_scenario", "run_dispatch", "run_ac_check"]),
         ("MATPOWER 8.1 (GNU Octave)", None, "octave-cli", ["run_matpower"]),
         ("ANDES 2.0 (暂态稳定)", "andes", None, ["run_andes_tds"]),
         ("OpenDSS (opendssdirect, 配网)", "opendssdirect", None, ["run_opendss"]),
         ("OpenModelica (omc, PowerSystems 2.0/MSL 4.1)", None, "omc", ["run_openmodelica"]),
         ("碳感知 Pareto / 任务级作业 (Phase 1, HiGHS)", "highspy", None, ["run_pareto_sweep", "get_carbon_profile", "generate_jobs", "load_job_trace"]),
         ("中文 RAG (bge-m3 + bge-reranker + jieba BM25 + LanceDB)", "sentence_transformers", None, ["search_knowledge"]),
         ("ParaView pvpython (3D 可视化, 可选)", None, "pvpython", ["run_paraview_render"])]

@app.get("/api/simulators")
def simulators():
    out = []
    for name, mod, exe, tools in _SIMS:
        ok = (importlib.util.find_spec(mod) is not None) if mod else bool(shutil.which(exe))
        ver = ""
        try:
            if mod: ver = __import__(mod).__version__
        except Exception: pass
        out.append(dict(name=name, available=ok, version=ver, tools=tools, path=shutil.which(exe) if exe else mod))
    return dict(simulators=out, tools=[t.mcp_spec() for t in REGISTRY.values()],
                llm=dict(mock=settings.get("LLM_MOCK") == "1", model=settings.get("LLM_MODEL")))

@app.get("/tools")
def tools(): return [t.mcp_spec() for t in REGISTRY.values()]

# ---------------- 散热方式库 / 配置构建器 / 对比扫描 / 余热可行性 ----------------
class CfgIn(BaseModel):
    spec: dict | None = None
    set: dict | None = None
    variants: list | None = None
    params: list | None = None
    base: dict | None = None
    title: str | None = None
    modes: list | None = None
    terminals: list | None = None
    lengths_km: list | None = None


@app.post("/api/sessions/{sid}/calibrate/power")
async def api_calibrate_power(sid: str, file: UploadFile = File(None), mode: str = "idle_dynamic", dc: str = None, n_servers: int = None, apply: bool = True):
    """上传 PDU CSV 标定功率模型。也可 JSON body 走工具。"""
    from .tools import call_tool
    s = get_session(sid)
    if file is None: raise HTTPException(400, "需要 multipart 文件字段 file")
    raw = (await file.read()).decode("utf-8", errors="replace")
    path = os.path.join(s.artifact_dir, "upload_pdu_calib.csv"); os.makedirs(s.artifact_dir, exist_ok=True)
    open(path, "w", encoding="utf-8").write(raw)
    out = call_tool(s, "calibrate_power_model", dict(csv_path=path, mode=mode, dc=dc, n_servers=n_servers, apply=apply, solve=False))
    save_session(s); return out

@app.post("/api/sessions/{sid}/check_year_days")
def api_check_year_days(sid: str, body: dict | None = None):
    from .tools import call_tool
    s = get_session(sid); body = body or {}
    out = call_tool(s, "check_year_days", body); save_session(s); return out

@app.post("/api/sessions/{sid}/heat/multi")
def api_heat_multi(sid: str, body: dict | None = None):
    from .tools import call_tool
    s = get_session(sid); body = body or {}
    out = call_tool(s, "build_multi_heat_network", body); save_session(s); return out

@app.get("/api/cooling/modes")
def cooling_modes():
    from .tools import cooling as CL
    from .tools.heat_grade import TERMINALS
    return {"modes": CL.library(), "terminals": TERMINALS}

@app.get("/api/config/template")
def config_template():
    from .tools import config_builder as B
    return {"template": B.TEMPLATE, "hp_types": B.HP_TYPES}

@app.post("/api/config/validate")
def config_validate(b: CfgIn):
    from .tools import config_builder as B
    sp = B.full_spec(b.spec or {})
    for k, v in (b.set or {}).items(): sp = B.set_path(sp, k, v)
    return B.validate_spec(sp)

@app.get("/api/sessions/{sid}/config")
def config_get(sid: str):
    from .tools import config_builder as B
    s = get_session(sid); return {"spec": s.state.get("config_spec") or B.full_spec({}), "last_sweep": s.state.get("last_sweep")}

def _cfg_call(sid, name, args):
    from .tools import call_tool
    s = get_session(sid)
    try: r = call_tool(s, name, args)
    except Exception as e: raise HTTPException(400, f"{type(e).__name__}: {e}")
    save_session(s)
    if name == "build_config" and r.get("ok"):
        try: s.state["scenario"].model_dump_json(); open(os.path.join(s.artifact_dir, "scenario.json"), "w", encoding="utf-8").write(s.state["scenario"].model_dump_json())
        except Exception: pass
    return {**r, "artifacts": _arts(s)}

@app.post("/api/sessions/{sid}/config/build")
def config_build(sid: str, b: CfgIn): return _cfg_call(sid, "build_config", {"spec": b.spec, "set": b.set})

@app.post("/api/sessions/{sid}/config/sweep")
def config_sweep(sid: str, b: CfgIn): return _cfg_call(sid, "run_config_sweep", {"base": b.base or b.spec, "variants": b.variants, "params": b.params, "title": b.title})

@app.post("/api/sessions/{sid}/config/heat_study")
def config_heat(sid: str, b: CfgIn): return _cfg_call(sid, "heat_feasibility_study", {"modes": b.modes, "terminals": b.terminals, "lengths_km": b.lengths_km, "base": b.base or b.spec})



@app.get("/api/sessions/{sid}/tier")
def api_tier_get(sid: str):
    from .tools import call_tool
    s = get_session(sid)
    return call_tool(s, "get_tier_timeline", {})

@app.post("/api/sessions/{sid}/tier/baseline")
def api_tier_baseline(sid: str, body: dict | None = None):
    from .tools import call_tool
    s = get_session(sid); b = body or {}
    out = call_tool(s, "save_day_ahead_baseline", b); save_session(s); return out

@app.post("/api/sessions/{sid}/tier/patch")
def api_tier_patch(sid: str, body: dict | None = None):
    from .tools import call_tool
    s = get_session(sid); b = body or {}
    out = call_tool(s, "apply_forecast_patch", b); save_session(s); return out

@app.post("/api/sessions/{sid}/tier/reoptimize")
def api_tier_reopt(sid: str, body: dict | None = None):
    from .tools import call_tool
    s = get_session(sid); b = body or {}
    out = call_tool(s, "reoptimize_intraday", b); save_session(s); return out

@app.post("/api/sessions/{sid}/tier/envelope")
def api_tier_env(sid: str, body: dict | None = None):
    from .tools import call_tool
    s = get_session(sid); b = body or {}
    out = call_tool(s, "compute_flexibility_envelope", b); save_session(s); return out

@app.post("/api/sessions/{sid}/tier/realtime")
def api_tier_rt(sid: str, body: dict | None = None):
    from .tools import call_tool
    s = get_session(sid); b = body or {}
    out = call_tool(s, "run_realtime_track", b); save_session(s); return out


@app.post("/api/sessions/{sid}/tier/backup")
def api_tier_backup(sid: str, body: dict | None = None):
    from .tools import call_tool
    s = get_session(sid); b = body or {}
    out = call_tool(s, "configure_backup_resources", b); save_session(s); return out

@app.get("/api/sessions/{sid}/tier/backup")
def api_tier_backup_get(sid: str):
    from .tools import call_tool
    s = get_session(sid)
    return call_tool(s, "list_backup_resources", {})

@app.post("/api/sessions/{sid}/tier/emergency")
def api_tier_emerg(sid: str, body: dict | None = None):
    from .tools import call_tool
    s = get_session(sid); b = body or {}
    out = call_tool(s, "set_emergency_mode", b); save_session(s); return out

@app.post("/api/sessions/{sid}/tier/coupling")
def api_tier_coup(sid: str, body: dict | None = None):
    from .tools import call_tool
    s = get_session(sid); b = body or {}
    out = call_tool(s, "report_load_cooling_coupling", b); save_session(s); return out


from .market.api import router as _market_router   # P0 运营沙盘（默认 sandbox，不影响原功能）
app.include_router(_market_router)
from .foundation.api import router as _foundation_router
app.include_router(_foundation_router)


@app.get("/health")
def health(): return {"ok": True, "mock": settings.get("LLM_MOCK") == "1"}

@app.on_event("startup")
def _warm_rag():   # 空库时写入模板/气象示例与 knowledge_seed；后台预加载嵌入模型
    from .foundation import service as F, store as S
    F.recover_interrupted_tasks()
    with S.LOCK:
        F.seed(); F.seed_public_climate()
    import threading
    def _bg():
        try: kb.seed_from_repo()
        except Exception as e: print("[startup] knowledge seed failed:", e)
        if os.getenv("RAG_PRELOAD", "1") == "1":
            try: kb.backend_info()
            except Exception as e: print("[startup] RAG preload failed:", e)
    threading.Thread(target=_bg, daemon=True).start()

from .help_api import router as _help_router   # 产品内在线帮助（本地静态手册，不调用 LLM）
app.include_router(_help_router)

app.mount("/static", StaticFiles(directory=os.path.join(ROOT, "static")), name="static")

@app.get("/")
def index():
    r = FileResponse(os.path.join(ROOT, "static", "index.html"))
    r.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    r.headers["Pragma"] = "no-cache"
    return r


# Explicit local research interfaces; they do not call external services.
@app.get("/paper-reproduction")
def paper_reproduction_ui():
    return FileResponse(os.path.join(ROOT,"static","paper_reproduction.html"))

@app.get("/api/paper-reproduction/cases/{name}")
def paper_reproduction_case(name: str):
    from pathlib import Path
    allowed=[f"zhang_s{i}" for i in range(1,8)]+["zheng2019_annual"]
    if name not in allowed: raise HTTPException(404,"Unknown published-input case")
    path=Path(ROOT).parent/"cases"/"paper_reproduction"/"inputs"/(name+".json")
    if not path.exists(): raise HTTPException(404,"Published inputs not installed")
    return json.loads(path.read_text())

from .paper_annual import AnnualMigrationInput
@app.post("/api/paper-reproduction/annual-migration")
def paper_annual_migration(body: AnnualMigrationInput):
    from .paper_annual import evaluate
    from pathlib import Path
    from .foundation.store import digest
    import csv, zipfile
    result=evaluate(body); aid="paper"+uuid.uuid4().hex[:16]; folder=Path(ART_ROOT)/aid; folder.mkdir(parents=True)
    inputs=body.model_dump(); result["input_hash"]=digest(inputs)
    from .foundation.service import code_identity
    result["execution_code_hash"]=code_identity()
    result["analysis_id"]=aid; result["export_url"]=f"/artifacts/{aid}/annual_audit.zip"
    (folder/"input.json").write_text(json.dumps(inputs,ensure_ascii=False))
    (folder/"results.json").write_text(json.dumps(result,ensure_ascii=False))
    for key in ("grid","hourly"):
        with (folder/(key+".csv")).open("w",newline="") as f:
            writer=csv.DictWriter(f,fieldnames=list(result[key][0]));writer.writeheader();writer.writerows(result[key])
    with zipfile.ZipFile(folder/"annual_audit.zip","w",zipfile.ZIP_DEFLATED) as z:
        for name in ("input.json","results.json","grid.csv","hourly.csv"): z.write(folder/name,name)
    return result


@app.post("/api/time-axis/resample-hourly")
def explicit_resample_hourly(scenario: dict):
    from .time_axis import resample_hourly
    from .tools.sdco_engine import validate
    try:
        raw=resample_hourly(Scenario.model_validate(scenario).model_dump())
        sc=Scenario.model_validate(raw);errors=validate(sc)
        if errors: raise ValueError("; ".join(errors))
        return dict(model=sc.model_dump(),axis_patch=dict(step_minutes=15,length=96),method="explicit_sample_and_hold",warning="能量积分守恒不等于不同分辨率策略结果相同；旧场景/版本不改写")
    except Exception as e: raise HTTPException(400,str(e))

# Explicit annual portfolio mode; never handed to the 24h Scenario/daily sessions.
from .opt_cfe_api import router as opt_cfe_router
app.include_router(opt_cfe_router)

@app.get("/api/solver-execution/status")
def solver_execution_status():
    from .solver_execution import execution_status
    return execution_status()

from .opt_grid_feedback_api import router as opt_grid_feedback_router
app.include_router(opt_grid_feedback_router)

from .opt_gpu_api import router as opt_gpu_router
app.include_router(opt_gpu_router)
