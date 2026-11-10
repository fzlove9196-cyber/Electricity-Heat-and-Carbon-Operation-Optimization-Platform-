"""研究编排器（状态机）：formulate → clarify → plan → execute(诊断/修订循环) → conclude → sediment。
研究状态持久化在 session.state["study"]（JSON 可序列化；求解中间对象以 _ 前缀保存在内存）。
Mock 模式全部走确定性规则；真实 LLM 通过 llm_bridge 做形式化补充/决策/解读（失败自动回退）。"""
from __future__ import annotations
import copy, json, os, re, time
from ..scenario import Scenario, load_preset
from . import topics as TP, diagnostics as DG, experiments as EX, llm_bridge as LB

MAX_REVISIONS = 3
PHASES = [("formulate", "问题形式化"), ("clarify", "澄清"), ("plan", "研究计划"), ("execute", "执行·诊断·修订"), ("conclude", "证据化结论"), ("sediment", "知识沉淀")]

def get(s): return s.state.get("study")
def _now(): return time.strftime("%H:%M:%S")
def _tl(st, kind, text, step=None, why=None): st.setdefault("timeline", []).append(dict(t=_now(), kind=kind, text=text, step=step, why=why))
def _base(st) -> Scenario: return Scenario.model_validate(st["base_sc"])
def _model(st) -> Scenario: return EX.apply_mods(_base(st), st["model_mods"])

def public(st):
    if not st: return None
    d = {k: v for k, v in st.items() if not k.startswith("_") and k not in ("base_sc",)}
    d["runs"] = {k: EX.public_run(v) for k, v in st.get("runs", {}).items()}
    for r in d["runs"].values(): r["findings"] = r.get("findings", [])
    d["phases"] = [dict(id=a, label=b, done=PHASES.index((a, b)) < _phase_idx(st), current=_phase_idx(st) == i) for i, (a, b) in enumerate(PHASES)]
    d["llm_mode"] = "mock(确定性规则)" if LB.is_mock() else "真实 LLM（function calling）"
    return d

def _phase_idx(st):
    return {"formulate": 0, "clarify": 1, "plan": 2, "execute": 3, "checkpoint": 3, "conclude": 4, "done": 5}.get(st["state"], 0)

def _msg(s, st, text):
    st.setdefault("msgs", []).append(dict(idx=len(st["msgs"]), text=text, t=_now())); return len(st["msgs"]) - 1

def _say(s, content, **kw):
    s.messages.append({"role": "assistant", "content": content}); return dict(type="message", content=content, final=kw.get("final", False))

def _ev_study(st): return dict(type="study", study=public(st))

# ---------------- 路由 ----------------
CMD = re.compile(r"^【(澄清回答|批准计划|检查点|采纳沉淀|生成报告)】")
def route(s, text, force=False):
    st = get(s); t = text.strip()
    from . import opt_flow as _of
    if _of.routes(s, t): return True
    if CMD.match(t) and st: return True
    if st and st["state"] in ("clarify", "plan", "checkpoint"): return True
    if st and st["state"] in ("done", "conclude") and (_is_why(t) or _is_whatif(t)): return True
    return bool(force)

def _is_why(t): return t.startswith("为什么") or "为何" in t[:6] or "原因" in t[:8]
def _is_whatif(t): return t.startswith("如果") or "会怎样" in t or "会怎么样" in t or "what if" in t.lower()

def chat_events(s, text, force=False):
    st = get(s); t = text.strip()
    from . import opt_flow as _of
    if _of.routes(s, t) and not CMD.match(t):   # 寻优分支：需求驱动的目标规格 → 求解 → 帕累托/追问
        yield from _of.chat_events(s, t); return
    s.messages.append({"role": "user", "content": t})
    yield from _sync_ui_edits(s, st)
    m = CMD.match(t)
    if m:
        kind = m.group(1); idx = _msg(s, st, t); yield dict(type="user_ref", idx=idx)
        if kind == "澄清回答": yield from answer(s, _parse_answers(st, t), idx)
        elif kind == "批准计划": yield from execute(s)
        elif kind == "检查点":
            mm = re.search(r"(K\d+)\D*(\w+)", t[5:]); yield from checkpoint(s, mm.group(1) if mm else None, (mm.group(2) if mm else "adopt"))
        elif kind == "采纳沉淀":
            ids = re.findall(r"S\d+", t); yield from sediment(s, ids)
        elif kind == "生成报告": yield from report_events(s)
        return
    if st and st["state"] == "clarify" and not TP.is_study_question(t):
        idx = _msg(s, st, t); yield dict(type="user_ref", idx=idx)
        ans = {qid: v for qid, (v, _) in TP.prefill(st["questions"], t).items()}
        yield from answer(s, ans, idx, free_text=t); return
    if st and st["state"] in ("done", "conclude", "checkpoint", "plan") and _is_why(t):
        idx = _msg(s, st, t); yield dict(type="user_ref", idx=idx); yield from why(s, t); return
    if st and st["state"] in ("done", "conclude", "plan") and _is_whatif(t):
        idx = _msg(s, st, t); yield dict(type="user_ref", idx=idx); yield from whatif(s, t); return
    yield from start(s, t)

def _parse_answers(st, t):
    out = {}
    for qid, v in re.findall(r"(q_\w+)\s*=\s*([^;；\s]+)", t):
        q = next((x for x in st["questions"] if x["id"] == qid), None)
        if not q: continue
        opt = next((o["v"] for o in q["options"] if str(o["v"]).lower() == v.lower()), None)
        if opt is None:
            try: opt = float(v)
            except ValueError: opt = v
        out[qid] = opt
    return out

# ---------------- ① 形式化 + ② 澄清 ----------------
def start(s, text):
    topic = TP.detect(text) or "heat_recovery"
    F = TP.formulate(topic, text)
    st = dict(id=f"study_{int(time.time())}", topic=topic, state="formulate", question=text, msgs=[], card=F["card"], questions=F["questions"],
              params={}, params_flat={}, model_mods={}, param_src={}, plan=[], runs={}, revisions=[], checkpoints=[], conclusions=[], whatifs=[],
              sediment=[], references=[], iter=dict(revisions=0, cap=MAX_REVISIONS), timeline=[], auto_revise=False, created=_now())
    s.state["study"] = st
    idx = _msg(s, st, text); yield dict(type="user_ref", idx=idx)
    _tl(st, "formulate", "解析研究问题 → 生成研究问题卡", why="把自然语言问题转为：研究问题、决策变量、约束、评价指标、情景与假设")
    # 参考经验（知识沉淀复用）
    try:
        from .. import knowledge as kb
        cards = kb.search_cards(text + " " + F["card"]["title"], k=4)
        st["references"] = [dict(id=c["id"], title=c["title"], task_type=c.get("task_type"), example=str(c.get("example") or "")[:200], params=c.get("params"))
                             for c in cards if c.get("id") != "builtin"]
    except Exception as e: st["references"] = []
    for r in st["references"]:
        if "研究" in str(r.get("task_type")): F["card"]["assumptions"].append(f"参考经验「{r['title']}」：{r['example'][:80]}")
    # 真实 LLM：补充问题卡与需澄清项（不得改变数字）
    llm = LB.call("submit_problem_card", "你是算电热碳耦合仿真研究助手。基于模板问题卡与候选澄清问题，用中文完善问题卡，只能从候选中选择需澄清的问题。",
                  dict(question=text, template=F["card"], candidates=[dict(id=q["id"], q=q["q"]) for q in F["questions"]]))
    if llm:
        for k in ("research_question", "decision_variables", "constraints", "kpis", "scenarios"):
            if llm.get(k): st["card"][k] = llm[k]
        if llm.get("assumptions"): st["card"]["assumptions"] = list(dict.fromkeys(st["card"]["assumptions"] + llm["assumptions"]))
        st["card"]["by"] = "LLM"
    else: st["card"]["by"] = "规则模板（Mock）"
    st["base_sc"] = load_preset(F["card"]["preset"]).model_dump()
    pre = TP.prefill(st["questions"], text)
    for q in st["questions"]:
        if q["id"] in pre:
            v, quote = pre[q["id"]]; q["answer"] = v; q["source"] = dict(tag="用户指定", note=f"首条提问原文：“{quote}”", msg=dict(idx=idx, quote=quote))
    yield dict(type="study_card", card=dict(kind="problem", study=public(st)))
    yield _say(s, f"📋 我把你的问题形式化为**研究问题卡**（右侧「🔬 研究」可查看/修改）：\n\n> {st['card']['research_question']}\n\n"
                  + (f"📚 参考了 {len(st['references'])} 条已有经验：" + "、".join(f"「{r['title']}」" for r in st["references"]) + "\n\n" if st["references"] else ""))
    st["state"] = "clarify"
    pend = [q for q in st["questions"] if "answer" not in q]
    _tl(st, "clarify", f"识别 {len(pend)} 项关键缺失信息，向用户澄清（均给出默认值）", why="这些参数决定结论方向，不能静默假设")
    yield _ev_study(st)
    yield dict(type="study_card", card=dict(kind="clarify", questions=pend, answered=[q for q in st["questions"] if "answer" in q]))
    yield _say(s, "❓ 还有几项**关键信息**需要你确认（每项都有默认值，可直接点「用默认值继续」）。", final=True)

def answer(s, ans, idx, free_text=None):
    st = get(s)
    for q in st["questions"]:
        if q["id"] in ans:
            q["answer"] = ans[q["id"]]; q["source"] = dict(tag="用户指定", note=f"澄清回答：{q['q']} → {ans[q['id']]}", msg=dict(idx=idx, quote=st["msgs"][idx]["text"][:80]))
        elif "answer" not in q:
            q["answer"] = q["default"]; q["source"] = dict(tag="智能体推断", note=f"未回答，采用默认值（{q['why']}）", msg=dict(idx=idx, quote="（用户选择默认值继续）"))
    st["params"] = {q["id"]: (q["path"], q["answer"]) for q in st["questions"]}; st["params_flat"] = {q["id"]: q["answer"] for q in st["questions"]}
    st["model_mods"] = TP.answers_to_mods(st["topic"], st["params"])
    for q in st["questions"]:
        st["param_src"][q["path"]] = dict(tag=q["source"]["tag"], note=q["source"]["note"], msg=q["source"].get("msg"), qid=q["id"])
    st["assumption_list"] = _assumptions(st)
    _apply_to_workbench(s, st, "澄清完成：按回答构建模型")
    _tl(st, "clarify", "澄清完成，构建模型：" + EX.describe_mods(st["model_mods"]))
    st["plan"] = TP.plan(st["topic"], st["params"]); st["state"] = "plan"
    _tl(st, "plan", f"生成研究计划 {len(st['plan'])} 步：基线 → 主方案 → 敏感性 → 方案比较 → 压力测试 → 校核", why="先建立可比基准，再逐步检验结论的稳健性")
    yield _ev_study(st)
    yield dict(type="study_card", card=dict(kind="plan", plan=st["plan"]))
    yield _say(s, "🗺 已生成**研究计划**（可在右侧勾选/删减步骤、修改敏感性取值）。确认后我会逐步执行，每次运行后自动诊断，必要时修订模型并在关键处请你确认。", final=True)

def _assumptions(st):
    A = []; f = st["params_flat"]
    A.append(dict(id="A1", text=f"案例预设 {st['card']['preset']} 的设备/网络/天气参数（合成+公开资料）", src="案例假设"))
    A.append(dict(id="A2", text="单日 24h 代表日；跨日效应、设备启停、投资折现未建模", src="建模假设"))
    if st["topic"] == "heat_recovery":
        A.append(dict(id="A3", text=f"售热价格 {f.get('q_price')} 元/MWh_th；末端 {f.get('q_terminal')}；管线 {f.get('q_pipe')} km", src=_qsrc(st, "q_price")))
        A.append(dict(id="A4", text=f"投资 {f.get('q_capex')} 万元/MW_th（假设）；供暖季 120 天", src=_qsrc(st, "q_capex")))
    else:
        A.append(dict(id="A3", text=f"DR {'硬承诺' if f.get('q_firm') else '尽力响应'}，请求 {f.get('q_dr')} MW（19–22 时），补偿 2000 元/MWh；热安全上限 {f.get('q_tallow')}°C", src=_qsrc(st, "q_firm")))
    return A

def _qsrc(st, qid):
    q = next((x for x in st["questions"] if x["id"] == qid), {}); return (q.get("source") or {}).get("tag", "默认值")

def _apply_to_workbench(s, st, why):
    """把研究模型写入会话场景（参数表/拓扑同步），参数来源带消息引用。"""
    sc = _model(st); s.state["scenario"] = sc; s.state["results"] = {}
    s.state["origin"] = dict(kind="preset", name=st["card"]["preset"]); s.state["params_confirmed"] = True
    ps = {}
    for path, src in st["param_src"].items():
        for p in _expand(sc, path): ps[p] = dict(tag=src["tag"], note=src["note"], msg_ref=src.get("msg"))
    s.state["param_src"] = ps
    st["_snap"] = json.dumps(sc.model_dump(), sort_keys=True, default=str)
    try:
        from ..tools.sim_tools import _art
        with open(_art(s, "scenario.json"), "w") as f: f.write(sc.model_dump_json(indent=2))
    except Exception: pass

def _expand(sc, path):
    if path.startswith("study."): return []
    if "*" not in path: return [path]
    a, b = path.split("*", 1); n = len(EX._resolve(sc, a.rstrip(".").split(".")) [0][2])
    return [f"{a}{i}{b}" for i in range(n)]

def _sync_ui_edits(s, st):
    """界面（参数表/拓扑）修改 → 研究上下文：以编辑后模型为新基准继续对话。"""
    if not st or "_snap" not in st or "scenario" not in s.state: return
    snap = json.dumps(s.state["scenario"].model_dump(), sort_keys=True, default=str)
    if snap == st["_snap"]: return
    cur = json.loads(snap)   # JSON 往返归一化：int 键（如 bus_region）→ str，避免伪差异挤掉真实修改
    old = json.loads(st["_snap"]); diffs = []
    def walk(a, b, p=""):
        if isinstance(a, dict) and isinstance(b, dict):
            for k in sorted(set(a) | set(b), key=str): walk(a.get(k), b.get(k), f"{p}.{k}" if p else k)
        elif isinstance(a, list) and isinstance(b, list) and len(a) == len(b) and a and isinstance(a[0], (dict, list)):
            for i, (x, y) in enumerate(zip(a, b)): walk(x, y, f"{p}.{i}")
        elif a != b: diffs.append((p, a, b))
    walk(old, cur)
    st["base_sc"] = cur; st["model_mods"] = {}; st["_snap"] = snap
    for p, a, b in diffs[:20]:
        st["param_src"][p] = dict(tag="用户指定", note=f"用户在界面修改：{str(a)[:30]} → {str(b)[:30]}（{_now()}）", msg=None)
    st.setdefault("ui_edits", []).append(dict(t=_now(), diffs=[dict(path=p, old=str(a)[:40], new=str(b)[:40]) for p, a, b in diffs[:20]]))
    _tl(st, "sync", f"同步界面编辑 {len(diffs)} 处（后续实验以编辑后模型为基准）：" + "；".join(f"{p}: {str(a)[:12]}→{str(b)[:12]}" for p, a, b in diffs[:4]))
    msg = "🔄 检测到你在界面修改了模型：" + "；".join(f"`{p}` {str(a)[:16]} → **{str(b)[:16]}**" for p, a, b in diffs[:6]) + (" …" if len(diffs) > 6 else "") + "。后续分析基于编辑后的模型。"
    s.messages.append({"role": "system", "content": "[研究上下文同步] " + msg})
    yield dict(type="message", content=msg)

# ---------------- ③ 计划编辑 ----------------
def edit_plan(s, edits: dict):
    st = get(s)
    for e in edits.get("steps", []):
        p = next((x for x in st["plan"] if x["id"] == e["id"]), None)
        if not p or p["status"] != "pending": continue
        if "enabled" in e: p["enabled"] = bool(e["enabled"])
        if e.get("values") and p["kind"] == "sensitivity":
            key = next(iter(p["variants"][0]["mods"])) if p["variants"] else None
            extra = {k: v for k, v in p["variants"][0]["mods"].items() if k != key}
            p["variants"] = [dict(label=f"{key.split('.')[-1]}={v:g}", mods={key: float(v), **extra}) for v in e["values"]]
    _tl(st, "plan", "用户修改研究计划：" + json.dumps(edits, ensure_ascii=False)[:120])
    return public(st)

# ---------------- ④ 执行 · 诊断 · 修订 ----------------
def execute(s):
    st = get(s)
    if st["state"] == "plan": _tl(st, "plan", "用户批准研究计划，开始执行"); st["state"] = "execute"
    elif st["state"] not in ("execute",): return
    base = _model(st)
    for p in st["plan"]:
        if p["status"] != "pending": continue
        if not p["enabled"]: p["status"] = "skipped"; continue
        p["status"] = "running"; _tl(st, "run", f"开始 {p['id']} {p['title']}", p["id"], p["why"])
        yield dict(type="progress", step=p["id"], title=p["title"], why=p["why"]); yield _ev_study(st)
        if p["kind"] == "check":
            yield from _check_step(s, st, p); continue
        for v in p["variants"]:
            r = EX.run_variant(st, base, v["label"], v["mods"], p["why"], p["id"], s.artifact_dir); r["role"] = "variant"; p["runs"].append(r["id"])
            yield dict(type="run", run=_brief(r))
            if p.get("with_baseline"):
                bm = dict(v["mods"]); bm.update({"__remove_heat__": 1} if st["topic"] == "heat_recovery" else {"__no_dr__": 1})
                rb = EX.run_variant(st, base, v["label"] + "（对应基线）", bm, "同工况基线，用于公平比较", p["id"], s.artifact_dir); rb["role"] = "baseline_pair"; p["runs"].append(rb["id"])
        runs = [st["runs"][x] for x in p["runs"]]
        p["status"] = "failed" if all(r["status"] != "optimal" for r in runs) else "done"
        p["diag"] = _diag_summary(runs)
        _tl(st, "diagnose", f"{p['id']} 诊断：" + p["diag"], p["id"])
        yield _ev_study(st)
        stop = yield from _decide(s, st, p, runs)
        if stop: return
        base = _model(st)
    yield from conclude(s)

def _brief(r): return dict(id=r["id"], label=r["label"], status=r["status"], cost=r.get("kpis", {}).get("cost_cny"), worst=DG.worst(r["findings"]))

def _diag_summary(runs):
    n = {"error": 0, "warn": 0}
    for r in runs:
        for f in r["findings"]:
            if f["level"] in n: n[f["level"]] += 1
    bad = [f["title"] for r in runs for f in r["findings"] if f["level"] in ("error", "warn")]
    return f"{len(runs)} 次运行，错误 {n['error']}、警告 {n['warn']}" + (f"（{'；'.join(dict.fromkeys(bad))[:120]}）" if bad else "，全部检查通过")

def _insert_after(st, pid, step):
    i = next(i for i, x in enumerate(st["plan"]) if x["id"] == pid); st["plan"].insert(i + 1, step)

def _new_step(id, kind, title, why, variants, by="diagnose", **kw):
    return dict(id=id, kind=kind, title=title, why=why, variants=variants, status="pending", runs=[], added_by=by, enabled=True, **kw)

def _decide(s, st, p, runs):
    """诊断 → 决策：不可行则定位原因并提出修订（检查点）；异常则追加实验。返回 True 表示暂停等待用户。"""
    ids = [x["id"] for x in st["plan"]]
    main_like = p["kind"] in ("main", "revised")
    failed = [r for r in runs if r["status"] != "optimal"]
    if main_like and failed and st["iter"]["revisions"] < st["iter"]["cap"]:
        r = failed[0]; base = _base(st)
        yield dict(type="progress", step=p["id"], title="不可行原因分析：逐项松弛关键约束", why="定位是哪条假设导致不可行")
        ex = DG.explain_infeasible(base, {**st["model_mods"], **r["mods"]})
        r["infeasibility"] = ex
        r["findings"].append(DG.F("INFEAS_CAUSE", "error", "不可行原因定位", f"{ex['cause']}；可恢复可行的松弛：{'、'.join(ex['restoring']) or '无'}",
                                  dict(tests=ex["tests"])))
        _tl(st, "diagnose", f"{r['id']} 不可行 → 松弛试探：" + "；".join(f"{t['relax']}:{'✓' if t['feasible'] else '✗' if t['feasible'] is False else '—'}" for t in ex["tests"]), p["id"],
            "工程近似 IIS：哪条约束放宽后恢复可行，哪条就是瓶颈")
        cands = []
        if st["topic"] == "heatwave_dr" and any(t["key"] == "dr_soft" and t["feasible"] for t in ex["tests"]):
            yield dict(type="progress", step=p["id"], title="二分搜索可保证的硬承诺量", why="在保持热安全硬约束的前提下找最大可承诺削峰功率")
            firm = DG.find_firm_dr(base, st["model_mods"])
            st["firm_dr"] = dict(firm, requested_mw=st["params_flat"].get("q_dr", 40.0), cause=ex["cause"], failed_run=r["id"])
            cands.append(dict(id="adopt_firm", label=f"将硬承诺调整为可保证的 {firm['firm_mw']:g} MW 并重新仿真（推荐）", mods={"dr_events.0.request_mw": firm["firm_mw"]}))
            cands.append(dict(id="adopt_soft", label="保持 40 MW 请求，但改为尽力响应", mods={"dr_events.0.mandatory": False}))
        else:
            for t in ex["tests"]:
                if t["feasible"]:
                    rel = next(x for x in DG.RELAX if x[0] == t["key"]); cands.append(dict(id="relax_" + t["key"], label=f"采纳松弛：{t['relax']}", mods=rel[2]))
        cands.append(dict(id="stop", label="保持原假设，不修订（结论将标注为不可行）", mods=None))
        rec = cands[0]["id"]
        d = LB.call("decide_next", "你是仿真研究助手，根据不可行诊断选择修订方案。", dict(diagnosis=ex, candidates=[dict(id=c["id"], label=c["label"]) for c in cands]))
        why = (d or {}).get("rationale") or f"松弛试探显示“{'、'.join(ex['restoring'])}”可恢复可行；优先保留用户的“硬约束保障”语义，只调整承诺量。"
        if d and d.get("choice") in [c["id"] for c in cands]: rec = d["choice"]
        k = dict(id=f"K{len(st['checkpoints']) + 1}", step=p["id"], run=r["id"], title=f"{p['id']} 不可行：是否修订模型？", detail=ex["cause"], candidates=cands, recommend=rec, why=why, status="open")
        st["checkpoints"].append(k); st["state"] = "checkpoint"
        _tl(st, "checkpoint", f"检查点 {k['id']}：{k['title']}（建议：{next(c['label'] for c in cands if c['id'] == rec)}）", p["id"], why)
        yield _ev_study(st)
        yield dict(type="study_card", card=dict(kind="checkpoint", checkpoint=k))
        yield _say(s, f"🩺 **诊断**：{r['id']}（{r['label']}）**不可行**。原因定位：{ex['cause']}。\n\n松弛试探：" +
                   "；".join(f"{t['relax']} {'✅可行' if t['feasible'] else '❌仍不可行' if t['feasible'] is False else '—'}" for t in ex["tests"]) +
                   (f"\n\n二分求解：硬承诺 **{st['firm_dr']['firm_mw']:g} MW** 可行、{st['firm_dr']['upper_mw']:g} MW 不可行。" if st.get("firm_dr") else "") +
                   f"\n\n👉 建议：{next(c['label'] for c in cands if c['id'] == rec)}。请在检查点卡片中确认。", final=True)
        if st.get("auto_revise"):
            yield from checkpoint(s, k["id"], rec); return True
        return True
    ok = [r for r in runs if r["status"] == "optimal" and r.get("role") != "baseline_pair"]
    if main_like and ok:
        codes = {f["code"] for f in ok[-1]["findings"]}
        if "THERMAL_EDGE" in codes and "P2m" not in ids:
            st["plan"].insert(next(i for i, x in enumerate(st["plan"]) if x["id"] == p["id"]) + 1,
                              _new_step("P2m", "check_run", "裕度复核：热安全上限下调 1 K", "诊断发现入口温度贴着允许上限（零裕度），验证结论对 1 K 安全裕度是否稳健",
                                        [dict(label="允许上限 −1K", mods={"data_centers.*.thermal.t_allow_max_c": {"op": "add", "value": -1.0}})]))
            _tl(st, "revise", "诊断 THERMAL_EDGE → 追加实验 P2m（裕度复核）", p["id"], "零裕度结论需要验证")
            yield _say(s, "🩺 诊断：主方案入口温度**贴着允许上限**运行（裕度 0 K）。我追加了实验 **P2m 裕度复核（上限 −1 K）** 来检验结论稳健性。")
        if "HEAT_DEMAND_CAP" in codes and "P2b" not in ids:
            _insert_after(st, p["id"], _new_step("P2b", "check_run", "验证：热泵容量 +50% 能否增收", "诊断发现供热量已达热网可接纳上限，验证扩容是否无益（避免过度投资）",
                                                 [dict(label="热泵 ×1.5", mods={"data_centers.*.thermal.hp_cap_mw_th": {"op": "mul", "value": 1.5}})]))
            _tl(st, "revise", "诊断 HEAT_DEMAND_CAP → 追加实验 P2b（热泵扩容验证）", p["id"], "供热受需求上限约束时扩容可能无益")
            yield _say(s, "🩺 诊断：供热量已达到**热网可接纳上限**（紧约束）。追加实验 **P2b：热泵容量 +50%**，验证扩容是否还有收益。")
    if p["kind"] == "check_run" and ok and p["id"] == "P2b":
        m = TP.main_run(st)
        if m: ok[-1]["findings"].append(DG.F("HP_EXPANSION", "info", "热泵扩容验证", f"扩容后日成本 {ok[-1]['kpis']['cost_cny']:,.0f} vs 主方案 {m['kpis']['cost_cny']:,.0f}，差 {m['kpis']['cost_cny'] - ok[-1]['kpis']['cost_cny']:,.0f} 元/日", {}))
    return False

def checkpoint(s, kid, choice):
    st = get(s); k = next((x for x in st["checkpoints"] if x["id"] == kid and x["status"] == "open"), None) or next((x for x in st["checkpoints"] if x["status"] == "open"), None)
    if not k: yield _say(s, "没有待确认的检查点。", final=True); return
    if choice in ("adopt", "采纳", "ok", None): choice = k["recommend"]
    c = next((x for x in k["candidates"] if x["id"] == choice), None) or next(x for x in k["candidates"] if x["id"] == k["recommend"])
    k["status"] = "resolved"; k["choice"] = c["id"]
    if c["mods"] is None:
        _tl(st, "checkpoint", f"{k['id']} 用户选择不修订", k["step"]); st["state"] = "execute"
        yield _say(s, "好的，保持原假设。继续执行其余实验。"); yield from execute(s); return
    st["iter"]["revisions"] += 1
    st["model_mods"].update(c["mods"])
    for path, v in c["mods"].items():
        st["param_src"][path] = dict(tag="智能体推断", note=f"诊断修订 {k['id']}（用户确认）：{c['label']}；依据 {k['run']} 不可行原因：{k['detail']}", msg=dict(idx=len(st["msgs"]) - 1, quote=st["msgs"][-1]["text"][:60]) if st["msgs"] else None)
    st["revisions"].append(dict(id=f"V{len(st['revisions']) + 1}", checkpoint=k["id"], label=c["label"], mods=c["mods"], from_run=k["run"], t=_now()))
    st["assumption_list"] = _assumptions(st) + [dict(id="A5", text=f"修订：{c['label']}", src="诊断修订（用户确认）")]
    _apply_to_workbench(s, st, "诊断修订")
    sid = "P2r" if "P2r" not in [x["id"] for x in st["plan"]] else f"P2r{st['iter']['revisions']}"
    _insert_after(st, k["step"], _new_step(sid, "revised", "修订后主方案（重新仿真）", f"采纳 {k['id']}：{c['label']}", [dict(label="修订后主方案", mods={})], by="revise"))
    _tl(st, "revise", f"采纳 {k['id']}：{c['label']} → 追加 {sid} 重新仿真（修订 {st['iter']['revisions']}/{st['iter']['cap']}）", k["step"])
    st["state"] = "execute"
    yield _say(s, f"✅ 已采纳修订：{c['label']}。参数表中对应参数已标注为“诊断修订”来源。开始重新仿真 {sid}。")
    yield from execute(s)

def _check_step(s, st, p):
    from ..tools import sdco_engine as eng
    m = TP.main_run(st)
    if not m or "_r" not in m: p["status"] = "failed"; p["diag"] = "主方案无可行解，跳过校核"; return
    try:
        ac = eng.ac_check(m["_sc"], m["_r"]); ok = ac["converged"] and 0.94 <= ac["vmin_pu"] and ac["vmax_pu"] <= 1.06 and ac["max_branch_loading_pct"] <= 100
        f = DG.F("AC_CHECK", "ok" if ok else "warn", "交流潮流校核" + ("通过" if ok else "存在越限"),
                 f"时刻 {ac.get('hour')}：电压 {ac['vmin_pu']:.3f}–{ac['vmax_pu']:.3f} pu，最大支路负载 {ac['max_branch_loading_pct']:.1f}%", {k: ac[k] for k in ("vmin_pu", "vmax_pu", "max_branch_loading_pct", "converged")})
    except Exception as e: f = DG.F("AC_CHECK", "warn", "交流校核失败", str(e)[:200])
    m["findings"].append(f); p["checks"] = [f]
    th = [x for x in m["findings"] if x["code"].startswith("THERMAL") or x["code"] in ("PUE_RANGE", "BALANCE")]
    p["checks"] += th; p["status"] = "done"; p["runs"] = [m["id"]]
    p["diag"] = f["title"] + "；" + "；".join(x["title"] for x in th)
    _tl(st, "diagnose", f"{p['id']} {p['diag']}", p["id"]); yield _ev_study(st)

# ---------------- ⑤ 结论 + ⑥ 沉淀 ----------------
def conclude(s):
    st = get(s); st["state"] = "conclude"
    st["conclusions"] = TP.conclusions(st)
    n = LB.call("narrate_conclusions", "为已计算好的工程结论写简洁中文解读，只能使用给出的数字。", [dict(id=c["id"], text=c["text"], evidence=c["evidence"]) for c in st["conclusions"]])
    for it in (n or {}).get("items", []):
        c = next((x for x in st["conclusions"] if x["id"] == it.get("id")), None)
        if c: c["narrative"] = it.get("narrative")
    _tl(st, "conclude", f"形成 {len(st['conclusions'])} 条证据化结论")
    st["sediment"] = _sediment_proposals(st)
    _tl(st, "sediment", f"提议沉淀 {len(st['sediment'])} 条知识（待用户确认）")
    st["state"] = "done"
    try:
        md = report_md(s); _write(s, "study_report.md", md); _write(s, "study_report.html", report_html(md))
    except Exception as e: print("[research] report", e)
    yield _ev_study(st)
    yield dict(type="study_card", card=dict(kind="conclusions", conclusions=st["conclusions"], runs={k: _brief(v) for k, v in st["runs"].items()}))
    yield dict(type="study_card", card=dict(kind="sediment", items=st["sediment"]))
    yield _say(s, "✅ 研究完成。结论（每条附证据链、置信度与假设依赖，点击 R 编号可查看运行）：\n\n" + "\n".join(f"- **{c['id']}**（置信度 {c['confidence']}）{c['text']}" for c in st["conclusions"])
               + "\n\n可以继续追问“**为什么**…”或“**如果**…会怎样”，我会基于模型重算并给出变化量。", final=True)

def _sediment_proposals(st):
    P = []; f = st["params_flat"]; m = TP.main_run(st)
    P.append(dict(id="S1", kind="方法卡", status="proposed", card=dict(title=f"研究流程：{st['card']['title']}", task_type="研究方法",
                  keywords=" ".join(["研究", st["topic"], "中卫", *st["card"]["scenarios"]]), steps=[f"{p['id']} {p['title']}：{p['why']}" for p in st["plan"] if p["status"] in ("done", "failed")],
                  params=dict(preset=st["card"]["preset"], **{k: v for k, v in f.items()}), checks=sorted({x["code"] for r in st["runs"].values() for x in r["findings"]}),
                  example=st["question"])))
    for c in st["conclusions"][:4]:
        if c["confidence"] in ("高", "中") and c["evidence"]:
            P.append(dict(id=f"S{len(P)+1}", kind="经验", status="proposed", card=dict(title=f"经验：{re.sub(r'[*]', '', c['text'])[:28]}", task_type="研究经验",
                          keywords=f"{st['topic']} 中卫 {' '.join(st['card']['scenarios'][:3])}", steps=[c["text"]], params=dict(evidence=[e for e in c["evidence"] if e], firm_dr=st.get("firm_dr", {}).get("firm_mw")),
                          checks=c.get("assumptions", []), example=f"来源研究：{st['question']}（{st['id']}）")))
    if st.get("firm_dr"):
        P.append(dict(id=f"S{len(P)+1}", kind="经验", status="proposed", card=dict(title="经验：热浪日 DR 硬承诺需先校核热安全可承诺上限", task_type="研究经验", keywords="热浪 需求响应 硬承诺 不可行 二分 中卫 蓄冷",
                      steps=[f"请求 {st['firm_dr']['requested_mw']:g} MW 硬承诺不可行，可保证 {st['firm_dr']['firm_mw']:g} MW", "方法：松弛试探定位 → 二分搜索最大可承诺量"],
                      params=dict(firm_mw=st["firm_dr"]["firm_mw"]), checks=["INFEASIBLE", "INFEAS_CAUSE"], example=st["question"])))
    return P

def sediment(s, ids):
    st = get(s); from .. import knowledge as kb; saved = []
    for p in st["sediment"]:
        if p["id"] in ids and p["status"] == "proposed":
            c = kb.save_card(p["card"]); p["status"] = "saved"; p["card_id"] = c["id"]; saved.append(p["card"]["title"])
    _tl(st, "sediment", f"用户确认沉淀：{'、'.join(saved) or '无'}")
    yield _ev_study(st); yield _say(s, f"🧠 已沉淀到知识库/技能卡：{'、'.join(saved) or '（无）'}。后续类似研究在形式化阶段会自动检索并显示“参考了哪些经验”。", final=True)

# ---------------- 追问：为什么 / 如果 ----------------
def why(s, text):
    st = get(s); m = TP.main_run(st); b = next(iter(TP._step_runs(st, "P1")), None)
    cid = re.search(r"C\d+", text)
    c = next((x for x in st["conclusions"] if cid and x["id"] == cid.group(0)), st["conclusions"][0] if st["conclusions"] else None)
    if not m: yield _say(s, "主方案还没有可行解，暂无法解释。", final=True); return
    L = [f"**解释 {c['id'] if c else ''}**：{c['text'] if c else ''}", "", "**① 紧约束与影子价格（{}）**：".format(m["id"])]
    for x in m.get("binding", [])[:4]:
        L.append(f"- {x['group']}：{x['n_binding']}/{x['n']} 条起作用，最大影子价格 {x['dual_max']} 元/单位 — 放宽 1 单位可改变目标约 {abs(x['dual_max'])} 元")
    if b and b.get("cost_terms") and m.get("cost_terms"):
        L.append(f"\n**② 收益归因（目标函数逐项，{b['id']} → {m['id']}，元/日）**：")
        d = {k: round(m["cost_terms"].get(k, 0) - b["cost_terms"].get(k, 0), 0) for k in set(b["cost_terms"]) | set(m["cost_terms"])}
        CN = dict(grid_purchase="购电", export_revenue="售电(负=收入)", carbon="碳成本", heat_revenue="售热(负=收入)", dr_revenue="DR 收入(负=收入)", thermal_penalty="超推荐温度惩罚", storage_degradation="储能损耗", curtail_penalty="弃电惩罚")
        for k, v in sorted(d.items(), key=lambda x: x[1]):
            if abs(v) >= 1: L.append(f"- {CN.get(k, k)}：{v:+,.0f}")
    if c and c.get("sensitivity"):
        L.append(f"\n**③ 敏感性**：{c['sensitivity']['param']} " + "、".join(f"{p['x']:g}→{p['y']:,.0f}" for p in c["sensitivity"]["points"]))
    if st.get("firm_dr") and ("不可行" in text or "承诺" in text or "DR" in text or "响应" in text):
        L.append(f"\n**④ 不可行原因**：{st['firm_dr']['cause']}（{st['firm_dr']['failed_run']} 的松弛试探）。")
    L.append("\n> 依据均来自本研究运行结果（影子价格为 LP 对偶值）。")
    _tl(st, "why", "回答追问：" + text[:40])
    yield _say(s, "\n".join(L), final=True)

def parse_whatif(st, text):
    m = {}; t = text
    if x := re.search(r"(?:热价|售热价)\D{0,6}(\d+(?:\.\d+)?)", t): m["heat_network.price_cny_mwh_th"] = float(x.group(1))
    if x := re.search(r"(?:温度|气温|热浪)?\D{0,6}(?:再|升高|高|增加|上升)\s*(\d+(?:\.\d+)?)\s*(?:°C|℃|度|K)", t): m.update(TP.T_ADD(float(x.group(1))))
    elif x := re.search(r"(?:降低|低|下降)\s*(\d+(?:\.\d+)?)\s*(?:°C|℃|度|K)", t): m.update(TP.T_ADD(-float(x.group(1))))
    if "蓄冷" in t:
        if x := re.search(r"(\d+(?:\.\d+)?)\s*倍", t): f = float(x.group(1))
        elif "翻倍" in t or "加倍" in t: f = 2.0
        elif any(k in t for k in ["没有", "取消", "去掉"]): f = 0.0
        else: f = 1.5
        m["data_centers.*.thermal.tes_mwh_th"] = {"op": "mul", "value": f}; m["data_centers.*.thermal.tes_p_mw_th"] = {"op": "mul", "value": f}
    if x := re.search(r"(?:削峰|DR|需求响应|承诺)\D{0,6}(\d+(?:\.\d+)?)\s*MW", t, re.I): m["dr_events.0.request_mw"] = float(x.group(1))
    if "尽力" in t: m["dr_events.0.mandatory"] = False
    for k, v in (("地暖", "floor"), ("散热器", "radiator"), ("一次网", "primary")):
        if k in t: m["heat_network.terminal_type"] = v
    if x := re.search(r"(\d+(?:\.\d+)?)\s*(?:km|公里)", t, re.I): m["heat_network.pipe_length_km"] = float(x.group(1))
    if "热泵" in t:
        if x := re.search(r"(\d+(?:\.\d+)?)\s*倍", t): m["data_centers.*.thermal.hp_cap_mw_th"] = {"op": "mul", "value": float(x.group(1))}
        elif "翻倍" in t: m["data_centers.*.thermal.hp_cap_mw_th"] = {"op": "mul", "value": 2.0}
    if x := re.search(r"(?:上限|允许)\D{0,6}(\d+(?:\.\d+)?)\s*(?:°C|℃|度)", t): m["data_centers.*.thermal.t_allow_max_c"] = float(x.group(1))
    if x := re.search(r"碳价\D{0,4}(\d+(?:\.\d+)?)", t): m["carbon_price_cny_t"] = float(x.group(1))
    return m

def whatif(s, text):
    st = get(s); mods = parse_whatif(st, text); m = TP.main_run(st)
    if not mods:
        yield _say(s, "我没识别出要改的参数。可以这样问：“如果热价降到 80 会怎样”“如果热浪再高 2 度会怎样”“如果蓄冷翻倍会怎样”“如果削峰 30 MW 会怎样”“如果改成地暖会怎样”。", final=True); return
    base = _model(st); sid = f"W{len(st['whatifs']) + 1}"
    yield dict(type="progress", step=sid, title="What-if：" + EX.describe_mods(mods), why="修改模型并重新仿真，与主方案对比")
    r = EX.run_variant(st, base, f"What-if {sid}", mods, text, sid, s.artifact_dir); r["role"] = "variant"
    bm = dict(mods); bm.update({"__remove_heat__": 1} if st["topic"] == "heat_recovery" else {"__no_dr__": 1})
    rb = EX.run_variant(st, base, f"What-if {sid}（对应基线）", bm, "同工况基线", sid, s.artifact_dir); rb["role"] = "baseline_pair"
    b0 = next(iter(TP._step_runs(st, "P1")), None)
    W = dict(id=sid, question=text, mods=mods, mods_desc=EX.describe_mods(mods), run=r["id"], baseline_run=rb["id"], ref_run=m["id"] if m else None, status=r["status"])
    if r["status"] == "optimal" and m:
        keys = ["cost_cny", "tin_max_c", "thermal_margin_k", "pue_avg", "heat_delivered_mwh", "heat_verdict", "terminal_margin_k", "dr_delivered_mwh", "dr_revenue_cny", "emissions_tco2"]
        rows = [dict(k=k, name=EX.KPI_CN.get(k, k), before=m["kpis"].get(k), after=r["kpis"].get(k)) for k in keys if k in m["kpis"] or k in r["kpis"]]
        for x in rows: x["delta"] = round(x["after"] - x["before"], 3) if isinstance(x["after"], (int, float)) and isinstance(x["before"], (int, float)) else None
        W["rows"] = rows
        if rb["status"] == "optimal" and b0:
            v0 = b0["kpis"]["cost_cny"] - m["kpis"]["cost_cny"]; v1 = rb["kpis"]["cost_cny"] - r["kpis"]["cost_cny"]
            W["value"] = dict(before=round(v0, 0), after=round(v1, 0), label=st["card"]["value_metric"])
        txt = f"🔁 **What-if {sid}**：{W['mods_desc']}（{r['id']} vs 主方案 {m['id']}）\n\n| 指标 | 主方案 | What-if | 变化 |\n|---|---|---|---|\n" + "\n".join(
            f"| {x['name']} | {_f(x['before'])} | {_f(x['after'])} | {_f(x['delta'], sign=True) if x['delta'] is not None else ''} |" for x in rows)
        if W.get("value"): txt += f"\n\n**{W['value']['label']}**：{W['value']['before']:,.0f} → **{W['value']['after']:,.0f} 元/日**（同工况基线 {rb['id']}）。"
        bad = [f["title"] for f in r["findings"] if f["level"] in ("warn", "error")]
        if bad: txt += "\n\n🩺 诊断：" + "；".join(bad)
    else:
        txt = f"🔁 **What-if {sid}**：{W['mods_desc']} → **{r['status']}**。{r.get('error', '')[:160]}"
        if r["status"] == "infeasible":
            ex = DG.explain_infeasible(base, mods); W["infeasibility"] = ex
            txt += f"\n\n🩺 原因定位：{ex['cause']}；可恢复可行：{'、'.join(ex['restoring']) or '无'}。"
    st["whatifs"].append(W); _tl(st, "whatif", f"{sid} {W['mods_desc']} → {r['status']}", sid, "用户追问 what-if")
    try: md = report_md(s); _write(s, "study_report.md", md); _write(s, "study_report.html", report_html(md))
    except Exception: pass
    yield _ev_study(st); yield dict(type="study_card", card=dict(kind="whatif", whatif=W)); yield _say(s, txt, final=True)

def _f(v, sign=False):
    if isinstance(v, (int, float)):
        return (f"{v:+,.2f}" if sign else f"{v:,.2f}") if abs(v) < 1000 else (f"{v:+,.0f}" if sign else f"{v:,.0f}")
    return "—" if v is None else str(v)

# ---------------- 报告 ----------------
def _write(s, name, txt):
    os.makedirs(s.artifact_dir, exist_ok=True)
    with open(os.path.join(s.artifact_dir, name), "w", encoding="utf-8") as f: f.write(txt)
    if name not in s.artifacts: s.artifacts.append(name)

def report_md(s):
    st = get(s); c = st["card"]; L = [f"# 研究报告：{c['title']}", "", f"> 研究编号 {st['id']} · 生成于 {time.strftime('%Y-%m-%d %H:%M')}（UTC+8）· 模式：{public(st)['llm_mode']} · 默认数据为合成/案例数据", ""]
    L += ["## 1. 研究问题卡", f"**研究问题**：{c['research_question']}", "", "**决策变量**：" + "；".join(c["decision_variables"]), "", "**约束**：" + "；".join(c["constraints"]), "",
          "**评价指标**：" + "；".join(c["kpis"]), "", "**情景**：" + "；".join(c["scenarios"]), ""]
    if st["references"]: L += ["**参考经验**：" + "；".join(r["title"] for r in st["references"]), ""]
    L += ["## 2. 澄清与关键参数（可追溯来源）", "| 问题 | 取值 | 来源 | 依据 |", "|---|---|---|---|"]
    for q in st["questions"]:
        src = q.get("source", {}); L.append(f"| {q['q']} | {q.get('answer')} | {src.get('tag')} | {src.get('note', '')}" + (f"（消息 #{src['msg']['idx']}）" if src.get("msg") else "") + " |")
    L += ["", "**假设**："] + [f"- {a['id']}：{a['text']}（{a['src']}）" for a in st.get("assumption_list", [])]
    L += ["", "## 3. 研究计划与执行", "| 步骤 | 内容 | 状态 | 来源 | 诊断 |", "|---|---|---|---|---|"]
    for p in st["plan"]: L.append(f"| {p['id']} | {p['title']} | {p['status']} | {dict(plan='计划', diagnose='诊断追加', revise='修订', whatif='追问').get(p['added_by'], p['added_by'])} | {p.get('diag', '')} |")
    L += ["", "## 4. 运行清单", "| 运行 | 说明 | 修改 | 状态 | 日净成本(元) | 最高入口(°C) | 供热(MWh_th) | DR(MWh) |", "|---|---|---|---|---|---|---|---|"]
    for r in st["runs"].values():
        k = r.get("kpis", {}); L.append(f"| {r['id']} | {r['label']} | {r['mods_desc']} | {r['status']} | {_f(k.get('cost_cny'))} | {_f(k.get('tin_max_c'))} | {_f(k.get('heat_delivered_mwh'))} | {_f(k.get('dr_delivered_mwh'))} |")
    L += ["", "## 5. 诊断与修订"]
    for r in st["runs"].values():
        bad = [f for f in r["findings"] if f["level"] in ("error", "warn")]
        if bad: L.append(f"- **{r['id']} {r['label']}**：" + "；".join(f"[{f['level']}] {f['title']}：{f['detail'][:120]}" for f in bad))
    for v in st["revisions"]: L.append(f"- 修订 {v['id']}（检查点 {v['checkpoint']}，源自 {v['from_run']}）：{v['label']}")
    L += ["", "## 6. 结论（证据链）"]
    for c2 in st["conclusions"]:
        L.append(f"### {c2['id']}（置信度：{c2['confidence']}）"); L.append(c2["text"])
        if c2.get("narrative"): L.append(f"\n*解读*：{c2['narrative']}")
        L.append("\n证据：" + "；".join(f"{e.get('run')}·{e.get('label')}={_f(e.get('value'))}" for e in c2["evidence"] if e))
        if c2["binding"]: L.append("紧约束：" + "、".join(c2["binding"]))
        L.append("依赖假设：" + "、".join(c2["assumptions"])); L.append("")
    if st["whatifs"]:
        L += ["## 7. What-if 追问"]
        for w in st["whatifs"]:
            L.append(f"- **{w['id']}** “{w['question']}” → {w['mods_desc']}：{w['status']}" + (f"；{w['value']['label']} {w['value']['before']:,.0f} → {w['value']['after']:,.0f} 元/日" if w.get("value") else ""))
    L += ["", "## 8. 局限", "- 单日代表日 LP，未含设备启停整数约束与跨日储热；投资/运维为假设值。", "- 影子价格为 LP 对偶值，仅在当前基点附近有效。", "- 默认数据为合成/案例数据，需用项目实测数据替换。"]
    return "\n".join(L)

def report_html(md):
    vend = os.path.join(os.path.dirname(__file__), "..", "static", "vendor", "marked.min.js")
    js = open(vend, encoding="utf-8").read() if os.path.exists(vend) else ""
    return ("<!doctype html><html lang='zh-CN'><head><meta charset='utf-8'><title>研究报告</title><style>body{font-family:'Noto Sans CJK SC',sans-serif;max-width:1000px;margin:24px auto;padding:0 16px;line-height:1.6}"
            "table{border-collapse:collapse;font-size:13px}td,th{border:1px solid #ccc;padding:3px 6px}h1{color:#1f4e79}</style><script>" + js + "</script></head><body><div id='c'></div>"
            "<script id='md' type='text/markdown'>" + md.replace("</script", "<\\/script") + "</script><script>document.getElementById('c').innerHTML=marked.parse(document.getElementById('md').textContent)</script></body></html>")

def report_events(s):
    md = report_md(s); _write(s, "study_report.md", md); _write(s, "study_report.html", report_html(md))
    yield dict(type="study_card", card=dict(kind="report", files=["study_report.md", "study_report.html"]))
    yield _say(s, "📄 研究报告已生成：study_report.md / study_report.html（右侧「🔬 研究」可下载）。", final=True)
