"""寻优工具（LLM 函数调用）：submit_objective_spec → run_optimization → query_abatement / explain_scheme。"""
from .base import tool, Session
from ..opt import engine as E, nl, schema as SC

@tool("submit_objective_spec", "提交结构化寻优目标规格（目标/硬约束/权重或优先级/帕累托轴/容量决策变量/碳因子口径/时间分辨率）。"
      "可只给 text（用户原话，由规则解析），或给 spec 字段。返回校验后的规格与数学表述。",
      {"type": "object", "properties": {"text": {"type": "string"}, "spec": SC.SPEC_SCHEMA}})
def submit_objective_spec(s: Session, text=None, spec=None):
    prev = s.state.get("opt_spec")
    if spec: sp, err = SC.validate(spec, prev); notes = err
    else: sp, notes = nl.parse(text or "", prev)
    s.state["opt_spec"] = sp
    return dict(ok=True, spec=sp, formulation=E.formulation(sp), notes=notes)

@tool("run_optimization", "按当前目标规格做全年（8760h 或代表日）容量规划+运行寻优；pareto 模式返回 ε-约束前沿并标注成本最优/碳最优/膝点。", {"type": "object", "properties": {}})
def run_optimization(s: Session):
    sp = s.state.get("opt_spec")
    if not sp: return dict(ok=False, error="请先 submit_objective_spec")
    from ..research.opt_flow import _clean, summary
    r = _clean(E.run(sp)); s.state["opt_result"] = r
    return dict(ok=True, summary=summary(r), n_points=len(r["front"]), runtime_s=r["runtime_s"],
                schemes=[dict(label=p["label"], tag=p.get("tag"), kpi={k: p["kpi"][k] for k in ("cost_total", "carbon_net_t", "green_share", "pue", "caps")}) for p in (r["front"] or r["schemes"])])

@tool("query_abatement", "追问：在参考方案基础上再降 pct（0-1）碳排放需多花多少钱（重新求解 + 对偶边际减排成本）。",
      {"type": "object", "properties": {"pct": {"type": "number"}, "ref": {"type": "string"}}, "required": ["pct"]})
def query_abatement(s: Session, pct=0.1, ref=None):
    r = s.state.get("opt_result")
    if not r: return dict(ok=False, error="请先 run_optimization")
    from ..research.opt_flow import _clean
    a = _clean(E.abatement(r, float(pct), ref)); return dict(ok=bool(a.get("ok")), **{k: v for k, v in a.items() if k != "ok"})

@tool("explain_scheme", "解释某个方案为何被选中（起作用约束/对偶值/触及上限/回收期）。", {"type": "object", "properties": {"label": {"type": "string"}}, "required": ["label"]})
def explain_scheme(s: Session, label):
    r = s.state.get("opt_result")
    if not r: return dict(ok=False, error="请先 run_optimization")
    p = next((x for x in (r["front"] or r["schemes"]) if x["label"] == label or x.get("tag") == label), None)
    return dict(ok=bool(p), why=p["why"] if p else None)
