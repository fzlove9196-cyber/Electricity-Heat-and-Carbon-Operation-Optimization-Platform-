"""研究模板（确定性）：问题卡、澄清问题、研究计划、结论计算。数字全部来自 run 结果。"""
from __future__ import annotations
import re
import numpy as np

T_ADD = lambda x: {"outdoor_temp_c": {"op": "add", "value": x}, "outdoor_temp_profiles.*": {"op": "add", "value": x}}

def detect(text: str) -> str | None:
    if any(k in text for k in ["余热", "供暖", "供热"]): return "heat_recovery"
    if any(k in text for k in ["热浪", "高温"]) and any(k in text for k in ["需求响应", "削峰", "DR", "响应"]): return "heatwave_dr"
    return None

def is_study_question(text: str) -> bool:
    return detect(text) is not None and any(k in text for k in ["值不值", "值得", "划算", "最优方案", "可行", "研究", "怎么", "如何", "方案", "看看", "评估", "能不能"])

# ---------------- 问题卡 + 澄清问题 ----------------
def formulate(topic: str, text: str) -> dict:
    if topic == "heat_recovery":
        card = dict(title="中卫数据中心集群冬季余热供暖经济性与可行性研究",
                    research_question="在中卫冬季（低风日）工况下，利用数据中心余热经热泵向城区集中供热，相比“不回收余热”是否带来净收益？在什么热价/末端条件下成立？",
                    decision_variables=["余热回收热泵逐时出力 q_hp(t)（MW_th）", "热网蓄热充放 / 调峰补热", "批处理算力时移与跨 DC 迁移", "储能充放电与外网购售电"],
                    constraints=["DC-OPF 节点功率平衡与线路限值", "机房 RC 热平衡、入口温度 18–32°C、温变率 ≤5 K/h", "冷机 N+1 可用冷量、自然冷却能力",
                                 "热泵容量 ≤ hp_cap、可回收余热 ≤ 60%×IT 发热", "热网逐时可接纳热负荷上限、管网热损", "末端供水温度（余热品位/热泵出水温度）"],
                    kpis=["日净成本（元/日）及相对不回收的节省", "供热量 MWh_th、售热收入", "供热抵扣碳排 tCO2", "余热热成本 元/GJ（对比参考热价 45 元/GJ）",
                          "末端温度裕度 K / 调峰补热量", "PUE", "简单投资回收期（若计入投资）"],
                    scenarios=["基线：不回收余热", "主方案：余热回收供暖", "敏感性：售热价格", "方案比较：供热末端类型", "压力测试：寒潮（室外 −8 K）"],
                    assumptions=["案例预设 zhongwei_winter_coupled_heat（合成+公开资料，见参数表来源）", "单日 24h 代表日，供暖季按 120 天折算", "热网需求曲线为给定可接纳负荷"],
                    preset="zhongwei_winter_coupled_heat", value_metric="相对不回收余热的日净成本节省")
        qs = [dict(id="q_terminal", q="热用户采用哪种供热末端？（决定余热品位是否够用）", path="heat_network.terminal_type", default="radiator",
                   options=[dict(v="floor", label="地暖 35–45°C"), dict(v="radiator", label="散热器 60–75°C（保守默认）"), dict(v="primary", label="城市一次网 70–110°C")],
                   kw={"地暖": "floor", "散热器": "radiator", "暖气片": "radiator", "一次网": "primary"}, why="末端温度决定能否直接换热/热泵 COP，是“值不值”的技术前提"),
              dict(id="q_pipe", q="数据中心到热用户的输热管线大约多长？", path="heat_network.pipe_length_km", default=5.0,
                   options=[dict(v=1.0, label="1 km（园区内）"), dict(v=5.0, label="5 km（城区边缘，默认）"), dict(v=10.0, label="10 km（远距离）")],
                   rx=r"(\d+(?:\.\d+)?)\s*(?:km|公里)", why="管线长度影响温降与热损"),
              dict(id="q_price", q="余热售热价格按多少计？（元/MWh_th）", path="heat_network.price_cny_mwh_th", default=120.0,
                   options=[dict(v=60.0, label="60（低价补贴型）"), dict(v=120.0, label="120（案例默认）"), dict(v=200.0, label="200（市场化热价）")],
                   rx=r"热价\D{0,4}(\d+(?:\.\d+)?)", why="直接决定售热收入"),
              dict(id="q_capex", q="“值不值”是否计入热泵/换热站投资？", path="study.capex_wan_per_mw", default=150.0,
                   options=[dict(v=0.0, label="只看运行收益"), dict(v=150.0, label="计入：150 万元/MW_th（假设，可改）")], why="决定能否给出回收期结论")]
    elif topic == "heatwave_dr":
        card = dict(title="中卫夏季热浪日：保障热安全前提下参与电网需求响应的最优方案",
                    research_question="热浪日（室外峰值约 39°C）晚高峰 19–22 时电网请求削峰，在入口温度不越限的前提下，数据中心集群最多能可靠响应多少？最优调度与收益如何？",
                    decision_variables=["DR 时段削减功率 dr(t)", "预冷/蓄冷罐充放冷（虚拟储冷）", "批处理时移与跨 DC 迁移", "冷机/自然冷却出力、储能"],
                    constraints=["入口温度 ≤ 允许上限（硬）、推荐上限软惩罚、温变率", "冷机 N+1 可用冷量（COP 随室外温度下降）", "DR 承诺量（硬承诺/尽力）",
                                 "批处理日能量守恒、迁移带宽", "DC-OPF 功率平衡与线路限值"],
                    kpis=["热安全：最高入口温度/裕度/违规数", "DR 实际响应 MWh 与可保证硬承诺 MW", "DR 收入与日净成本", "PUE 峰值", "蓄冷放冷量"],
                    scenarios=["基线：热浪日不参与 DR", "主方案：按请求参与 DR", "敏感性：削峰请求量", "方案比较：蓄冷罐容量", "压力测试：热浪再 +2°C"],
                    assumptions=["案例预设 zhongwei_heatwave_stress（合成热浪曲线 25–39°C）", "DR 补偿 2000 元/MWh、基线=无 DR 优化计划", "冷机 N+1 可用"],
                    preset="zhongwei_heatwave_stress", value_metric="DR 收益扣除热管理代价后的日净成本变化")
        qs = [dict(id="q_firm", q="需求响应是否必须足额（硬承诺，未足额视为违约）？", path="dr_events.0.mandatory", default=True,
                   options=[dict(v=True, label="必须足额（硬约束，默认：“保障”语义）"), dict(v=False, label="尽力响应（按实际结算）")],
                   kw={"必须": True, "足额": True, "尽力": False}, why="决定 DR 是硬约束还是软目标，直接影响可行性"),
              dict(id="q_dr", q="电网削峰请求量多大？（19–22 时，MW）", path="dr_events.0.request_mw", default=40.0,
                   options=[dict(v=20.0, label="20 MW"), dict(v=40.0, label="40 MW（案例默认）"), dict(v=60.0, label="60 MW")],
                   rx=r"(\d+(?:\.\d+)?)\s*MW", why="请求量越大越依赖热惯性/蓄冷"),
              dict(id="q_tallow", q="热安全标准（入口温度硬上限）？", path="data_centers.*.thermal.t_allow_max_c", default=32.0,
                   options=[dict(v=32.0, label="ASHRAE A1 允许 32°C（默认）"), dict(v=30.0, label="企业内控 30°C")], why="热安全硬约束的边界"),
              dict(id="q_wave", q="热浪强度按哪种？", path="study.wave_add_k", default=0.0,
                   options=[dict(v=0.0, label="案例热浪（峰值≈39°C）"), dict(v=2.0, label="极端：再 +2°C")], why="决定冷机 COP 与自然冷却可用性")]
    else:
        return None
    return _localize(topic, text, dict(card=card, questions=qs))

# 研究模式按地点关键词匹配案例预设（原先固定为中卫）。关键词 -> (预设名前缀, 中文地名)
SITE_KW = [(("韶关", "华南数谷"), "shaoguan", "韶关"), (("乌兰察布", "中金数据"), "ulanqab_cicdata", "乌兰察布"), (("世纪互联",), "ulanqab_21vianet", "乌兰察布(世纪互联)"),
           (("Odense", "odense", "欧登塞", "Meta", "丹麦"), "odense_meta", "欧登塞(Meta)"), (("临港",), "lingang", "上海临港"),
           (("芜湖",), "wuhu_telecom", "芜湖"), (("贵安", "华为云"), "guian_huawei", "贵安"), (("仁和", "浸没"), "renhe_alibaba", "杭州仁和"),
           (("和林格尔", "华电"), "helinger", "和林格尔")]

def resolve_preset(topic, text):
    """返回 (preset, 地名) 或 None：按地点关键词找同类研究可用的预设（余热→含热网+热泵；热浪DR→含 DR 事件，优先 heatwave/coldwave 日）。"""
    from ..scenario import list_presets, load_preset
    P = list_presets()
    for kws, prefix, cn in SITE_KW:
        if not any(k in text for k in kws): continue
        cands = [n for n in P if n.startswith(prefix)]
        def ok(n):
            sc = load_preset(n)
            if sc.thermal_mode != "coupled": return False
            if topic == "heat_recovery": return sc.heat_network is not None and any(d.thermal and d.thermal.hp_cap_mw_th > 0 for d in sc.data_centers)
            return bool(sc.dr_events)
        pref = (lambda n: (("winter" not in n) + ("coldwave" in n)) if topic == "heat_recovery" else (("heatwave" not in n) + 0))
        good = sorted([n for n in cands if ok(n)], key=pref)
        if good: return good[0], cn
    return None

def _localize(topic, text, F):
    r = resolve_preset(topic, text)
    if not r: return F
    preset, cn = r; card = F["card"]
    from ..scenario import load_preset
    sc = load_preset(preset)
    for k in ("title", "research_question"): card[k] = card[k].replace("中卫", cn)
    card["assumptions"] = [f"案例预设 {preset}（公开资料+真实气象，见参数表来源）"] + card["assumptions"][1:]
    card["preset"] = preset; card["site"] = cn
    if topic == "heatwave_dr" and sc.dr_events:
        ev = sc.dr_events[0]; tmax = max(max(v) for v in (sc.outdoor_temp_profiles.values() or [sc.outdoor_temp_c]))
        card["research_question"] = (f"{cn}热浪/高温日（室外峰值约 {tmax:.0f}°C）{ev.start}–{ev.end} 时电网请求削峰 {ev.request_mw:g} MW，在入口温度不越限的前提下，"
                                     "数据中心最多能可靠响应多少？最优调度与收益如何？")
        for q in F["questions"]:
            if q["id"] == "q_dr":
                q["q"] = f"电网削峰请求量多大？（{ev.start}–{ev.end} 时，MW）"; q["default"] = float(ev.request_mw)
                q["options"] = [dict(v=round(ev.request_mw*0.5, 1), label=f"{ev.request_mw*0.5:g} MW"), dict(v=float(ev.request_mw), label=f"{ev.request_mw:g} MW（案例默认）"),
                                dict(v=round(ev.request_mw*1.5, 1), label=f"{ev.request_mw*1.5:g} MW")]
    if topic == "heat_recovery" and sc.heat_network is not None:
        hn = sc.heat_network
        for q in F["questions"]:
            if q["id"] == "q_price":
                q["options"] = [dict(v=round(hn.price_cny_mwh_th*0.5, 1), label=f"{hn.price_cny_mwh_th*0.5:g}"), dict(v=float(hn.price_cny_mwh_th), label=f"{hn.price_cny_mwh_th:g}（案例默认）"),
                                dict(v=round(hn.price_cny_mwh_th*1.5, 1), label=f"{hn.price_cny_mwh_th*1.5:g}")]; q["default"] = float(hn.price_cny_mwh_th)
            if q["id"] == "q_pipe" and hn.pipe_length_km: q["default"] = float(hn.pipe_length_km)
            if q["id"] == "q_terminal" and hn.terminal_type: q["default"] = hn.terminal_type
    return F

def prefill(questions, text):
    """从用户原话中直接解析出的答案（带原文引用）。"""
    out = {}
    for q in questions:
        for k, v in (q.get("kw") or {}).items():
            if k in text: out[q["id"]] = (v, k); break
        if q["id"] not in out and q.get("rx") and (m := re.search(q["rx"], text, re.I)): out[q["id"]] = (float(m.group(1)), m.group(0))
    return out

def answers_to_mods(topic, params):
    mods = {}
    for qid, (path, v) in params.items():
        if path.startswith("study."): continue
        mods[path] = v
    if topic == "heatwave_dr":
        w = next((v for (p, v) in params.values() if p == "study.wave_add_k"), 0.0)
        if w: mods.update(T_ADD(float(w)))
    return mods

# ---------------- 研究计划 ----------------
def plan(topic, params):
    P = []
    def S(id, kind, title, why, variants, **kw): P.append(dict(id=id, kind=kind, title=title, why=why, variants=variants, status="pending", runs=[], added_by="plan", enabled=True, **kw))
    if topic == "heat_recovery":
        S("P1", "baseline", "基线：不回收余热", "建立“值不值”的比较基准（同网络、同天气、同算力负荷）", [dict(label="不回收余热", mods={"__remove_heat__": 1})])
        S("P2", "main", "主方案：余热回收供暖", "按澄清后的末端/管线/热价求解耦合 LP，得到收益、供热量、末端判定", [dict(label="余热回收（主方案）", mods={})])
        S("P3", "sensitivity", "敏感性：售热价格", "热价是收益的主要不确定性，找出盈亏平衡热价", [dict(label=f"热价 {v:g}", mods={"heat_network.price_cny_mwh_th": v}) for v in (60.0, 120.0, 200.0)])
        S("P4", "alternative", "方案比较：供热末端", "余热品位（30–40°C）与末端温度匹配决定技术可行性", [dict(label=f"末端 {n}", mods={"heat_network.terminal_type": t}) for t, n in (("floor", "地暖"), ("radiator", "散热器"), ("primary", "一次网"))])
        S("P5", "stress", "压力测试：寒潮（室外 −8 K）", "极寒时末端供水温度要求升高、热泵 COP 下降，检验结论稳健性", [dict(label="寒潮 −8K", mods=T_ADD(-8.0))], with_baseline=True)
        S("P6", "check", "交流潮流校核 + 热安全复核", "DC-OPF 为线性近似，需交流校核电压/负载率", [], check_of="P2")
    else:
        S("P1", "baseline", "基线：热浪日不参与 DR", "得到热浪日最优运行的成本与热安全基准", [dict(label="不参与 DR", mods={"__no_dr__": 1})])
        S("P2", "main", "主方案：按请求参与 DR", "检验在热安全硬约束下能否满足电网请求", [dict(label="参与 DR（主方案）", mods={})])
        S("P3", "sensitivity", "敏感性：削峰请求量（尽力响应）", "找出实际可响应量随请求量的变化", [dict(label=f"请求 {v:g} MW", mods={"dr_events.0.request_mw": v, "dr_events.0.mandatory": False}) for v in (20.0, 30.0, 40.0)])
        S("P4", "alternative", "方案比较：蓄冷罐容量", "虚拟储冷是热浪日 DR 的关键灵活性来源", [dict(label=f"蓄冷 ×{m:g}", mods={"data_centers.*.thermal.tes_mwh_th": {"op": "mul", "value": m}, "data_centers.*.thermal.tes_p_mw_th": {"op": "mul", "value": m}}) for m in (0.0, 1.0, 2.0)])
        S("P5", "stress", "压力测试：热浪再 +2°C", "检验方案在更极端热浪下是否仍安全可行", [dict(label="热浪 +2°C", mods=T_ADD(2.0))], with_baseline=True)
        S("P6", "check", "交流潮流校核 + 热安全复核", "DC-OPF 为线性近似，需交流校核", [], check_of="P2")
    return P

# ---------------- 结论 ----------------
def _ev(run, metric, label=None):
    v = (run.get("kpis") or {}).get(metric)
    return dict(run=run["id"], metric=metric, label=label or metric, value=v)

def _step_runs(study, sid, ok=True):
    st = next((p for p in study["plan"] if p["id"] == sid), None)
    rs = [study["runs"][r] for r in (st or {}).get("runs", []) if r in study["runs"]]
    return [r for r in rs if r["status"] == "optimal"] if ok else rs

def main_run(study):
    for sid in ("P2r", "P2"):
        rs = _step_runs(study, sid)
        if rs: return rs[-1]
    return None

def conclusions(study):
    t = study["topic"]; C = []; base = (_step_runs(study, "P1") or [None])[0]; main = main_run(study)
    A = {a["id"]: a for a in study.get("assumption_list", [])}
    def add(text, conf, evidence, assumptions, binding=None, links=None, sens=None):
        C.append(dict(id=f"C{len(C)+1}", text=text, confidence=conf, evidence=evidence, assumptions=assumptions, binding=binding or [], links=links or [], sensitivity=sens))
    if not main or not base:
        add("主方案或基线未得到可行解，无法给出结论；请查看诊断。", "低", [], []); return C
    errs = [f for f in main["findings"] if f["level"] == "error"]
    if t == "heat_recovery":
        val = base["kpis"]["cost_cny"] - main["kpis"]["cost_cny"]; k = main["kpis"]
        sens = [(r["mods"].get("heat_network.price_cny_mwh_th"), base["kpis"]["cost_cny"] - r["kpis"]["cost_cny"]) for r in _step_runs(study, "P3")]
        pos = all(v > 0 for _, v in sens) if sens else val > 0
        be = None
        if len(sens) >= 2:
            xs, ys = np.array([s[0] for s in sens]), np.array([s[1] for s in sens]); a, b = np.polyfit(xs, ys, 1)
            be = round(-b/a, 1) if a > 0 else None
        days = 120; capex = study["params_flat"].get("q_capex", 0) or 0
        hp = sum(d.thermal.hp_cap_mw_th for d in main["_sc"].data_centers if d.thermal) if main.get("_sc") else None
        pb = None
        if capex and hp and val > 0: pb = round(capex*1e4*hp/(val*days), 1)
        txt = (f"**{'值得' if val > 0 else '不值得'}**：余热回收使日净成本降低 **{val:,.0f} 元/日**（{base['id']} {base['kpis']['cost_cny']:,.0f} → {main['id']} {k['cost_cny']:,.0f}），"
               f"供热 {k.get('heat_delivered_mwh', 0):,.0f} MWh_th/日、售热 {k.get('heat_revenue_cny', 0):,.0f} 元、抵扣碳 {k.get('carbon_heat_offset_tco2', 0):,.0f} tCO2/日；"
               f"按 {days} 天供暖季折算约 {val*days/1e4:,.0f} 万元/季。")
        conf = "高" if (pos and not errs and k.get("heat_verdict") in (None, "可行")) else "中"
        bind = [b["group"] for b in main.get("binding", [])[:3]]
        add(txt, conf, [_ev(base, "cost_cny", "基线日成本"), _ev(main, "cost_cny", "主方案日成本"), _ev(main, "heat_delivered_mwh", "供热量"), _ev(main, "carbon_heat_offset_tco2", "抵扣碳")],
            ["A1", "A2", "A3"], bind, [dict(kind="run", id=base["id"]), dict(kind="run", id=main["id"]), dict(kind="param", path="heat_network.price_cny_mwh_th")],
            sens=dict(param="售热价格 元/MWh_th", points=[dict(x=x, y=round(y, 0)) for x, y in sens], breakeven=be))
        if sens:
            spread = (max(y for _, y in sens) - min(y for _, y in sens))/max(abs(val), 1)
            add(f"收益{'在测试热价范围内始终为正' if pos else '在低热价下转负'}，{'但对热价高度敏感' if spread > 0.5 else '对热价不敏感'}：热价 {', '.join(f'{x:g}→{y:,.0f} 元/日' for x, y in sens)}" + (f"；线性外推盈亏平衡热价约 {be} 元/MWh_th" + ("（低于 0，说明即使不售热，回收也通过 PUE/冷却节电获益）" if be is not None and be < 0 else "") if be is not None else "") + "。",
                "高" if len(sens) >= 3 else "中", [dict(run=r["id"], metric="cost_cny", label=r["label"], value=r["kpis"]["cost_cny"]) for r in _step_runs(study, "P3")], ["A3"],
                links=[dict(kind="step", id="P3")])
        alts = _step_runs(study, "P4", ok=False)
        if alts:
            seg = []
            for r in alts:
                kk = r.get("kpis", {})
                seg.append(f"{r['label'].replace('末端 ', '')}：{kk.get('heat_verdict', r['status'])}（裕度 {kk.get('terminal_margin_k')} K、热成本 {kk.get('heat_cost_cny_gj')} 元/GJ、节省 {base['kpis']['cost_cny'] - kk['cost_cny']:,.0f} 元/日）" if kk else f"{r['label']}：{r['status']}")
            bad = [r for r in alts if r.get("kpis", {}).get("heat_verdict") not in (None, "可行")]
            add("末端决定技术可行性：" + "；".join(seg) + ("。一次网等高温末端需调峰补热/高温热泵，余热品位（30–40°C 级）是瓶颈。" if bad else "。"),
                "高", [dict(run=r["id"], metric="terminal_margin_k", label=r["label"], value=r.get("kpis", {}).get("terminal_margin_k")) for r in alts], ["A1", "A2"], links=[dict(kind="step", id="P4")])
        st = [x for x in _step_runs(study, "P5") if x.get("role") != "baseline_pair"]
        if st:
            sr = st[-1]; sb = next((x for x in _step_runs(study, "P5") if x.get("role") == "baseline_pair"), None)
            sv = (sb["kpis"]["cost_cny"] - sr["kpis"]["cost_cny"]) if sb else None
            add(f"寒潮压力测试（室外 −8 K）下：{'仍然值得' if (sv or 0) > 0 else '收益消失'}，节省 {sv:,.0f} 元/日，末端判定 {sr['kpis'].get('heat_verdict', '—')}、裕度 {sr['kpis'].get('terminal_margin_k')} K。" if sv is not None else "寒潮压力测试已运行。",
                "中", [_ev(sr, "cost_cny", "寒潮主方案"), _ev(sb, "cost_cny", "寒潮基线") if sb else {}], ["A2"], links=[dict(kind="run", id=sr["id"])])
        if pb: add(f"按投资假设 {capex:g} 万元/MW_th × 热泵 {hp:g} MW_th，简单回收期约 **{pb} 年**（仅运行收益、不含运维与折现）。", "低", [_ev(main, "cost_cny")], ["A4"])
    else:
        k = main["kpis"]; firm = study.get("firm_dr")
        dr = (main.get("dr") or [{}])[0]
        _ta = k.get("tin_air_max_c", k.get("tin_max_c")); _cs = k.get("coolant_supply_max_c")
        txt = (f"热安全可保障：主方案 {main['id']} " + (f"风冷最高入口温度 {_ta}°C（上限 {study['params_flat'].get('q_tallow', 32):g}°C）" if _ta is not None else "")
               + (f"、液冷最高供液温度 {_cs}°C（液冷按各自供液上限校核）" if _cs is not None else "") + f"、违规 {k.get('thermal_violations', 0)} 处；"
               f"DR 响应 {dr.get('delivered_mwh', 0):.1f}/{dr.get('requested_mwh', 0):.1f} MWh，收入 {dr.get('revenue_cny', 0):,.0f} 元；日净成本 {k['cost_cny']:,.0f} 元（基线 {base['kpis']['cost_cny']:,.0f}，"
               f"{'节省' if base['kpis']['cost_cny'] > k['cost_cny'] else '增加'} {abs(base['kpis']['cost_cny'] - k['cost_cny']):,.0f} 元）。")
        add(txt, ("高" if (k.get("thermal_margin_k") or 0) > 0.5 else "中") if not errs else "低", [_ev(main, "tin_max_c", "最高入口温度"), _ev(main, "dr_delivered_mwh", "DR 响应"), _ev(base, "cost_cny", "基线成本"), _ev(main, "cost_cny", "主方案成本")],
            ["A1", "A2"], [b["group"] for b in main.get("binding", [])[:3]], [dict(kind="run", id=main["id"]), dict(kind="run", id=base["id"])])
        if firm:
            add(f"在热浪日 + 热安全硬约束下，可**保证**的削峰硬承诺上限约 **{firm['firm_mw']:g} MW**（二分求解，{firm['upper_mw']:g} MW 即不可行）；请求的 {firm['requested_mw']:g} MW 硬承诺不可行，"
                f"主因：{firm.get('cause')}。建议以 {firm['firm_mw']:g} MW 申报硬承诺，余量按尽力响应。", "高",
                [dict(run=firm.get("failed_run"), metric="status", label="原硬承诺", value="infeasible"), dict(run=main["id"], metric="dr_delivered_mwh", label="修订后响应", value=k.get("dr_delivered_mwh"))],
                ["A1", "A3"], ["需求响应约束（承诺量/上限）", "机房热平衡（RC 模型）", "冷机可用冷量上限（N+1）"], [dict(kind="step", id="P2"), dict(kind="step", id="P2r")])
        sr = _step_runs(study, "P3")
        if sr:
            add("尽力响应时实际可削减：" + "；".join(f"请求 {r['mods']['dr_events.0.request_mw']:g} MW → 响应 {r['kpis'].get('dr_delivered_mwh', 0):.1f} MWh（{100*r['kpis'].get('dr_delivered_mwh', 0)/max(r['kpis'].get('dr_requested_mwh', 1e-9), 1e-9):.0f}%）" for r in sr) + "。",
                "高", [_ev(r, "dr_delivered_mwh", r["label"]) for r in sr], ["A2"], links=[dict(kind="step", id="P3")])
        tr = _step_runs(study, "P4", ok=False)
        if tr:
            add("蓄冷容量的作用：" + "；".join(f"{r['label']} → " + (f"成本 {r['kpis']['cost_cny']:,.0f} 元、DR {r['kpis'].get('dr_delivered_mwh', 0):.1f} MWh、最高入口 {r['kpis'].get('tin_max_c')}°C" if r["status"] == "optimal" else "不可行") for r in tr) + "。",
                "中", [_ev(r, "cost_cny", r["label"]) for r in tr if r["status"] == "optimal"], ["A1"], links=[dict(kind="step", id="P4")])
        st = _step_runs(study, "P5", ok=False)
        if st:
            r = [x for x in st if x.get("role") != "baseline_pair"]
            r = r[-1] if r else st[-1]
            add(f"热浪再 +2°C：方案{'仍可行' if r['status'] == 'optimal' else '不可行'}" + (f"，最高入口 {r['kpis'].get('tin_max_c')}°C、DR {r['kpis'].get('dr_delivered_mwh', 0):.1f} MWh。" if r["status"] == "optimal" else "：需下调承诺量或增加蓄冷。"),
                "中", [_ev(r, "tin_max_c", "压力测试")] if r["status"] == "optimal" else [dict(run=r["id"], metric="status", value=r["status"])], ["A1"], links=[dict(kind="run", id=r["id"])])
    edge = [f for f in main["findings"] if f["code"] == "THERMAL_EDGE"]
    if edge:
        chk = _step_runs(study, "P2m", ok=False)
        add(f"⚠ 主方案入口温度在 {len(edge[0]['evidence'].get('hours', []))} 个时段贴着允许上限（裕度 0 K）" + (f"；裕度复核（上限 −1 K）{'仍可行' if chk and chk[-1]['status'] == 'optimal' else '不可行'}" if chk else "") + "，工程实施应预留 1–2 K 安全裕度。",
            "中", [dict(run=main["id"], metric="thermal_margin_k", label="热裕度", value=main["kpis"].get("thermal_margin_k"))] + ([dict(run=chk[-1]["id"], metric="status", label="裕度复核", value=chk[-1]["status"])] if chk else []), ["A1"])
    return C
