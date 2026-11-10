"""研究编排器中的“寻优”分支：对话 → 目标规格卡（可编辑、展示数学表述）→ 求解（流式进度）→ 帕累托/方案卡 → 追问（再降 x% 碳要多花多少钱 / 为什么 / 查看方案）。
规格由 LLM 函数调用 submit_objective_spec 产生；Mock 或调用失败时用规则解析器（app/opt/nl.py）。"""
import json, queue, threading, re
from ..opt import nl, engine as E, schema as SC

def _clean(o): return json.loads(json.dumps(o, ensure_ascii=False, default=lambda v: float(v) if hasattr(v, "__float__") else str(v)))

def routes(s, text):
    t = text.strip()
    if t.startswith("【目标规格】"): return True
    if s.state.get("opt_result") and nl.followup(t): return True
    return nl.is_opt(t)

def spec_from_text(s, text):
    prev = s.state.get("opt_spec"); hint = None
    sc = s.state.get("scenario")
    if sc is not None:
        for kws, p in nl.SITES:
            if any(k.lower() in (sc.name or "").lower() for k in kws): hint = p
    from .. import settings
    if settings.get("LLM_MOCK", "0") != "1":
        try:
            from ..llm import get_llm
            sys_p = ("你是数据中心算-电-热-碳寻优助手。把用户需求翻译成目标规格，必须调用 submit_objective_spec。"
                     "区分硬约束（不低于/不超过/必须）与偏好（尽量/兼顾→作为目标或权重）。多个目标且未说明权重或优先级时用 pareto。"
                     f"上一轮规格：{json.dumps(prev, ensure_ascii=False) if prev else '无'}")
            r = get_llm().chat([{"role": "system", "content": sys_p}, {"role": "user", "content": text}],
                               [{"type": "function", "function": {"name": "submit_objective_spec", "description": "提交结构化目标规格", "parameters": SC.SPEC_SCHEMA}}])
            calls = [c for c in r.get("tool_calls", []) if c["name"] == "submit_objective_spec"]
            if calls:
                sp, err = SC.validate(calls[0]["arguments"], prev if prev and calls[0]["arguments"].get("preset") in (None, prev["preset"]) else None)
                return sp, ["由 LLM 函数调用 submit_objective_spec 生成"] + err, "LLM"
        except Exception as e:
            note = f"LLM 解析失败（{type(e).__name__}），改用规则解析"
            sp, notes = nl.parse(text, prev, hint); return sp, [note] + notes, "规则解析"
    sp, notes = nl.parse(text, prev, hint); return sp, notes, "规则解析(Mock)"

def _run_stream(spec):
    q = queue.Queue(); box = {}
    def work():
        try: box["r"] = E.run(spec, progress=lambda k, m: q.put(m))
        except Exception as e: box["e"] = e
        q.put(None)
    th = threading.Thread(target=work, daemon=True); th.start()
    while True:
        m = q.get()
        if m is None: break
        yield dict(type="progress", step="寻优", title=m, why="")
    th.join()
    if "e" in box: raise box["e"]
    return box["r"]

def _fmt(v, d=0):
    return f"{v:,.{d}f}" if isinstance(v, (int, float)) else "—"

def summary(r):
    sp = r["spec"]; L = [f"**寻优完成**（{r['runtime_s']} s，{sp['preset']}，{'全年 8760h' if sp['resolution'] in ('full', None) else str(sp['resolution']) + ' 个代表日 + 8760h 复核'}，碳因子={'逐时边际' if sp['carbon_basis'] == 'marginal' else '平均'}）"]
    rows = r["front"] or r["schemes"]
    L.append("| 方案 | 标记 | 年化总成本(万元) | 净碳排(t) | 绿电占比 | PUE | 新增容量 |"); L.append("|---|---|---|---|---|---|---|")
    TAG = {"cost_opt": "💰成本最优", "carbon_opt": "🌿碳最优", "knee": "⚖️折中(膝点)", "optimum": "⭐最优"}
    for p in rows:
        k = p["kpi"]; caps = "、".join(f"{E._capcn(n)}+{v:g}" for n, v in k["caps"].items()) or "—"
        L.append(f"| {p['label']} | {TAG.get(p.get('tag'), '')} | {_fmt(k['cost_total']/1e4)} | {_fmt(k['carbon_net_t'])} | {k['green_share']:.1%} | {k['pue']:.3f} | {caps} |")
    if r.get("baseline"): b = r["baseline"]["kpi"]; L.append(f"\n现状（不新增投资，仅优化运行）：年成本 {_fmt(b['cost_total']/1e4)} 万元，碳 {_fmt(b['carbon_net_t'])} t，绿电 {b['green_share']:.1%}")
    for p in r["schemes"]:
        L.append(f"\n**{p['label']} {TAG.get(p.get('tag'), '')}**：" + "；".join(p["why"]))
        if p.get("verify", {}).get("err"): L.append("  8760h 复核偏差：" + "，".join(f"{k} {v:+.1%}" for k, v in p["verify"]["err"].items()))
    if r["front"]: L.append("\n可以继续问：「再降10%碳要多花多少钱」「为什么选折中方案」「查看方案3」，或直接在目标卡里改约束后重算。")
    return "\n".join(L)

def chat_events(s, text):
    t = text.strip(); s.messages.append({"role": "user", "content": t})
    res = s.state.get("opt_result"); fu = nl.followup(t) if res else None
    if fu:
        kind, arg = fu
        if kind == "abate":
            yield dict(type="progress", step="寻优追问", title=f"再降 {arg:.0%} 碳：以{'膝点' if any(p.get('tag') == 'knee' for p in res['front']) else '当前最优'}为参考重新求解", why="min 成本 s.t. 碳 ≤ (1−x)·C_ref")
            a = _clean(E.abatement(res, arg))
            if not a.get("ok"): msg = f"⚠️ {a.get('msg')}"
            else:
                msg = (f"以 **{a['ref']['label']}**（碳 {_fmt(a['ref']['kpi']['carbon_net_t'])} t/年）为参考，再降 {arg:.0%} 到 ≤ {_fmt(a['target'])} t：\n\n"
                       f"- 年化总成本增加 **{_fmt(a['d_cost']/1e4, 1)} 万元/年**，减碳 {_fmt(a['d_carbon'])} t → 平均减排成本 **{_fmt(a['avg_mac'])} 元/tCO2**\n"
                       f"- 碳约束对偶值（再多减 1 t 的边际成本）≈ **{_fmt(a['marginal_mac'])} 元/tCO2**\n- 新方案新增容量：" +
                       ("、".join(f"{E._capcn(n)}+{v:g}" for n, v in a['scheme']['kpi']['caps'].items()) or "—") + f"（求解 {a['runtime_s']} s）")
            s.state["opt_abate"] = a; s.messages.append({"role": "assistant", "content": msg})
            yield dict(type="opt_card", card=dict(kind="abate", abate=a)); yield dict(type="message", content=msg); return
        pts = res["front"] or res["schemes"]
        lab = {"成本最优": "cost_opt", "碳最优": "carbon_opt", "折中": "knee", "膝点": "knee"}.get(arg)
        p = next((x for x in pts if x["label"] == arg or (lab and x.get("tag") == lab)), None)
        msg = f"**{p['label']}**：" + "；".join(p["why"]) if p else f"没有找到 {arg}"
        s.messages.append({"role": "assistant", "content": msg})
        if p: yield dict(type="opt_card", card=dict(kind="scheme", scheme=p))
        yield dict(type="message", content=msg); return
    if t.startswith("【目标规格】"):
        try: raw = json.loads(t[len("【目标规格】"):].strip())
        except Exception as e: yield dict(type="message", content=f"目标规格 JSON 解析失败：{e}"); return
        spec, err = SC.validate(raw); notes, by = ["界面编辑后的目标规格"] + err, "用户编辑"
    else:
        spec, notes, by = spec_from_text(s, t)
    s.state["opt_spec"] = spec
    yield dict(type="opt_card", card=_clean(dict(kind="spec", spec=spec, formulation=E.formulation(spec), notes=notes, by=by)))
    try: r = yield from _run_stream(spec)
    except Exception as e:
        msg = f"❌ 寻优失败：{type(e).__name__}: {e}"; s.messages.append({"role": "assistant", "content": msg}); yield dict(type="message", content=msg); return
    r = _clean(r); s.state["opt_result"] = r
    yield dict(type="opt_card", card=dict(kind="result", result=r))
    msg = summary(r); s.messages.append({"role": "assistant", "content": msg}); yield dict(type="message", content=msg)
