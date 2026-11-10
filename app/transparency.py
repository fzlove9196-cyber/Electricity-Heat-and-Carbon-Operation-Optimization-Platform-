"""仿真过程透明化：参数表（含来源标注）、数学模型（目标/约束/变量/规模）、运行日志、KPI 定义、结果归因、可复现运行包。"""
from __future__ import annotations
import json, os, re, time, io, zipfile
import numpy as np
from .scenario import Scenario

# ---------------- 工作流步骤 ----------------
STEPS = [("goal", "① 场景与目标"), ("params", "② 输入参数"), ("model", "③ 模型构建（拓扑核对）"),
         ("solver", "④ 求解配置"), ("run", "⑤ 运行与校核"), ("results", "⑥ 结果与分析")]
TOOL_STEP = {"build_scenario": "params", "generate_jobs": "params", "load_job_trace": "params", "get_carbon_profile": "params",
             "show_model_topology": "model", "plot_topology": "model", "run_dispatch": "run", "run_ac_check": "run",
             "run_pareto_sweep": "run", "compute_kpis": "results", "compare_baseline": "results", "make_plots": "results",
             "write_report": "results", "plot_energy_flow": "results", "search_knowledge": "goal", "save_skill_card": "goal"}
RUN_TOOLS = {"run_dispatch", "run_ac_check", "compare_baseline", "run_pareto_sweep", "compute_kpis", "make_plots", "write_report", "plot_energy_flow"}
TOOL_CN = {"build_scenario": "构建场景", "run_dispatch": "优化调度求解", "run_ac_check": "交流潮流校核", "compute_kpis": "计算 KPI",
           "compare_baseline": "基线对比", "make_plots": "生成图表", "write_report": "撰写报告", "show_model_topology": "生成模型拓扑",
           "search_knowledge": "检索知识库", "save_skill_card": "保存技能卡", "get_carbon_profile": "碳强度曲线", "run_pareto_sweep": "成本-碳 Pareto 扫描",
           "generate_jobs": "生成任务", "load_job_trace": "加载任务 trace", "plot_topology": "拓扑单线图", "plot_energy_flow": "能流图",
           "run_matpower": "MATPOWER 潮流", "run_andes_tds": "ANDES 暂态", "run_opendss": "OpenDSS 配网", "run_openmodelica": "OpenModelica", "run_paraview_render": "ParaView 3D"}
TOOL_WHY = {"build_scenario": "把需求转换为可求解的场景（网络、电源、储能、数据中心、电价、碳参数）",
            "run_dispatch": "求解 24h 多时段 DC-OPF 线性规划，得到最低成本调度方案",
            "run_ac_check": "用交流潮流校核 DC-OPF 结果在峰值时刻的电压与支路负载是否越限",
            "compute_kpis": "由调度结果计算关键指标", "compare_baseline": "与“无协同”基线对比，量化优化收益",
            "make_plots": "把逐时结果画成图便于核对", "write_report": "汇总为 Markdown 报告", "show_model_topology": "生成拓扑图供核对模型"}
DEFAULT_SOLVER = dict(solver="HiGHS", time_limit_s=60, mip_gap=None, run_baseline=True, ac_check=True, ac_hour=None, attribution=True)

def log_entry(s, name, args, ok, res, dt, err=None):
    actor = s.state.pop("_actor", None) or "智能体"
    why = s.state.pop("_why", None)
    e = dict(i=len(s.state.get("runlog", [])) + 1, ts=time.strftime("%H:%M:%S"), tool=name, title=TOOL_CN.get(name, name),
             step=TOOL_STEP.get(name, "run"), actor=actor, why=why or TOOL_WHY.get(name, ""), why_source="智能体说明" if why else "系统说明",
             args=_short(args), ok=ok, duration_s=round(dt, 3), error=err, outputs=_summ(name, res) if ok else {})
    s.state.setdefault("runlog", []).append(e); s.state["runlog"] = s.state["runlog"][-200:]
    s.state["wf_step"] = e["step"]
    return e

def _short(o, n=400):
    try: t = json.dumps(o, ensure_ascii=False, default=str)
    except Exception: t = str(o)
    if len(t) <= n: return json.loads(t) if t.startswith(("{", "[")) else t
    return t[:n] + "…"

def _summ(name, r):
    if not isinstance(r, dict): return {}
    keep = ["case", "objective_cny", "cost_cny", "emissions_tco2", "pv_curtail_mwh", "converged", "hour", "vmin_pu", "vmax_pu",
            "max_branch_loading_pct", "voltage_ok", "loading_ok", "losses_mw", "saving_pct", "saving_cny", "emissions_reduction_pct",
            "jobs_deadline_met_pct", "migrated_mwh", "artifact", "solver_status", "solver_time_s", "n_vars", "n_constraints"]
    out = {k: r[k] for k in keep if k in r}
    if "summary" in r: out["summary"] = _short(r["summary"], 300)
    if "kpis" in r: out["kpis_n"] = len(r["kpis"])
    if "artifacts" in r and "artifact" not in out: out["artifacts"] = r["artifacts"][:6]
    return out

def step_status(s):
    st = s.state; sc = st.get("scenario"); res = st.get("results", {})
    done = dict(goal=sc is not None, params=bool(st.get("params_confirmed")) and sc is not None,
                model=bool(st.get("params_confirmed")) and sc is not None, solver=bool(st.get("params_confirmed")) and sc is not None,
                run="optimized" in res, results="compare" in st and "optimized" in res)
    cur = st.get("wf_step") or next((k for k, _ in STEPS if not done[k]), "results")
    if sc is None: cur = "goal"
    return [dict(id=k, label=l, done=done[k], current=(k == cur)) for k, l in STEPS], cur

# ---------------- 参数表 ----------------
_KW = {"thermal.t_": ["热安全边界"], "thermal.ramp": ["热安全边界"], "thermal": ["热模型"], "outdoor_temp": ["室外温度"], "heat_network": ["余热供热"],
       "dr_events": ["需求响应"], "carbon_marginal": ["碳强度逐时"], "carbon_basis": ["碳强度逐时"], "thermal_mode": ["热模型"], "pue": ["PUE"], "price_cny_kwh": ["电价", "峰平谷", "电度"], "carbon": ["排放因子"], "cap_it_mw": ["存量", "增量", "规模"],
       "batch_mwh": ["DC灵活性", "灵活性", "年用电"], "storage": ["储能"], "links": ["链路"], "carbon_price_cny_t": ["碳价"],
       "pv_curtail_penalty": ["弃电"], "lines": ["线路", "等值网络", "回110kV"], "pv": ["风电", "风光", "清洁电力", "光伏"], "ext_grids": ["外送"],
       "interactive_mw": ["负荷", "灵活性"], "power_model": ["功率模型", "idle", "PDU"], "vcc_mode": ["VCC", "虚拟容量", "碳智能"]}

def _src_lookup(sc: Scenario, path: str):
    key = next((k for k in _KW if k in path), None)
    if not key or not sc.sources: return None
    for k, v in sc.sources.items():
        if k == "假设": continue
        if any(w in k for w in _KW[key]):
            urls = re.findall(r"https?://[^\s;，,]+", v)
            if urls: return dict(tag="公开资料", note=k, link=urls[0])
            return dict(tag="案例假设" if "假设" in v else "公开资料", note=f"{k}：{v[:140]}")
    a = sc.sources.get("假设", "")
    if any(w in a for w in _KW[key]): return dict(tag="案例假设", note="案例假设：" + a[:120])
    return None

def _source(s, sc, path):
    ps = s.state.get("param_src", {}); org = s.state.get("origin", {"kind": "default"})
    if path in ps: return ps[path]
    top = path.split(".")[0]
    if top in ps: return ps[top]
    if org.get("kind") == "preset":
        return _src_lookup(sc, path) or dict(tag="案例假设", note=f"来自案例预设 {org.get('name')}（{(sc.sources.get('假设') or '见案例 sources')[:80]}）")
    if org.get("kind") == "agent_json": return dict(tag="智能体推断", note="智能体直接给出完整场景 JSON")
    if org.get("kind") == "user": return dict(tag="用户指定", note="用户在界面提供的场景")
    return dict(tag="默认值", note="引擎内置合成默认值（SYNTHETIC）")

def _stat(v):
    a = np.asarray(v, float); return f"{len(a)} 点：min {a.min():.3g} / 均值 {a.mean():.3g} / max {a.max():.3g}"

def _items(sc: Scenario):
    """(group, path, 名称, 含义, 值, 单位, 范围/枚举, 类型, 必填)"""
    I = []; A = I.append
    nw = sc.network
    A(("时间与任务模式", "dt_hours", "物理时间步", "MW×dt=MWh；15min须显式展开全部曲线；旧历史按结果自身时间步", sc.dt_hours, "h", None, "info", True))
    A(("时间与任务模式", "migration_cleanup", "迁移去冗余次目标", "先保持第一主目标最优值，再最小gross迁移；默认off", sc.migration_cleanup, "", ["off","lexicographic_gross"], "enum", False))
    A(("时间与任务模式", "migration_cleanup_tolerance_cny", "第一主目标锁定公差", "不暗加epsilon；状态/偏差/公差随结果导出", sc.migration_cleanup_tolerance_cny, "CNY", [0,1e-4], "num", False))
    for i,j in enumerate(sc.jobs):
        for f,u in [("execution_mode","mode"),("duration_h","h"),("initial_progress_h","h"),("initial_dc","site"),("allow_restart","bool"),("restart_delay_h","h"),("required","bool"),("source","source")]:
            A(("时间与任务模式",f"jobs.{i}.{f}",j.id+" · "+f,"energy=可分能量；continuous=整数连续固定功率；取消从零重启并分账损失；修改完整草稿JSON",getattr(j,f),u,None,"info",False))
    A(("网络", "network_case", "网络模型", "case14=IEEE14 标准算例；custom=等值自定义网络", sc.network_case, "", ["case14", "custom"], "enum", True))
    if sc.network_case == "custom" and nw:
        A(("网络", "network.buses", "母线数", "等值网络母线（节点）数量", len(nw.buses), "个", None, "info", True))
        for i, l in enumerate(nw.lines):
            A(("网络", f"network.lines.{i}.rating_mva", f"线路 {l.name or i} 额定", f"{nw.buses[l.from_bus].name}→{nw.buses[l.to_bus].name}，{l.length_km} km，x={l.x_ohm_per_km} Ω/km，×{l.parallel} 回", l.rating_mva, "MVA/回", [1, 1e5], "num", True))
        for i, t in enumerate(nw.trafos):
            A(("网络", f"network.trafos.{i}.sn_mva", f"变压器 {t.name or i} 容量", f"{nw.buses[t.hv_bus].name}/{nw.buses[t.lv_bus].name}，vk={t.vk_percent}%", t.sn_mva, "MVA", [1, 1e5], "num", True))
        for i, e in enumerate(nw.ext_grids):
            A(("网络", f"network.ext_grids.{i}.import_max_mw", f"外网 {e.name} 购电上限", "从外部电网最大受入功率", e.import_max_mw, "MW", [0, 1e5], "num", True))
            A(("网络", f"network.ext_grids.{i}.export_max_mw", f"外网 {e.name} 反送上限", ">0 允许向外网售电（外送）", e.export_max_mw, "MW", [0, 1e5], "num", False))
        for i, ld in enumerate(nw.loads):
            A(("网络", f"network.loads.{i}.p_mw", f"常规负荷 {ld.name}", "基准有功，按系统日负荷曲线缩放", ld.p_mw, "MW", [0, 1e5], "num", False))
    A(("网络", "load_scale", "常规负荷缩放", "常规负荷曲线整体倍数", sc.load_scale, "×", [0, 5], "num", True))
    # 电源
    for i, p in enumerate(sc.pv):
        kind = p.kind or ("wind" if (p.profile and min(p.profile[:5]) > 0.02) else "pv")
        nm = p.name or f"{'风电' if kind == 'wind' else '光伏'}{i}"
        A(("电源", f"pv.{i}.cap_mw", f"{nm} 装机", f"接入母线 {p.bus}；出力 = 装机 × 逐时出力系数", p.cap_mw, "MW", [0, 1e5], "num", True))
        A(("电源", f"pv.{i}.profile", f"{nm} 出力系数", "逐时可用出力/装机（0-1）；缺省为合成正弦光伏曲线", _stat(p.profile) if p.profile else "合成正弦曲线（缺省）", "p.u.", [0, 1], "list24", False))
        if p.ppa_price_cny_kwh is not None:
            A(("电价与碳", f"pv.{i}.ppa_price_cny_kwh", f"{nm} PPA 结算价", "绿电直供/PPA 结算价" + ("（照付不议：按可发电量结算）" if p.ppa_take_or_pay else "（按实际利用电量）"), p.ppa_price_cny_kwh, "元/kWh", [0, 3], "num", False))
    if sc.network_case == "custom" and nw:
        for i, g in enumerate(nw.gens):
            grp = "柴发/备用电源" if (g.kind or "") == "diesel" else "电源"
            A((grp, f"network.gens.{i}.pmax_mw", f"{g.name} 最大出力", f"{g.kind} 机组，母线 {g.bus}", g.pmax_mw, "MW", [0, 1e5], "num", True))
            A((grp, f"network.gens.{i}.pmin_mw", f"{g.name} 最小出力", "简化连续模型；0=可停机", g.pmin_mw, "MW", [0, 1e5], "num", True))
            A((grp, f"network.gens.{i}.cost_cny_mwh", f"{g.name} 发电成本", "边际成本", g.cost_cny_mwh, "元/MWh", [0, 5000], "num", True))
            if getattr(g, "ramp_mw_h", None) is not None:
                A((grp, f"network.gens.{i}.ramp_mw_h", f"{g.name} 爬坡", "|P_t−P_{t−1}| ≤ ramp", g.ramp_mw_h, "MW/h", [0, 1e5], "num", True))
            if (g.kind or "") == "diesel":
                A((grp, f"network.gens.{i}.dispatch_mode", f"{g.name} 调度模式",
                   "economic/peak_shave=可日常调度；emergency_only=仅应急", getattr(g, "dispatch_mode", "economic"), "",
                   ["economic", "emergency_only", "peak_shave"], "enum", True))
                A((grp, f"network.gens.{i}.emission_t_mwh", f"{g.name} 排放因子", "柴油发电", g.emission_t_mwh, "tCO2/MWh", [0, 2], "num", True))
                if getattr(g, "source_note", ""):
                    A((grp, f"network.gens.{i}.source_note", f"{g.name} 来源", "参数来源/【假设】", g.source_note, "", None, "info", False))
            if g.energy_mwh_day is not None:
                A((grp, f"network.gens.{i}.energy_mwh_day", f"{g.name} 日电量上限", "水电来水约束 Σ_t P ≤ E_day", g.energy_mwh_day, "MWh", [0, 1e6], "num", False))
        A(("柴发/备用电源", "emergency_mode", "应急模式", "True 时 UPS 可用至 soc_min，emergency_only 柴发放开", getattr(sc, "emergency_mode", False), "", [True, False], "enum", True))
    else:
        A(("电源", "gen_cost", "IEEE14 机组成本", "4 台常规机组边际成本（合成）", sc.gen_cost, "元/MWh", [0, 5000], "list", True))
        A(("电源", "gen_min_share", "机组最小出力比例", "Pmin = 比例 × Pmax", sc.gen_min_share, "", [0, 1], "num", True))
    # 储能
    if not sc.storage:
        A(("储能", "storage", "储能", "当前场景无储能（可在拓扑页添加）", "无", "", None, "info", False))
    for i, x in enumerate(sc.storage):
        kind = getattr(x, "kind", "ess") or "ess"
        grp = "UPS/EUPS" if kind == "ups" else "储能"
        for f, n, m, u, r in [("bus", "接入母线", "所在母线编号", "", [0, 999]), ("energy_mwh", "容量", "可用能量容量 E", "MWh", [0, 1e5]),
                              ("power_mw", "功率", "最大充/放电功率 P", "MW", [0, 1e5]), ("eta_ch", "充电效率", "η_ch", "", [0.5, 1]),
                              ("eta_dis", "放电效率", "η_dis", "", [0.5, 1]), ("soc0", "初始 SOC", "日初荷电状态（日末不低于此值）", "p.u.", [0, 1]),
                              ("soc_min", "SOC 下限", "硬底线；UPS 经济调度另见 reserve_frac", "p.u.", [0, 1]), ("soc_max", "SOC 上限", "", "p.u.", [0, 1])]:
            A((grp, f"storage.{i}.{f}", f"{x.name} {n}", m, getattr(x, f), u, r, "num", True))
        A((grp, f"storage.{i}.kind", f"{x.name} 类型", "ess=站用储能；ups=可调度 UPS/EUPS", kind, "", ["ess", "ups"], "enum", False))
        if kind == "ups":
            A((grp, f"storage.{i}.reserve_frac", f"{x.name} 备用保留比例",
               "ops_soc_min=soc_min+reserve_frac×(soc_max-soc_min)；emergency 时退回 soc_min",
               getattr(x, "reserve_frac", 0.0), "", [0, 1], "num", True))
        if getattr(x, "source_note", ""):
            A((grp, f"storage.{i}.source_note", f"{x.name} 来源", "参数来源/【假设】", x.source_note, "", None, "info", False))
    # 数据中心
    for i, d in enumerate(sc.data_centers):
        A(("数据中心与算力负荷", f"data_centers.{i}.bus", f"{d.name} 接入母线", "", d.bus, "", [0, 999], "num", True))
        A(("数据中心与算力负荷", f"data_centers.{i}.cap_it_mw", f"{d.name} IT 容量", "交互+批处理 IT 功率上限", d.cap_it_mw, "MW", [0, 1e5], "num", True))
        A(("数据中心与算力负荷", f"data_centers.{i}.pue", f"{d.name} PUE", "电网侧功率 = PUE × IT 功率", d.pue, "", [1, 3], "num", True))
        A(("数据中心与算力负荷", f"data_centers.{i}.interactive_mw", f"{d.name} 交互式负载", "不可调度的在线业务 IT 功率", _stat(d.interactive_mw), "MW", None, "list24", True))
        if not sc.jobs:
            A(("数据中心与算力负荷", f"data_centers.{i}.batch_mwh", f"{d.name} 批处理日能量", "可时移/迁移的批处理 IT 能量（聚合模型）", d.batch_mwh, "MWh/日", [0, 1e6], "num", True))
        A(("数据中心与算力负荷", f"data_centers.{i}.power_model", f"{d.name} IT 功率模型",
           "identity=P_IT=IT工作功率（旧）；idle_dynamic=P_idle+(P_peak-P_idle)·u；pdu_pwl=分段线性(SOS2/MILP)",
           d.power_model, "", ["identity", "idle_dynamic", "pdu_pwl"], "enum", False))
        if d.power_model and d.power_model != "identity":
            A(("数据中心与算力负荷", f"data_centers.{i}.p_idle_mw", f"{d.name} 空载功率", "站点 idle MW（或由 p_idle_kw×n_servers 换算）", d.p_idle_mw, "MW", [0, 1e4], "optnum", False))
            A(("数据中心与算力负荷", f"data_centers.{i}.p_peak_mw", f"{d.name} 峰值功率", "u=1 时站点功率", d.p_peak_mw, "MW", [0, 1e4], "optnum", False))
    A(("数据中心与算力负荷", "jobs", "任务级作业", "非空时按任务建模（释放/截止/能量/功率/允许 DC/时延）", f"{len(sc.jobs)} 个，合计 {sum(j.energy_mwh for j in sc.jobs):.1f} MWh" if sc.jobs else "无（聚合批处理模型）", "", None, "info", False))
    A(("数据中心与算力负荷", "mig_max_mw", "每小时迁移上限", "每个 DC 每小时迁出 IT 功率上限", sc.mig_max_mw, "MW", [0, 1e5], "num", True))
    A(("数据中心与算力负荷", "mig_day_share", "日迁移比例上限", "日迁出能量 ≤ 比例 × 本地批处理能量", sc.mig_day_share, "", [0, 1], "num", True))
    A(("数据中心与算力负荷", "mig_energy_mwh_per_mwh", "迁移能耗系数 κ", "每迁移 1 MWh 在目的地额外消耗 κ MWh", sc.mig_energy_mwh_per_mwh, "MWh/MWh", [0, 1], "num", False))
    for i, l in enumerate(sc.links):
        A(("数据中心与算力负荷", f"links.{i}.bw_mw", f"链路 {l.a}-{l.b} 带宽", f"时延 {l.latency_ms} ms；每小时可迁移 IT 功率上限", l.bw_mw, "MW", [0, 1e5], "num", False))
    # 电价与碳
    A(("电价与碳", "price_cny_kwh", "分时电价", f"购电电度电价（{sc.price_kind}）", _stat(sc.price_cny_kwh), "元/kWh", [0, 5], "list24", True))
    A(("电价与碳", "grid_markup_cny_mwh", "购电附加", "购电价之外的输配/附加费用", sc.grid_markup_cny_mwh, "元/MWh", [0, 2000], "num", True))
    if sc.network_case == "custom" and nw:
        for i, e in enumerate(nw.ext_grids):
            if e.demand_charge_cny_mw_day:
                A(("电价与碳", f"network.ext_grids.{i}.demand_charge_cny_mw_day", f"外网 {e.name} 需量电费", "按日最大购电功率计费（月需量电价/30）", e.demand_charge_cny_mw_day, "元/MW·日", [0, 1e5], "num", False))
    A(("电价与碳", "carbon_factor", "电网排放因子", "缺省碳强度曲线日均值", sc.carbon_factor, "tCO2/MWh", [0, 2], "num", True))
    A(("电价与碳", "carbon_price_cny_t", "碳价", "λ，用于碳成本与双目标", sc.carbon_price_cny_t, "元/tCO2", [0, 2000], "num", True))
    A(("电价与碳", "carbon_weight", "碳权重 w", "目标 = 成本 + w·λ·排放；0=纯成本", sc.carbon_weight, "", [0, 100], "num", True))
    A(("电价与碳", "vcc_mode", "VCC 虚拟容量模式", "off=关闭（旧）；carbon/price/weighted=灵活负荷容量整形（Google Carbon-Intelligent 风格）",
       sc.vcc_mode, "", ["off", "carbon", "price", "weighted"], "enum", False))
    if sc.vcc_mode != "off":
        A(("电价与碳", "vcc_stage", "VCC 阶段", "joint=与 DC-OPF 同层；day_ahead=先解 VCC 再约束批处理", sc.vcc_stage, "", ["joint", "day_ahead"], "enum", False))
        A(("电价与碳", "vcc_carbon_weight", "VCC 碳信号权重", "weighted 模式", sc.vcc_carbon_weight, "", [0, 100], "num", False))
        A(("电价与碳", "vcc_price_weight", "VCC 电价信号权重", "weighted 模式", sc.vcc_price_weight, "", [0, 100], "num", False))
        A(("电价与碳", "vcc_preserve_daily", "VCC 日能量守恒", "Σ Cap_vcc ≥ 日灵活需求", sc.vcc_preserve_daily, "", [True, False], "enum", False))
    A(("电价与碳", "carbon_accounting", "碳核算口径", "location=数据中心用电×区域碳强度；generation=发电侧", sc.carbon_accounting, "", ["location", "generation"], "enum", True))
    # ---- 算-电-热-碳耦合 ----
    TM = "热管理与冷却"
    if not (sc.thermal_mode == "coupled" or any(d.thermal for d in sc.data_centers) or sc.heat_network or sc.dr_events):
        A(("数据中心与算力负荷", "thermal_mode", "热-电耦合模式", "当前常数 PUE；在拓扑页「❄ 热管理」为 DC 启用热模型，或对智能体说“考虑虚拟储冷/余热/需求响应/热安全”，将出现 热管理与冷却/余热回收与供热/需求响应/碳 参数组",
           sc.thermal_mode, "", ["constant_pue", "coupled"], "enum", False))
        TM = None
    if TM: A((TM, "thermal_mode", "热-电耦合模式", "constant_pue=电网侧=PUE×IT（旧模型）；coupled=RC 热模型+冷机 COP(T_out)+自然冷却+蓄冷，输出动态 PUE", sc.thermal_mode, "", ["constant_pue", "coupled"], "enum", True))
    if TM is None: return _items_tail(sc, I)
    A((TM, "outdoor_temp_c", "室外温度（缺省区域）", "逐时室外干球温度，决定冷机 COP 与自然冷却可用量", _stat(sc.outdoor_temp_c), "°C", [-40, 50], "list24", False))
    for r, prof in sc.outdoor_temp_profiles.items():
        A((TM, f"outdoor_temp_profiles.{r}", f"室外温度 [{r}]", "区域逐时室外温度", _stat(prof), "°C", [-40, 50], "list24", False))
    for i, d in enumerate(sc.data_centers):
        th = d.thermal
        if th is None:
            if sc.thermal_mode == "coupled": A((TM, f"data_centers.{i}.thermal", f"{d.name} 热模型", "未配置热参数 → 沿用常数 PUE", "无", "", None, "info", False))
            continue
        P = f"data_centers.{i}.thermal."
        for f, n, mng, u, rg in [("t_min_c", "入口温度下限", "ASHRAE 推荐下限（硬约束）", "°C", [10, 27]), ("t_rec_max_c", "推荐上限", "超出部分按软惩罚计", "°C", [18, 35]),
                                 ("t_allow_max_c", "允许上限（硬）", "热安全硬约束 T_in ≤ 此值", "°C", [20, 45]), ("ramp_max_k_h", "最大温变率", "|ΔT_in| ≤ 此值（硬约束）", "K/h", [0.5, 20]),
                                 ("rec_exceed_penalty_cny_kh", "超推荐上限惩罚", "元/(K·h)，引导性虚拟成本", "元/K·h", [0, 1e5]),
                                 ("c_air_mwh_k", "空气/机柜热容", "快节点热容 C_a", "MWh_th/K", [0.001, 100]), ("c_mass_mwh_k", "建筑/机架热容", "慢节点热容 C_m（虚拟储冷能力）", "MWh_th/K", [0, 1000]),
                                 ("ua_am_mw_k", "空气-结构换热", "UA_am", "MW_th/K", [0, 100]), ("ua_env_mw_k", "围护换热", "UA_env（与室外）", "MW_th/K", [0, 10]),
                                 ("chiller_cap_mw_th", "冷机装机冷量", "含备用", "MW_th", [0, 1e4]), ("chiller_units", "冷机台数", "N+1 时可用 = 装机×(n−1)/n", "台", [1, 50]),
                                 ("crah_cap_mw_th", "末端排热能力", "CRAH/列间空调", "MW_th", [0, 1e4]), ("cop_ref", "冷机参考 COP", "室外 25°C 时", "", [1, 15]),
                                 ("cop_slope_per_k", "COP 温度斜率", "COP_t = COP_ref − k(T_out−25)", "1/K", [0, 1]), ("tower_pump_kw_per_kw", "冷却塔/水泵电耗", "", "kW/kW_th", [0, 0.2]),
                                 ("free_cap_mw_th", "自然冷却冷量", "板换/间接蒸发", "MW_th", [0, 1e4]), ("free_t_full_c", "自然冷却满出力温度", "T_out ≤ 此值满出力", "°C", [-30, 25]),
                                 ("free_t_zero_c", "自然冷却截止温度", "T_out ≥ 此值无自然冷却", "°C", [-20, 30]), ("other_frac", "其他损耗比例", "配电/UPS/照明 占 IT", "", [0, 0.3]),
                                 ("tes_mwh_th", "蓄冷罐容量", "显式储冷（冷冻水/冰）", "MWh_th", [0, 1e4]), ("tes_p_mw_th", "蓄冷罐功率", "充/放冷上限", "MW_th", [0, 1e4]),
                                 ("tes_loss_h", "蓄冷自损失", "每小时", "", [0, 0.1])]:
            A((TM, P + f, f"{d.name} {n}", mng, getattr(th, f), u, rg, "num", f in ("t_allow_max_c", "chiller_cap_mw_th", "cop_ref")))
        A((TM, P + "redundancy_n1", f"{d.name} N+1 冗余", "冷机保留 1 台备用", th.redundancy_n1, "", [True, False], "enum", False))
    CM = "散热方式"
    from .tools.cooling import MODES as _CM, liquid_fraction as _lf, source_temp as _st
    for i, d in enumerate(sc.data_centers):
        th = d.thermal
        if th is None: continue
        P = f"data_centers.{i}.thermal."
        md = _CM.get(th.cooling_mode or "")
        A((CM, P + "cooling_mode", f"{d.name} 散热方式", "风冷冷冻水/间接蒸发/直接蒸发/冷板液冷/浸没液冷/混合；切换后按散热方式库重设温度边界、COP 曲线、自然冷却阈值、WUE、余热源温度" + (f"。当前：{md['cn']}，典型 PUE {md['pue_typical']}" if md else "（未选=通用参数）"),
           th.cooling_mode, "", list(_CM), "enum", True))
        if md and md["family"] == "liquid":
            A((CM, P + "liquid_frac", f"{d.name} 液冷比例", "液冷承担 IT 发热比例（0=按方式默认）；其余经残余风冷", round(_lf(th), 2), "", [0, 1], "num", False))
            A((CM, P + "air_residual_mode", f"{d.name} 残余风冷方式", "", th.air_residual_mode, "", ["air_chw", "air_iec", "air_dec"], "enum", False))
        A((CM, P + "waste_heat_c", f"{d.name} 余热源温度", f"覆盖值；空=按散热方式（当前 {_st(th):.0f}°C）", th.waste_heat_c, "°C", [15, 80], "optnum", False))
        A((CM, P + "wue_l_kwh", f"{d.name} WUE 覆盖", "空=按散热方式库（蒸发冷却/冷却塔耗水）", th.wue_l_kwh, "L/kWh", [0, 5], "optnum", False))
        A((CM, P + "racks", f"{d.name} 机柜数", "功率密度=IT/机柜；风冷 >25 kW/柜建议液冷", th.racks, "柜", [1, 1e6], "optnum", False))
    HR = "余热回收与供热"
    for i, d in enumerate(sc.data_centers):
        if d.thermal is not None and (d.thermal.hp_cap_mw_th > 0 or sc.heat_network is not None):
            P = f"data_centers.{i}.thermal."
            A((HR, P + "hp_cap_mw_th", f"{d.name} 热泵供热能力", "余热回收热泵最大供热（0=不回收）", d.thermal.hp_cap_mw_th, "MW_th", [0, 1e4], "num", False))
            A((HR, P + "hp_cop", f"{d.name} 热泵 COP", "供热量/耗电", d.thermal.hp_cop, "", [1.5, 10], "num", False))
            A((HR, P + "hr_max_frac", f"{d.name} 可回收余热比例", "回收热 ≤ 比例×IT 发热", d.thermal.hr_max_frac, "", [0, 1], "num", False))
    hn = sc.heat_network
    if hn is None: A((HR, "heat_network", "区域供热网", "当前场景未接入供热网（冬季北方园区可添加）", "无", "", None, "info", False))
    else:
        A((HR, "heat_network.demand_mw_th", f"{hn.name} 可接纳热负荷", "逐时可接纳余热负荷", _stat(hn.demand_mw_th), "MW_th", None, "list24", True))
        for f, n, mng, u, rg in [("price_cny_mwh_th", "售热价格", "余热售热收入（目标负项）", "元/MWh_th", [0, 2000]), ("boiler_ef_t_mwh_th", "替代锅炉排放因子", "热碳抵扣", "tCO2/MWh_th", [0, 1]),
                                 ("pipe_loss", "管网热损", "", "", [0, 0.5]), ("storage_mwh_th", "热网惯性/蓄热容量", "虚拟储热", "MWh_th", [0, 1e5]),
                                 ("storage_p_mw_th", "蓄热功率", "", "MW_th", [0, 1e4]), ("storage_loss_h", "蓄热自损失", "每小时", "", [0, 0.2])]:
            A((HR, "heat_network." + f, n, mng, getattr(hn, f), u, rg, "num", f == "price_cny_mwh_th"))
        HG = "余热品位与供热末端"
        A((HG, "heat_network.terminal_type", "供热末端类型", "floor 地暖 35-45 / fcu 风机盘管 45-55 / radiator 散热器 60-75 / primary 城市一次网 70-110 °C；空=旧模型(常数 COP)", hn.terminal_type, "", ["floor", "fcu", "radiator", "primary", None], "enum", False))
        for f, n, mng, u, rg in [("t_supply_min_c", "末端要求供水(暖季)", "空=按末端类型", "°C", [25, 130]), ("t_supply_max_c", "末端要求供水(设计温度)", "空=按末端类型", "°C", [25, 130]),
                                 ("t_return_c", "回水温度", "空=按末端类型", "°C", [15, 80]), ("t_out_design_c", "供暖室外计算温度", "质调节曲线端点", "°C", [-40, 10]),
                                 ("pipe_length_km", "输热管线长度", "单程", "km", [0, 100]), ("pipe_dt_k_per_km", "沿程温降", "保温良好 0.1-0.3", "K/km", [0, 3]),
                                 ("pipe_loss_per_km", "沿程热损", "比例/km", "", [0, 0.05]), ("hx_approach_k", "板换端差", "直接换热判据", "K", [1, 15]),
                                 ("hp_eta_carnot", "热泵卡诺效率 η", "COP=η·T_sink/(T_sink−T_evap)", "", [0.3, 0.7]), ("hp_max_out_c", "热泵最高出水", "常规 80 / 高温 95", "°C", [50, 130]),
                                 ("booster_price_cny_mwh_th", "燃气补热成本", "", "元/MWh_th", [0, 2000]), ("ref_heat_price_cny_gj", "对标热价", "经济性判据", "元/GJ", [0, 300]),
                                 ("design_load_mw_th", "设计热负荷", "degree_hour 模式", "MW_th", [0, 1e4])]:
            A((HG, "heat_network." + f, n, mng, getattr(hn, f), u, rg, "optnum" if f.startswith("t_") and f != "t_out_design_c" else "num", False))
        A((HG, "heat_network.booster", "补热方式", "温度不足时：燃气调峰锅炉/电加热/无（无=末端不达标即不可行）", hn.booster, "", ["gas_boiler", "electric", "none"], "enum", False))
        A((HG, "heat_network.demand_mode", "热负荷模式", "given=给定曲线；degree_hour=度时法（随室外温度）", hn.demand_mode, "", ["given", "degree_hour"], "enum", False))
    DRG = "需求响应"
    if not sc.dr_events: A((DRG, "dr_events", "需求响应事件", "当前无 DR 事件（可在对话中说“晚高峰需求响应 40MW”）", "无", "", None, "info", False))
    for i, e in enumerate(sc.dr_events):
        P = f"dr_events.{i}."
        A((DRG, P + "kind", f"{e.name} 类型", f"{e.start}:00–{e.end}:00；reduce=削峰，increase=填谷", e.kind, "", ["reduce", "increase"], "enum", True))
        for f, n, mng, u, rg in [("start", "开始时刻", "", "h", [0, 23]), ("end", "结束时刻", "不含", "h", [1, 24]), ("request_mw", "申报/要求响应量", "", "MW", [0, 1e4]),
                                 ("price_cny_mwh", "补偿价格", "按实际响应量结算", "元/MWh", [0, 1e4]), ("shortfall_penalty_cny_mwh", "未达考核", "", "元/MWh", [0, 1e5])]:
            A((DRG, P + f, f"{e.name} {n}", mng, getattr(e, f), u, rg, "num", f in ("request_mw", "price_cny_mwh")))
        A((DRG, P + "baseline_method", f"{e.name} 基线方法", "plan=无 DR 时的优化计划；bau=无协同基线；given=给定", e.baseline_method, "", ["plan", "bau", "given"], "enum", True))
        A((DRG, P + "mandatory", f"{e.name} 强制达标", "True=响应量 ≥ 申报（硬约束）", e.mandatory, "", [True, False], "enum", False))
    CG = "碳"
    A((CG, "carbon_basis", "碳强度口径", "average=平均排放因子；marginal=边际排放因子（需提供边际曲线）", sc.carbon_basis, "", ["average", "marginal"], "enum", False))
    for r, prof in sc.carbon_profiles.items():
        A((CG, f"carbon_profiles.{r}", f"平均碳强度 [{r}]", "逐时平均碳强度", _stat(prof), "tCO2/MWh", [0, 2], "list24", False))
    for r, prof in sc.carbon_marginal_profiles.items():
        A((CG, f"carbon_marginal_profiles.{r}", f"边际碳强度 [{r}]", "逐时边际碳强度", _stat(prof), "tCO2/MWh", [0, 2], "list24", False))
    A((CG, "_heat_offset", "热碳抵扣", "总碳 = 电力碳 − 替代锅炉排放因子 × 余热供热量", "启用" if (hn and sc.thermal_mode == "coupled") else "不适用", "", None, "info", False))
    return _items_tail(sc, I)

def _items_tail(sc, I):
    A = I.append
    # 约束
    A(("约束", "min_green_share", "绿电占比下限", "外网购电 ≤ (1−s)×数据中心用电；空=不启用", sc.min_green_share, "", [0, 1], "optnum", False))
    A(("约束", "pv_curtail_penalty", "弃风弃光惩罚", "对未利用的新能源电量计罚（引导消纳，非真实费用）", sc.pv_curtail_penalty, "元/MWh", [0, 1e4], "num", True))
    if sc.jobs:
        A(("约束", "unserved_penalty_cny_mwh", "任务未完成惩罚", "截止前未完成的 IT 能量罚", sc.unserved_penalty_cny_mwh, "元/MWh", [0, 1e6], "num", True))
    A(("约束", "_soc_end", "日末 SOC 约束", "SOC_23 ≥ SOC_0（保证日循环可持续，固定启用）", "启用" if sc.storage else "不适用", "", None, "info", False))
    A(("约束", "_line_limit", "支路热稳定约束", "|P_l,t| ≤ 额定 × 回数（case14 为合成额定值）", "启用", "", None, "info", True))
    return I

def _check(v, rng, typ):
    if typ in ("num", "optnum") and rng and v is not None and isinstance(v, (int, float)):
        if not rng[0] <= v <= rng[1]: return f"超出合理范围 [{rng[0]}, {rng[1]}]"
    if typ == "enum" and rng and v not in rng: return f"应为 {rng}"
    return None

def param_sheet(s, solver_cfg=None):
    sc: Scenario = s.state["scenario"]
    from .tools import sdco_engine as eng
    errs = eng.validate(sc); groups = {}; counts = dict(用户指定=0, 智能体推断=0, 默认值=0, 案例假设=0, 公开资料=0); missing = []
    org = s.state.get("origin", {"kind": "default"}); act = s.state.get("build_actor", "智能体")
    otag = "用户指定" if act != "智能体" else "智能体推断"
    okind = {"preset": f"案例预设 {org.get('name')}", "default": "内置合成默认场景（IEEE14）", "agent_json": "智能体给出的完整 JSON", "user": "用户提供的场景"}.get(org.get("kind"), org.get("kind"))
    groups["网络"] = [dict(path="_origin", name="场景来源", meaning="本场景由谁、依据什么构建", value=okind, unit="", range=None, type="info", required=True, editable=False,
                           source=otag, source_note=(f"{act}选择；构建参数 {json.dumps(s.state.get('build_args', {}), ensure_ascii=False)}"), link=None, warning=None, missing=False)]
    counts[otag] += 1
    for g, path, name, meaning, val, unit, rng, typ, req in _items(sc):
        src = _source(s, sc, path); counts[src["tag"]] = counts.get(src["tag"], 0) + 1
        warn = _check(val, rng, typ)
        miss = req and (val is None or val == "")
        if miss: missing.append(name)
        groups.setdefault(g, []).append(dict(path=path, name=name, meaning=meaning, value=val, unit=unit, range=rng, type=typ, required=req,
                                             editable=typ in ("num", "enum", "optnum"), source=src["tag"], source_note=src.get("note", ""),
                                             link=src.get("link"), msg_ref=src.get("msg_ref"), warning=warn, missing=miss))
    cfg = {**DEFAULT_SOLVER, **(solver_cfg or s.state.get("solver_cfg") or {})}
    groups["求解器"] = [dict(path=f"solver.{k}", name=n, meaning=m, value=cfg[k], unit=u, range=r, type=t, required=False, editable=True,
                            source="用户指定" if k in (s.state.get("solver_cfg") or {}) else "默认值", source_note="求解配置（④）", link=None, warning=None, missing=False)
                       for k, n, m, u, r, t in [("solver", "求解器", "线性规划求解器（开源 HiGHS）", "", ["HiGHS"], "enum"),
                                               ("time_limit_s", "时间上限", "求解时间上限", "s", [1, 3600], "num"),
                                               ("run_baseline", "计算基线", "同时求解“无协同”基线用于对比", "", [True, False], "bool"),
                                               ("ac_check", "交流校核", "求解后用 pandapower 交流潮流校核", "", [True, False], "bool"),
                                               ("ac_hour", "校核时刻", "空=自动取总负荷峰值时刻", "h", [0, 23], "optnum"),
                                               ("attribution", "收益归因", "额外求解反事实情景以分解收益来源", "", [True, False], "bool")]]
    REN = {"电源": "能源配置", "储能": "蓄能配置"}
    G2 = {}
    for g, its in groups.items():
        for it in its:
            ng = REN.get(g, g)
            if any(it["path"].endswith(x) for x in ("tes_mwh_th", "tes_p_mw_th", "tes_loss_h")) or it["path"].startswith("heat_network.storage"): ng = "蓄能配置"
            G2.setdefault(ng, []).append(it)
    groups = G2
    order = ["网络", "能源配置", "蓄能配置", "数据中心与算力负荷", "散热方式", "热管理与冷却", "余热回收与供热", "余热品位与供热末端", "需求响应", "电价与碳", "碳", "约束", "求解器"]
    return dict(ok=True, scenario=sc.name, origin=s.state.get("origin", {"kind": "default"}), confirmed=bool(s.state.get("params_confirmed")),
                auto_run=bool(s.state.get("auto_run")), groups=[dict(name=g, items=groups.get(g, [])) for g in order if groups.get(g) or g not in ("热管理与冷却", "余热回收与供热", "需求响应", "碳", "散热方式", "余热品位与供热末端")],
                source_counts=counts, missing=missing, errors=errs, note=sc.note, sources=sc.sources,
                inferred=[dict(path=i["path"], name=i["name"], value=i["value"], note=i["source_note"]) for g in groups.values() for i in g if i["source"] in ("智能体推断", "默认值") and i["type"] != "info"][:80])

def set_param(s, path, value):
    if path.startswith("solver."):
        k = path.split(".", 1)[1]
        if k not in DEFAULT_SOLVER: raise ValueError(f"未知求解配置 {k}")
        s.state.setdefault("solver_cfg", {})[k] = value; return
    d = s.state["scenario"].model_dump(); ks = path.split("."); o = d
    for k in ks[:-1]: o = o[int(k)] if isinstance(o, list) else o[k]
    last = ks[-1]
    if isinstance(o, list): o[int(last)] = value
    else:
        if last not in o: raise ValueError(f"参数 {path} 不存在")
        o[last] = value
    sc = Scenario.model_validate(d)
    if last in ("cooling_mode", "liquid_frac") and ".thermal." in path and value is not None:   # 切换散热方式：按库写入温度边界/辅机/回收比例
        from .tools.cooling import apply_mode
        i = int(ks[1]); th = sc.data_centers[i].thermal
        if th.cooling_mode: apply_mode(th, th.cooling_mode, th.liquid_frac if (last == "liquid_frac" or th.cooling_mode == "hybrid") else None, cap_it=sc.data_centers[i].cap_it_mw)
    from .tools import sdco_engine as eng
    errs = eng.validate(sc)
    if errs: raise ValueError("修改后校验失败：" + "；".join(errs))
    s.state["scenario"] = sc; s.state["results"] = {}; s.state.pop("compare", None); s.state.pop("model_graph", None)
    s.state.setdefault("param_src", {})[path] = dict(tag="用户指定", note=f"用户在参数表修改（{time.strftime('%H:%M:%S')}）")
    s.state["params_confirmed"] = False

def mark_build_sources(s, args):
    """build_scenario 调用后记录来源：preset=案例；scenario JSON=智能体/用户；快捷参数=智能体推断，其余默认值。"""
    actor = s.state.get("_actor_build", "智能体")
    s.state["build_actor"] = actor; s.state["build_args"] = {k: v for k, v in args.items() if k != "scenario"}
    s.state["param_src"] = {}; s.state["params_confirmed"] = False
    if args.get("scenario"): s.state["origin"] = dict(kind="user" if actor != "智能体" else "agent_json")
    elif args.get("preset"): s.state["origin"] = dict(kind="preset", name=args["preset"])
    elif s.state.get("origin", {}).get("kind") in ("preset", "user") and s.state.get("model_edited"): pass
    else: s.state["origin"] = dict(kind="default")
    tag = "用户指定" if actor != "智能体" else "智能体推断"
    m = {"n_dc": "data_centers", "storage_mwh": "storage", "storage_bus": "storage", "storage_power_mw": "storage", "price_kind": "price_cny_kwh",
         "load_scale": "load_scale", "carbon_weight": "carbon_weight", "carbon_price_cny_t": "carbon_price_cny_t", "carbon_accounting": "carbon_accounting",
         "n_jobs": "jobs", "multi_region": "carbon_factor",
         "thermal": "thermal_mode", "tes": "thermal_mode", "heatwave": "outdoor_temp_c", "heat_recovery": "heat_network", "dr_mw": "dr_events", "dr_window": "dr_events"}
    for k, v in args.items():
        if k in m and v is not None:
            s.state["param_src"][m[k]] = dict(tag=tag, note=f"{'由对话文本解析' if tag == '智能体推断' else '用户输入'}：{k}={v}")

# ---------------- 数学模型 ----------------
def formulation(sc: Scenario, result: dict | None = None):
    nw = sc.network if sc.network_case == "custom" else None
    has_sto = bool(sc.storage); jobs = bool(sc.jobs); links = bool(sc.links)
    exp = bool(nw and any(e.export_max_mw > 0 for e in nw.ext_grids)); dem = bool(nw and any(e.demand_charge_cny_mw_day > 0 for e in nw.ext_grids))
    local = bool((nw and nw.gens) or sc.network_case == "case14"); ppa = any(p.ppa_price_cny_kwh for p in sc.pv)
    hydro = bool(nw and any(g.energy_mwh_day is not None for g in nw.gens)); green = sc.min_green_share is not None
    carbon = sc.carbon_weight*sc.carbon_price_cny_t > 0; lat = any(j.max_latency_ms is not None for j in sc.jobs)
    from .power_model import is_hardware as _is_hw
    hw = any(_is_hw(d) for d in sc.data_centers)
    vcc_on = (getattr(sc, "vcc_mode", "off") or "off") != "off"
    T = "\\sum_{t=0}^{"+str(sc.n_steps-1)+"}"
    cp = sc.thermal_mode == "coupled" and any(d.thermal is not None for d in sc.data_centers)
    tes = cp and any(d.thermal and d.thermal.tes_mwh_th > 0 for d in sc.data_centers)
    hr = cp and sc.heat_network is not None and any(d.thermal and d.thermal.hp_cap_mw_th > 0 for d in sc.data_centers)
    hst = hr and sc.heat_network.storage_mwh_th > 0
    dr = bool(sc.dr_events); drm = any(e.mandatory for e in sc.dr_events)
    off = "常数 PUE 模式（thermal_mode=constant_pue）"
    cmode = cp and any(d.thermal and d.thermal.cooling_mode for d in sc.data_centers)
    hg = hr and bool(sc.heat_network.terminal_type)
    cms = ",".join(sorted({d.thermal.cooling_mode for d in sc.data_centers if d.thermal and d.thermal.cooling_mode})) if cmode else ""
    obj = [
        dict(id="grid", name="外网购电费用", latex=T + "\\sum_{g\\in\\mathcal G^{ext}} (\\pi_{g,t}+m)\\,P_{g,t}", text="Σ_t Σ_外网 (电价+附加)×购电功率", active=True, reason="始终计入"),
        dict(id="local", name="本地机组发电成本", latex=T + "\\sum_{g\\in\\mathcal G^{loc}} c_g P_{g,t}", text="Σ 成本系数×机组出力", active=local, reason="存在本地可调度电源" if local else "无本地机组"),
        dict(id="export", name="外送售电收入（负项）", latex="-" + T + "\\sum_g \\pi^{ex}_{g,t} P^{ex}_{g,t}", text="−Σ 售电价×外送功率", active=exp, reason="外网允许反送" if exp else "未设置外送上限"),
        dict(id="curt", name="弃风弃光惩罚", latex="\\rho^{cur}" + T + "\\sum_k (\\bar P^{re}_{k,t}-P^{re}_{k,t})", text="惩罚系数×未利用新能源电量", active=bool(sc.pv), reason=f"ρ={sc.pv_curtail_penalty} 元/MWh（引导消纳的虚拟成本）"),
        dict(id="deg", name="储能循环损耗", latex="c^{deg}" + T + "\\sum_s (P^{ch}_{s,t}+P^{dis}_{s,t})", text="5 元/MWh×充放电量", active=has_sto, reason="有储能（避免同时充放）" if has_sto else "无储能"),
        dict(id="ppa", name="PPA/直供结算", latex=T + "\\sum_k \\pi^{ppa}_k \\tilde P^{re}_{k,t}", text="PPA 价×(可发电量 或 实际利用量)", active=ppa, reason="设置了 PPA 结算价" if ppa else "未设置 PPA"),
        dict(id="dem", name="需量电费", latex="\\sum_g d_g \\hat P_g,\\; \\hat P_g\\ge P_{g,t}", text="需量电价×日最大购电功率", active=dem, reason="两部制需量电价" if dem else "未设置需量电价"),
        dict(id="uns", name="任务未完成惩罚", latex="\\rho^{u}\\sum_j U_j", text="惩罚×未完成能量", active=jobs, reason="任务级模型" if jobs else "聚合批处理模型（无任务）"),
        dict(id="therm_pen", name="超推荐温度惩罚", latex="\\rho^{T}" + T + "\\sum_d \\epsilon_{d,t},\\;\\epsilon_{d,t}\\ge T^{in}_{d,t}-T^{rec}", text="入口温度超过 ASHRAE 推荐上限的软惩罚", active=cp, reason="热耦合：允许在推荐~允许区间短时运行但计罚" if cp else off),
        dict(id="heat_rev", name="余热售热收入（负项）", latex="-\\pi^{h}" + T + "H^{del}_t", text="−售热价×供热量", active=hr, reason="配置热泵与供热网" if hr else ("未接入供热网/无热泵" if cp else off)),
        dict(id="dr_rev", name="需求响应补偿（负项）/考核", latex="-" + T + "\\sum_e \\pi^{dr}_e R_{e,t}+\\rho^{dr}_e S_{e,t}", text="−补偿价×实际响应量 + 未达考核", active=dr, reason=f"{len(sc.dr_events)} 个 DR 事件" if dr else "无需求响应事件"),
        dict(id="carbon", name="碳成本（双目标）", latex="w\\,\\lambda" + T + "E_t", text="碳权重×碳价×排放", active=carbon, reason=f"w={sc.carbon_weight}, λ={sc.carbon_price_cny_t}" if carbon else "碳权重 w=0：纯成本目标"),
        dict(id="vcc", name="VCC 容量整形（灵活负荷）", latex="\\sigma" + T + "\\sum_d s_{d,t} Cap^{vcc}_{d,t}", text="信号(碳/电价/加权)×虚拟容量；day_ahead 不进主目标", active=vcc_on and sc.vcc_stage=="joint", reason=f"vcc_mode={sc.vcc_mode}, stage={sc.vcc_stage}" if vcc_on else "vcc_mode=off"),
    ]
    welfare=sc.objective_mode=="welfare"
    for term in obj:
        if term["id"]=="uns" and welfare: term.update(active=False,reason="welfare 用逐任务接纳价值替代未完成惩罚")
    obj.extend([
        dict(id="demand_value",name="接纳需求价值（负项）",latex=r"-\sum_j v_j(E_j-U_j)",text="逐任务异质需求报价；接纳和迁移均由优化器内生决定",active=welfare,reason=sc.objective_mode),
        dict(id="line_fee",name="线路绝对潮流服务费",latex=r"\sum_{l,t} c_l |F_{l,t}|",text="按绝对电力潮流收取服务成本",active=bool(sc.network and any(l.service_fee_cny_mwh for l in sc.network.lines)),reason="显式报价"),
        dict(id="migration_fee",name="迁移服务报价",latex=r"\sum_{e,t} c_e A_{e,t}",text="gross:双向之和；net:双向差的绝对值。容量仍按每方向约束",active=any(l.fee_cny_mwh for l in sc.links),reason=sc.migration_fee_basis)])
    C = [
        dict(id="bal", name="节点功率平衡（直流潮流）", latex="\\sum_{g\\in b}(P_{g,t}-P^{ex}_{g,t})+\\sum_{k\\in b}P^{re}_{k,t}-L_{b,t}-\\sum_{d\\in b}P^{dc}_{d,t}-\\sum_{s\\in b}(P^{ch}_{s,t}-P^{dis}_{s,t})=\\sum_{l} A_{lb}\\frac{\\theta_{f(l),t}-\\theta_{t(l),t}}{x_l}S_B", text="每母线每小时：注入 − 负荷 − 数据中心 − 储能充电 = 流出潮流", active=True, reason="DC-OPF 核心"),
        dict(id="line", name="支路热稳定", latex="|F_{l,t}|\\le \\bar F_l", text="|潮流| ≤ 额定", active=True, reason="线路/变压器容量"),
        dict(id="ref", name="参考相角", latex="\\theta_{ref,t}=0", text="每个电气岛参考母线相角为 0", active=True, reason="消除相角平移自由度"),
        dict(id="gen", name="电源出力上下限", latex="P^{min}_g\\le P_{g,t}\\le P^{max}_g", text="", active=True, reason=""),
        dict(id="hydro", name="水电日电量", latex="\\sum_t P_{g,t}\\le E^{day}_g", text="来水约束", active=hydro, reason="设置了日电量上限" if hydro else "无日电量上限"),
        dict(id="re", name="新能源可用出力", latex="0\\le P^{re}_{k,t}\\le \\mathrm{Cap}_k\\,\\alpha_{k,t}", text="利用 ≤ 装机×出力系数（可弃）", active=bool(sc.pv), reason=""),
        dict(id="itcap", name="数据中心 IT 容量", latex="P^{int}_{d,t}+P^{bt}_{d,t}\\le \\mathrm{Cap}^{IT}_d", text="交互+批处理 ≤ IT 容量", active=True, reason=""),
        dict(id="pwr", name="IT 硬件功率（idle+动态 / PDU）", latex="P^{IT}_{d,t}=P^{idle}_d+(P^{peak}_d-P^{idle}_d) u_{d,t}", text="缺省 identity：P_IT=工作功率；启用后电气 IT 与发热用 P_IT，constant_pue 下冷却=PUE×P_IT", active=hw, reason="某 DC 设置了 idle_dynamic/pdu_pwl" if hw else "全部 identity（旧行为）"),
        dict(id="vccc", name="VCC 虚拟容量", latex="P^{bt}_{d,t}\\le Cap^{vcc}_{d,t},\\;\\sum_t Cap^{vcc}_{d,t}\\ge B_d", text="灵活负荷不超过虚拟容量；日总量守恒", active=vcc_on, reason=f"{sc.vcc_mode}/{sc.vcc_stage}" if vcc_on else "vcc_mode=off"),
        dict(id="batch", name="批处理日能量守恒", latex="\\sum_t P^{bt}_{d,t}=B_d-\\sum_{e,t}M_{d,e,t}+(1+\\kappa)\\sum_{e,t}M_{e,d,t}", text="批处理总量守恒（迁出减、迁入加迁移能耗）", active=not jobs, reason="聚合批处理模型" if not jobs else "被任务级约束替代"),
        dict(id="job", name="任务能量与窗口", latex="\\sum_{d,t\\in[r_j,\\delta_j)}p_{j,d,t}+U_j=E_j,\\quad \\sum_d p_{j,d,t}\\le \\bar p_j", text="任务在释放~截止窗口内完成能量，单小时功率有上限", active=jobs, reason="任务级模型" if jobs else "无任务"),
        dict(id="mig", name="迁移上限", latex="\\sum_e M_{d,e,t}\\le \\bar M,\\; \\sum_{e,t}M_{d,e,t}\\le \\sigma B_d", text=f"每小时 ≤ {sc.mig_max_mw} MW；日 ≤ {sc.mig_day_share}×批处理", active=len(sc.data_centers) > 1, reason="多数据中心可迁移" if len(sc.data_centers) > 1 else "单数据中心无迁移"),
        dict(id="link", name="链路带宽", latex="M_{d,e,t}\\le BW_{d,e}", text="仅沿已定义链路迁移，且不超带宽", active=links, reason="定义了迁移链路" if links else "未定义链路（不限链路）"),
        dict(id="lat", name="时延敏感过滤", latex="p_{j,e,t}=0\\;\\text{if}\\;\\ell_{d,e}>\\bar\\ell_j", text="时延敏感任务不可迁到超时延链路", active=lat, reason="存在时延敏感任务" if lat else "无时延敏感任务"),
        dict(id="sto", name="储能功率/SOC/动态", latex="SOC_{s,t}=SOC_{s,t-1}+\\eta^{ch}P^{ch}_{s,t}-P^{dis}_{s,t}/\\eta^{dis},\\; \\underline{SOC}\\le SOC\\le\\overline{SOC},\\; P^{ch},P^{dis}\\le \\bar P_s", text="能量递推 + 上下限 + 功率限", active=has_sto, reason="有储能" if has_sto else "无储能"),
        dict(id="soc_end", name="日末 SOC", latex="SOC_{s,23}\\ge SOC_{s,0}", text="日末不低于初值", active=has_sto, reason="保证可持续日循环" if has_sto else "无储能"),
        dict(id="dcelec", name="数据中心电功率（动态 PUE）", latex="P^{dc}_{d,t}=P^{IT}_{d,t}(1+\\phi_d)+Q^{ch}_{d,t}\\left(\\tfrac{1}{\\mathrm{COP}_{d,t}}+a_d\\right)+\\tfrac{Q^{fc}_{d,t}}{\\mathrm{COP}^{fc}_d}+\\tfrac{H^{hp}_{d,t}}{\\mathrm{COP}^{hp}_d},\\;\\mathrm{COP}_{d,t}=\\mathrm{clip}(\\mathrm{COP}^{ref}-k(T^{out}_t-25))", text="电网侧 = IT×(1+其他损耗) + 冷机电耗(COP 随室外温度逐时预计算) + 自然冷却风机水泵 + 热泵；常数 PUE 模式下 = PUE×IT", active=True, reason=("热耦合：发热用实际 P_IT；COP 逐时预计算 → 线性" if cp else "常数 PUE：P = PUE×P_IT") + ("; 硬件功率层启用" if hw else "")),
        dict(id="rc", name="两节点 RC 热平衡（隐式欧拉）", latex="C^a_d(T^{in}_{d,t}-T^{in}_{d,t-1})=P^{IT}_{d,t}(1+\\tfrac{\\phi_d}{2})-Q^{room}_{d,t}-UA^{am}_d(T^{in}_{d,t}-T^m_{d,t})+UA^{env}_d(T^{out}_t-T^{in}_{d,t}),\\; C^m_d(T^m_{d,t}-T^m_{d,t-1})=UA^{am}_d(T^{in}_{d,t}-T^m_{d,t})", text="IT 发热进入空气节点，冷却排热；建筑/机架热质量为慢节点（虚拟储冷）", active=cp, reason="热耦合模式" if cp else off),
        dict(id="qroom", name="排热构成", latex="Q^{room}_{d,t}=Q^{ch}_{d,t}-Q^{tes,c}_{d,t}+Q^{fc}_{d,t}+Q^{tes,d}_{d,t}+H^{hp}_{d,t}(1-1/\\mathrm{COP}^{hp}_d)", text="冷机（扣除给蓄冷罐充冷）+ 自然冷却 + 蓄冷放冷 + 热泵蒸发侧取热", active=cp, reason="热耦合模式" if cp else off),
        dict(id="tsafe", name="热安全：入口温度边界（硬）", latex="T^{min}_d\\le T^{in}_{d,t}\\le T^{allow}_d", text="ASHRAE A1：18 ≤ T_in ≤ 32°C（可配置）", active=cp, reason="热安全硬约束" if cp else off),
        dict(id="tramp", name="热安全：温度变化率（硬）", latex="|T^{in}_{d,t}-T^{in}_{d,t-1}|\\le \\dot T^{max}_d", text="≤ 5 K/h", active=cp, reason="热安全硬约束" if cp else off),
        dict(id="n1", name="热安全：冷机 N+1 可用冷量（硬）", latex="Q^{ch}_{d,t}\\le \\bar Q^{ch}_d\\tfrac{n_d-1}{n_d}", text="保留 1 台备用", active=cp, reason="热安全硬约束" if cp else off),
        dict(id="itcool", name="热安全：IT ≤ 可用冷却能力（硬）", latex="P^{IT}_{d,t}\\le \\bar Q^{ch,N+1}_d+\\bar Q^{fc}_d f_{d,t}+\\bar Q^{tes}_d(+\\bar H^{hp}_d(1-1/\\mathrm{COP}^{hp}))", text="稳态充足性 + 末端排热 ≤ CRAH 能力", active=cp, reason="热安全硬约束" if cp else off),
        dict(id="free", name="自然冷却可用量", latex="Q^{fc}_{d,t}\\le \\bar Q^{fc}_d\\,\\mathrm{clip}\\!\\left(\\tfrac{T^{0}-T^{out}_t}{T^{0}-T^{full}},0,1\\right)", text="室外越冷可用越多（逐时预计算）", active=cp, reason="热耦合模式" if cp else off),
        dict(id="precool", name="虚拟储冷（预冷）日末约束", latex="T^{in}_{d,23}\\le T^0_d,\\;T^m_{d,23}\\le T^0_d", text="不透支热惯性：日末温度不高于初值", active=cp, reason="热耦合优化（基线为定送风温度）" if cp else off),
        dict(id="tes", name="蓄冷罐（显式储冷）", latex="S^{c}_{d,t}=(1-\\ell^c)S^c_{d,t-1}+Q^{tes,c}_{d,t}-Q^{tes,d}_{d,t},\\;S^c_{d,23}\\ge S^c_{d,0}", text="容量/功率/损失", active=tes, reason="配置蓄冷罐" if tes else ("无蓄冷罐" if cp else off)),
        dict(id="hp", name="余热回收热泵", latex="H^{hp}_{d,t}\\le \\bar H^{hp}_d,\\;H^{hp}_{d,t}(1-1/\\mathrm{COP}^{hp})\\le \\gamma_d P^{IT}_{d,t}", text="供热能力、可回收余热比例", active=hr, reason="配置热泵与供热网" if hr else ("无供热网/热泵" if cp else off)),
        dict(id="heatbal", name="供热网热平衡 + 虚拟储热", latex="(1-\\ell^{pipe})\\sum_d H^{hp}_{d,t}+H^{s,d}_t-H^{s,c}_t=H^{del}_t\\le H^{dem}_t,\\;S^h_t=(1-\\ell^h)S^h_{t-1}+H^{s,c}_t-H^{s,d}_t", text="热网惯性/蓄热罐作为虚拟储热", active=hr, reason=("含热网蓄热" if hst else "无蓄热") if hr else ("无供热网" if cp else off)),
        dict(id="cmode", name="散热方式：分段线性 COP + 液冷比例加权", latex="\\mathrm{COP}_{d,t}=\\Big(\\tfrac{\\lambda_d}{\\mathrm{PWL}^{liq}(T^{db}_t)}+\\tfrac{1-\\lambda_d}{\\mathrm{PWL}^{air}(T^{wb|db}_t)}\\Big)^{-1},\\; f_{d,t}=\\lambda_d f^{liq}_{t}+(1-\\lambda_d) f^{air}_t,\\; W_{d,t}=\\mathrm{WUE}_{d,t}P^{IT}_{d,t}", text="冷机 COP 对室外干/湿球温度分段线性；自然冷却比例按方式阈值；液冷比例 λ 加权；耗水=WUE×IT（逐时预计算，仍为 LP）", active=cmode, reason=f"散热方式：{cms}" if cmode else "未选择散热方式（通用 COP 参数）"),
        dict(id="csafe", name="液冷热安全：供液温度/芯片温度代理", latex="T^{sup}_{min}\\le T^{sup}_{d,t}\\le T^{sup}_{max},\\; T^{chip}_{d,t}\\approx T^{sup}_{d,t}+\\Delta T^{chip}\\,P^{IT}_{d,t}/\\bar P^{IT}_d\\le 85^\\circ C", text="液冷模式下 RC 主节点代表供液温度（W40/W45 等级），芯片温度代理事后校核", active=cmode, reason="液冷/混合" if cmode else "—"),
        dict(id="hpcop", name="热泵 COP（卡诺效率，按温升逐时）", latex="\\mathrm{COP}^{hp}_{d,t}=\\eta\\frac{T^{sink}_t+273.15}{T^{sink}_t-(T^{src}_d-\\Delta T^{ev})},\\;T^{sink}_t=\\min(T^{plant}_t,T^{hp}_{max});\\;\\mathrm{COP}=40\\;\\text{if}\\;T^{src}_d-\\Delta T^{hx}\\ge T^{plant}_t", text="源温度由散热方式决定（风冷 32-36、冷板 50、浸没 55°C）；源温足够时直接板换", active=hg, reason="余热品位模型" if hg else "常数 COP（未设置末端类型）"),
        dict(id="tterm", name="末端供水温度（质调节）+ 管网温降", latex="T^{req}_t=T^{min}+(T^{max}-T^{min})\\,\\mathrm{clip}\\!\\left(\\tfrac{15-T^{out}_t}{15-T^{out}_{des}},0,1\\right),\\;T^{plant}_t=T^{req}_t+L\\,\\delta T,\\;\\ell^{pipe}=\\ell_0+L\\,\\ell_{km}", text="末端要求供水随室外温度；站出口须覆盖沿程温降", active=hg, reason=f"末端 {sc.heat_network.terminal_type}，L={sc.heat_network.pipe_length_km} km" if hg else "—"),
        dict(id="boost", name="温度达标（硬）：调峰补热", latex="H^{b}_t(1-f_t)=f_t\\sum_d H^{hp}_{d,t},\\;f_t=\\mathrm{clip}\\!\\left(\\tfrac{T^{plant}_t-T^{hp}_{max}}{T^{plant}_t-T^{ret}},0,0.95\\right),\\;(1-\\ell^{pipe})(\\textstyle\\sum_d H^{hp}_{d,t}+H^b_t)+H^{s,d}_t-H^{s,c}_t=H^{del}_t", text="热泵出水温度不足部分由燃气锅炉/电加热补到要求温度（按混水能量比例），成本与碳计入", active=hg, reason=f"补热方式 {sc.heat_network.booster}" if hg else "—"),
        dict(id="dr", name="需求响应量", latex="R_{e,t}\\le \\pm(B_{e,t}-\\sum_{d\\in e}P^{dc}_{d,t}),\\;R_{e,t}\\le\\min(R^{req}_e,\\bar R_e),\\;S_{e,t}\\ge R^{req}_e-R_{e,t}", text="相对基线的削减（或填谷增加）量；基线 B 由 plan/bau/given 方法得到", active=dr, reason=f"{len(sc.dr_events)} 个事件；基线方法 " + ",".join(sorted({e.baseline_method for e in sc.dr_events})) if dr else "无 DR 事件"),
        dict(id="drm", name="DR 强制达标", latex="R_{e,t}\\ge R^{req}_e", text="", active=drm, reason="mandatory=True" if drm else "未设强制"),
        dict(id="carbon_bal", name="电-热碳核算", latex="E_t=\\sum_d CI_{d,t}P^{dc}_{d,t}-\\mathrm{EF}^{boiler}H^{del}_t", text="电力碳（逐时平均/边际因子）− 余热替代锅炉的热碳抵扣", active=True, reason=("含热碳抵扣；" if hr else "") + f"口径 {sc.carbon_accounting}/{sc.carbon_basis}"),
        dict(id="green", name="绿电占比下限", latex="\\sum_{t,g\\in ext}P_{g,t}\\le(1-s)\\sum_{d,t}P^{dc}_{d,t}", text=f"s={sc.min_green_share}", active=green, reason="设置了绿电占比考核" if green else "未设置"),
        dict(id="peak", name="需量峰值", latex="\\hat P_g\\ge P_{g,t}", text="日最大购电功率", active=dem, reason="两部制" if dem else "无需量电价"),
    ]
    V = [dict(sym="P_{g,t}", name="电源/外网出力", unit="MW", active=True), dict(sym="P^{ex}_{g,t}", name="外送功率", unit="MW", active=exp),
         dict(sym="\\theta_{b,t}", name="母线相角", unit="rad", active=True), dict(sym="P^{re}_{k,t}", name="新能源利用功率", unit="MW", active=bool(sc.pv)),
         dict(sym="P^{bt}_{d,t}", name="批处理 IT 功率", unit="MW", active=True), dict(sym="M_{d,e,t}", name="跨中心迁移功率", unit="MW", active=len(sc.data_centers) > 1 and not jobs),
         dict(sym="p_{j,d,t},U_j", name="任务功率 / 未完成能量", unit="MW / MWh", active=jobs),
         dict(sym="P^{ch},P^{dis},SOC", name="储能充放电与荷电", unit="MW / MWh", active=has_sto), dict(sym="\\hat P_g", name="日最大购电", unit="MW", active=dem),
         dict(sym="T^{in}_{d,t},T^m_{d,t}", name="入口(空气)温度 / 结构温度", unit="°C", active=cp), dict(sym="Q^{ch},Q^{fc}", name="冷机冷量 / 自然冷却冷量", unit="MW_th", active=cp),
         dict(sym="Q^{tes,c},Q^{tes,d},S^c", name="蓄冷充/放冷与蓄冷量", unit="MW_th / MWh_th", active=tes), dict(sym="\\epsilon_{d,t}", name="超推荐温度量", unit="K", active=cp),
         dict(sym="H^{hp},H^{del},S^h", name="热泵供热 / 售热 / 热网蓄热", unit="MW_th / MWh_th", active=hr), dict(sym="R_{e,t},S_{e,t}", name="DR 响应量 / 缺额", unit="MW", active=dr)]
    Tnote = r"\Delta t"
    for term in obj:
        if term["id"] not in ["dem","uns","demand_value"]:
            term["latex"] = r"\Delta t\left("+term["latex"]+r"\right)"
            term["text"] += "；功率/速率项乘Δt积分"
    dt_equations = {
        "hydro":r"\Delta t\sum_t P_{g,t}\le E^{day}_g",
        "batch":r"\Delta t\sum_t P^{bt}_{d,t}=B_d-\Delta t\sum_{e,t}M_{d,e,t}+(1+\kappa)\Delta t\sum_{e,t}M_{e,d,t}",
        "job":r"\Delta t\sum_{d,t}p_{j,d,t}+U_j=E_j \quad (energy\ mode)",
        "sto":r"S_t=S_{t-1}+\Delta t(\eta^{ch}P^{ch}_t-P^{dis}_t/\eta^{dis})",
        "rc":r"C^a(T^a_t-T^a_{t-1})=\Delta t[P^{IT}_t(1+\phi/2)-Q^{room}_t-UA^{am}(T^a_t-T^m_t)+UA^{env}(T^{out}_t-T^a_t)],\ C^m(T^m_t-T^m_{t-1})=\Delta t UA^{am}(T^a_t-T^m_t)",
        "tramp":r"|T_t-T_{t-1}|\le\Delta t\dot T^{max}",
        "tes":r"S^c_t=(1-\ell_h)^{\Delta t}S^c_{t-1}+\Delta t(Q^c_t-Q^d_t)",
        "heatbal":r"inflow+storageDis=delivered+outflow+storageCh;\ S_t=(1-\ell_h)^{\Delta t}S_{t-1}+\Delta t(H^{ch}_t-H^{dis}_t)",
        "soc_end":r"S_{N-1}\ge S_{initial}",
        "precool":r"T^a_{N-1}\le T^0,\ T^m_{N-1}\le T^0"
    }
    for row in C:
        row["latex"]=dt_equations.get(row["id"],row["latex"])
        row["text"]=row["text"].replace("每小时","每步").replace("单小时","每步")
        if row["id"]=="job" and sc.jobs and all(j.execution_mode=="continuous" for j in sc.jobs): row["active"]=False
    continuous=any(j.execution_mode=="continuous" for j in sc.jobs)
    C.append(dict(id="integer_state_flow",name="整数连续任务状态守恒/截止期",latex=r"y_{arc}\in\{0,1\};\ \sum out(y)=\sum in(y);\ p_{j,d,t}=P_j\sum productive(y);\ U_j=E_j(1-complete_j)",text="同站点连续固定功率；取消丢弃全部进度返回积压、显式重启等待；required强制截止完成；初始进度+执行=goodput+取消损失+截止损失",active=continuous,reason="binary_state_flow_v1；不是作者完整滚动策略"))
    obj.append(dict(id="cancel",name="取消操作费用",latex=r"\sum_j c^{cancel}_j N^{cancel}_j",text="逐次取消费用；已经消耗的电量照实计费；goodput与浪费分账",active=continuous,reason="显式任务参数"))
    V.append(dict(sym="y_{arc}",name="任务离散状态转移",unit="binary",active=continuous))
    size = None
    if result and result.get("solver"): size = {k: result["solver"][k] for k in ("n_vars", "n_fixed_vars", "n_constraints", "time_s", "status", "objective", "gap_pct", "name", "problem")}
    return dict(ok=True, problem=("MILP（整数连续任务）" if continuous else "多时段直流最优潮流（DC-OPF）线性规划")+"：min 目标函数 s.t. 约束", horizon=f"{sc.hours} h，步长 {sc.dt_hours} h，{sc.n_steps} 点（确定性日调度）", time_axis=dict(dt_hours=sc.dt_hours,steps=sc.n_steps,integration="所有能量/热量/碳/电度费用=功率或速率×dt；ramp单位每物理小时"), integer_task_model="binary_state_flow_v1：连续固定功率，取消丢弃进度，deadline/重启等待以物理小时计", migration_cleanup=sc.migration_cleanup,
                objective=obj, constraints=C, variables=V, size=size, objective_mode=sc.objective_mode, network_domain=sc.network_domain, angle_bounds_rad=None if sc.network_domain=="paper_abstract" else [-3.141592653589793,3.141592653589793], lifecycle_enabled=sc.lifecycle_enabled, lifecycle_note="独立事后分账，不改变运行碳目标或调度",
                baseline_note=("整数任务基线只限制本地站点，仍按连续/取消物理语义求解，不冒称均匀可分或原作者策略。" if continuous else "")+"基线（无协同）：批处理在本地全天均匀运行、无迁移、不使用储能（离网孤岛必需储能除外）；用同一模型求解以保证可比。",
                ac_note="交流校核：取 DC-OPF 结果某一时刻（默认总负荷峰值），用 pandapower 牛顿-拉夫逊交流潮流计算电压/负载/网损，检验线性化误差。",
                approximations=["热模型为两节点集总 RC（空气+结构），忽略机房内气流组织/热点分布（入口温度取机房平均）", "冷机 COP 用室外干球温度线性近似并逐时预计算（不随部分负荷率变化），保持 LP 线性",
                                "自然冷却可用量按室外温度线性插值；冷却塔/水泵电耗按冷量比例", "热泵 COP：设置末端类型时按卡诺效率法逐时预计算（随温升），否则取常数；热网为单节点稳态热平衡+等效蓄热，管网温降/热损按长度线性（忽略输送时延与水力）", "液冷/混合按液冷比例对 COP（调和）与自然冷却比例（线性）加权；湿球温度按 Stull 公式由干球+相对湿度估算",
                                "DR 基线 plan 法需先求解一次无 DR 的优化计划；响应量对参与 DC 合计核算", "PUE 不含热泵用电（单独报告），ERF=回收热/IT 电量"] if cp or dr else [],
                symbols={"π": "电价", "m": "购电附加", "PUE": "能效比", "κ": "迁移能耗系数", "σ": "日迁移比例", "ρ": "惩罚系数", "w,λ": "碳权重、碳价"})

# ---------------- KPI 定义 ----------------
KPI_DEF = {
    "total_objective_cny": ("目标函数值", "元/日", "优化模型最小化的总值 = 各项成本 + 惩罚（+碳项）", "J = Σ 目标项"),
    "cost_cny": ("总成本（不含碳项）", "元/日", "目标函数扣除碳成本项", "J − w·λ·E"),
    "energy_cost_cny": ("发购电费用", "元/日", "外网购电 + 本地发电 − 外送收入 + PPA", "Σ_t hour_cost_t"),
    "emissions_tco2": ("碳排放", "tCO2/日", "按核算口径统计的排放", "Σ_t CI_t × 用电_t"),
    "pv_curtail_mwh": ("弃风弃光电量", "MWh", "新能源可发但未利用的电量", "Σ (可用 − 利用)"),
    "pv_util_pct": ("新能源利用率", "%", "利用电量 / 可用电量", "Σ利用/Σ可用×100"),
    "max_line_loading_pct": ("最大支路负载率(DC)", "%", "DC-OPF 下最大 |潮流|/额定", "max |F|/F̄×100"),
    "dc_energy_mwh": ("数据中心用电量", "MWh", "电网侧（含 PUE）", "Σ PUE×(交互+批处理)"),
    "dc_avg_price_cny_kwh": ("数据中心平均电价", "元/kWh", "数据中心用电按分时电价加权平均", "Σ P_dc×π / Σ P_dc"),
    "dc_peak_mw": ("数据中心峰值功率", "MW", "数据中心电网侧总功率最大值", "max_t Σ_d P_dc"),
    "migrated_mwh": ("跨中心迁移量", "MWh", "迁出的 IT 能量", "Σ M"),
    "grid_import_mwh": ("外网购电量", "MWh", "从外网受入电量", "Σ P_ext"),
    "grid_export_mwh": ("外送电量", "MWh", "", "Σ P_ex"),
    "green_share_pct": ("绿电占比", "%", "1 − (外网+化石)/总用电", "1−(购电+化石)/负荷"),
    "jobs_deadline_met_pct": ("任务按期完成率", "%", "截止前完成的任务占比", "#按期/#任务"),
    "pue_avg": ("动态 PUE（日均）", "", "(IT + 冷却 + 其他)/IT，逐时随室外温度与调度变化（不含热泵）", "Σ(P_IT+P_cool+P_oth)/ΣP_IT"),
    "pue_max": ("动态 PUE（最大）", "", "日内最大逐时 PUE", "max_t PUE_t"),
    "tin_max_c": ("最高入口温度", "°C", "所有数据中心入口温度最大值（热安全）", "max T_in"),
    "thermal_margin_k": ("热安全裕度", "K", "允许上限 − 最高入口温度（≥0 为安全）", "T_allow − max T_in"),
    "cooling_mwh": ("冷却用电量", "MWh", "冷机+冷却塔水泵+自然冷却风机", "Σ P_cool"),
    "wue_l_kwh": ("WUE 水利用效率", "L/kWh", "冷却耗水/IT 电量（蒸发冷却/冷却塔模式显著）", "Σ W/Σ E_IT"),
    "water_m3": ("冷却耗水", "m³/日", "", "Σ_t P_IT·WUE_t"),
    "heat_cost_cny_gj": ("余热供热成本", "元/GJ", "(热泵/补热电费 + 燃气补热费)/供热量", "(C_hp+C_boost)/(3.6·ΣH)"),
    "terminal_margin_k": ("末端供水温度裕度", "K", "无补热时 末端实际供水 − 末端要求供水 的最小值（≥0 满足）", "min_t(T_ach−ΔT_pipe−T_req)"),
    "heat_verdict": ("余热供暖可行性", "", "技术/经济/碳 综合判定", "可行/有条件可行/不可行"),
    "heat_boost_mwh": ("调峰补热量", "MWh_th", "温度不足由锅炉/电加热补足的热量", "Σ H_boost"),
    "heat_delivered_mwh": ("终端实际用热量", "MWh_th", "终端用户实际取热；售热与锅炉抵扣口径。不同于管段到达量（到达后可储热/产生储热损耗）", "Σ H_terminal · dt"),
    "heat_revenue_cny": ("售热收入", "元/日", "", "π_h × Σ H_del"),
    "dr_delivered_mwh": ("需求响应量", "MWh", "相对基线的实际削减/填谷电量", "Σ R"),
    "dr_requested_mwh": ("需求响应要求量", "MWh", "", "Σ R_req"),
    "dr_revenue_cny": ("需求响应收益", "元/日", "", "Σ π_dr R"),
    "carbon_elec_tco2": ("电力碳排放", "tCO2", "数据中心用电×逐时碳强度", "Σ CI·P_dc"),
    "carbon_heat_offset_tco2": ("热碳抵扣", "tCO2", "余热替代锅炉减少的排放", "EF_boiler × Σ H_del"),
}

def kpi_cards(k: dict, kb: dict | None):
    out = []
    for key, (n, u, d, f) in KPI_DEF.items():
        if key not in k: continue
        b = kb.get(key) if kb else None; v = k[key]
        out.append(dict(key=key, name=n, unit=u, definition=d, formula=f, value=v, baseline=b,
                        delta=(round(v - b, 3) if isinstance(b, (int, float)) and isinstance(v, (int, float)) else None)))
    return out

TERM_CN = dict(grid_purchase="外网购电", local_gen="本地发电", export_revenue="外送收入(负)", curtail_penalty="弃电惩罚",
               storage_degradation="储能损耗", ppa="PPA 结算", demand_charge="需量电费", unserved_penalty="任务未完成惩罚", carbon="碳成本项", physical_line_service="线路服务费", migration_service="迁移服务费", admitted_demand_value="接纳需求价值（负项）",
               thermal_penalty="超推荐温度惩罚", heat_revenue="售热收入(负)", dr_revenue="需求响应收益(负)")

def attribution(sc, base, opt, solver_opts=None):
    """顺序反事实分解：基线 → 仅时移 → +迁移 → +储能（=完整优化）。"""
    from .tools import sdco_engine as eng
    from .tools import thermal as _th0
    A = base["objective"]; D = opt["objective"]
    lv0 = dict(precool=False, tes=False, heat=False, dr=False) if (_th0.active(sc) or sc.dr_events) else None
    B = eng.solve(sc, optimize=True, use_storage=False, no_migration=True, solver_opts=solver_opts, levers=lv0)["objective"]
    Cc = eng.solve(sc, optimize=True, use_storage=False, solver_opts=solver_opts, levers=lv0)["objective"] if len(sc.data_centers) > 1 else B
    total = A - D
    parts = [dict(id="shift", name="负荷时移（批处理/任务移到低价、风光充裕时段）", saving=A - B),
             dict(id="migration", name="跨中心迁移", saving=B - Cc), dict(id="storage", name="储能套利/削峰", saving=Cc - D)]
    from .tools import thermal as _th
    if _th.active(sc) or sc.dr_events:   # 耦合杠杆：+储能后依次放开 虚拟储冷(预冷+蓄冷) → 余热回收 → 需求响应
        off = dict(precool=False, tes=False, heat=False, dr=False)
        seq = [("virtual_cold", "虚拟储冷（预冷热惯性 + 蓄冷罐）", dict(precool=True, tes=True)), ("heat", "余热回收供热（含虚拟储热）", dict(heat=True)), ("dr", "需求响应补偿", dict(dr=True))]
        prev = eng.solve(sc, optimize=True, solver_opts=solver_opts, levers=dict(off))["objective"]
        parts[-1]["saving"] = Cc - prev; cur = dict(off)
        for pid, nm, upd in seq:
            cur.update(upd)
            if pid == "dr" and not sc.dr_events: continue
            if pid == "heat" and not _th.heat_dcs(sc): continue
            if pid == "virtual_cold" and not _th.active(sc): continue
            val = eng.solve(sc, optimize=True, solver_opts=solver_opts, levers=dict(cur))["objective"] if cur != {k: True for k in off} else D
            parts.append(dict(id=pid, name=nm, saving=prev - val)); prev = val
        if abs(prev - D) > 1e-3: parts.append(dict(id="interaction", name="交互/其余", saving=prev - D))
    for p in parts: p["saving"] = round(p["saving"], 1); p["share_pct"] = round(p["saving"]/total*100, 1) if abs(total) > 1e-6 else 0.0
    terms = []
    bt, ot = base.get("cost_terms", {}), opt.get("cost_terms", {})
    for k in ot:
        terms.append(dict(term=k, name=TERM_CN.get(k, k), baseline=round(bt.get(k, 0), 1), optimized=round(ot[k], 1), saving=round(bt.get(k, 0) - ot[k], 1)))
    bdf, odf = base["df"], opt["df"]
    phys = dict(curtail_reduction_mwh=round(base["curtail_mwh"] - opt["curtail_mwh"], 2),
                grid_import_reduction_mwh=round(float(bdf.grid_import_MW.sum() - odf.grid_import_MW.sum()), 2) if "grid_import_MW" in odf else None,
                peak_import_reduction_mw=round(float(bdf.grid_import_MW.max() - odf.grid_import_MW.max()), 2) if "grid_import_MW" in odf else None,
                storage_discharge_mwh=round(float(sum(odf[f"{s}_dis"].sum() for s in opt["storage"])), 2),
                migrated_mwh=round(float(odf[[c for c in odf if c.endswith("_mig_out")]].sum().sum()), 2))
    th = opt.get("thermal") or {}
    if th:
        phys.update(pue_avg_baseline=_pue(base), pue_avg_optimized=_pue(opt),
                    cooling_reduction_mwh=round(sum(x["cooling_mwh"] for x in (base.get("thermal") or {}).get("dcs", {}).values()) - sum(x["cooling_mwh"] for x in th["dcs"].values()), 2),
                    heat_delivered_mwh=(th.get("heat") or {}).get("delivered_mwh", 0.0), heat_carbon_offset_t=(th.get("heat") or {}).get("carbon_offset_t", 0.0))
    if opt.get("dr"): phys.update(dr_delivered_mwh=round(sum(e["delivered_mwh"] for e in opt["dr"]), 2), dr_requested_mwh=round(sum(e["requested_mwh"] for e in opt["dr"]), 2))
    top = max(parts, key=lambda p: p["saving"])
    txt = (f"相对基线，目标函数降低 {total:,.0f} 元/日。按“基线→仅时移→+迁移→+储能”顺序反事实分解："
           + "；".join(f"{p['name']} {p['saving']:,.0f} 元（{p['share_pct']}%）" for p in parts)
           + f"。最大贡献来自「{top['name']}」。弃电减少 {phys['curtail_reduction_mwh']} MWh，对应弃电惩罚项变化 "
           + f"{next((t['saving'] for t in terms if t['term'] == 'curtail_penalty'), 0):,.0f} 元（惩罚为引导性虚拟成本，非真实支出）。")
    return dict(total_saving=round(total, 1), steps=dict(baseline=round(A, 1), shift_only=round(B, 1), shift_migration=round(Cc, 1), full=round(D, 1)),
                parts=parts, terms=terms, physical=phys, text=txt,
                method="顺序反事实：分别求解“允许时移但禁用迁移与储能”“允许时移+迁移但禁用储能”两个附加 LP（热耦合/DR 场景再依次放开 虚拟储冷→余热→DR）；各杠杆贡献 = 相邻情景目标差。分解次序会影响交互效应的归属。")

def _pue(r):
    th = r.get("thermal")
    if not th: return None
    it = sum(x["it_mwh"] for x in th["dcs"].values())
    return round(sum(x["pue_avg"]*x["it_mwh"] for x in th["dcs"].values())/it, 4) if it else None

def warnings(sc, ac=None, res=None):
    W = []
    if sc.network_domain == "paper_abstract": W.append("论文抽象网络：相角无物理箱约束；不适用交流校核，不代表物理安全。")
    if sc.objective_mode == "welfare": W.append("福利目标：接纳任务价值减发电、线路和迁移服务成本，不是传统现金成本。")
    if sc.synthetic: W.append("场景使用合成示例数据（SYNTHETIC），数值仅用于方法演示。")
    if sc.sources.get("假设"): W.append("案例假设：" + sc.sources["假设"])
    if sc.thermal_mode == "coupled":
        W.append("热耦合模型：两节点集总 RC + 线性 COP(T_out) 近似，入口温度为机房平均值，未刻画局部热点；热安全裕度应在 CFD/实测中复核。")
        th = (res or {}).get("thermal") if res else None
        if th and th.get("violations"): W.append("⚠️ 热安全越限：" + "；".join(th["violations"]))
        elif th: W.append("热安全硬约束均满足（入口温度/变化率/N+1 冷量/IT≤冷却能力）。")
    if sc.dr_events: W.append("需求响应收益按基线差额结算；实际结算以电网公司基线算法（如前 N 日均值）为准。")
    W += ["DC-OPF 为线性化模型：忽略无功、电压与网损，支路潮流为近似值。", "日前确定性优化：风光/负荷/电价按给定曲线完全已知，未考虑预测误差。",
          "弃电惩罚、任务未完成惩罚是引导性虚拟成本，计入目标但不是真实现金支出。"]
    if sc.network_case == "case14": W.append("IEEE14 线路额定值为合成假设值。")
    if ac:
        W.append(f"交流校核仅针对 {ac.get('hour')}:00 单一时刻；" + ("已收敛" if ac.get("converged") else "未收敛！") +
                 ("" if ac.get("voltage_ok", True) else "，存在电压越限") + ("" if ac.get("loading_ok", True) else "，存在支路过载"))
    else: W.append("尚未进行交流潮流校核。")
    return W

# ---------------- 可复现运行包 ----------------
REPRO = '''"""可复现脚本：用 sim-agent 的调度引擎重算本次运行并核对目标函数。
用法：SIM_AGENT_ROOT=/path/to/sim-agent python reproduce.py   （需安装 pandapower / pyomo / highspy）"""
import json, os, sys
ROOT = os.environ.get("SIM_AGENT_ROOT", {root!r})
sys.path.insert(0, ROOT)
from app.scenario import Scenario
from app.tools import sdco_engine as eng
HERE = os.path.dirname(os.path.abspath(__file__))
sc = Scenario.model_validate_json(open(os.path.join(HERE, "scenario.json"), encoding="utf-8").read())
cfg = json.load(open(os.path.join(HERE, "solver_config.json"), encoding="utf-8"))
expected = json.load(open(os.path.join(HERE, "results.json"), encoding="utf-8"))
opts = dict(time_limit_s=cfg.get("time_limit_s"))
out = {{}}
for case in ["optimized", "baseline"]:
    if case not in expected["objective"]: continue
    r = eng.solve(sc, optimize=(case == "optimized"), solver_opts=opts)
    r["df"].to_csv(os.path.join(HERE, f"reproduced_dispatch_{{case}}.csv"), index=False)
    out[case] = r["objective"]
    exp = expected["objective"][case]; ok = abs(r["objective"] - exp) <= 1e-6*max(1, abs(exp))
    print(f"{{case}}: 目标函数 {{r['objective']:.4f}}（原运行 {{exp:.4f}}）{{'一致 ✓' if ok else '不一致 ✗'}}")
print(json.dumps({{"reproduced_objective": out}}, ensure_ascii=False))
'''

def export_package(s, root):
    import pandas as pd
    sc = s.state["scenario"]; res = s.state.get("results", {}); buf = io.BytesIO()
    cfg = {**DEFAULT_SOLVER, **(s.state.get("solver_cfg") or {})}
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("scenario.json", sc.model_dump_json(indent=2))
        z.writestr("params.json", json.dumps(param_sheet(s), ensure_ascii=False, indent=1, default=str))
        z.writestr("formulation.json", json.dumps(formulation(sc, res.get("optimized")), ensure_ascii=False, indent=1, default=str))
        z.writestr("solver_config.json", json.dumps(cfg, ensure_ascii=False, indent=1))
        if s.state.get("foundation_task_id"):
            from .foundation import store as fs
            task=fs.get("task",s.state["foundation_task_id"])
            z.writestr("input_snapshot.json",json.dumps(task["snapshot"],ensure_ascii=False,indent=2))
            z.writestr("frozen_task_metadata.json",json.dumps({key:task.get(key) for key in ("id","name","input_hash","status","execution_code_hash","execution_solver_identity","created","completed")},ensure_ascii=False,indent=2))
        z.writestr("runlog.json", json.dumps(s.state.get("runlog", []), ensure_ascii=False, indent=1, default=str))
        rj = dict(objective={k: v["objective"] for k, v in res.items()}, solver={k: v.get("solver") for k, v in res.items()},
                  cost_terms={k: v.get("cost_terms") for k, v in res.items()}, kpis=s.state.get("kpis", {}), compare=s.state.get("compare"),
                  ac=s.state.get("ac", {}), attribution=s.state.get("attribution"))
        if any(v.get("heat_boundary_audit") for v in res.values()): rj["heat_boundaries"]={k:v.get("heat_boundary_audit") for k,v in res.items() if v.get("heat_boundary_audit")}
        z.writestr("results.json", json.dumps(rj, ensure_ascii=False, indent=1, default=str))
        for k, v in res.items():
            z.writestr(f"dispatch_{k}.csv", v["df"].to_csv(index=False))
            for table in ("jobs", "links", "allocations", "job_admission", "migration_audit", "network_dispatch"):
                if table in v:
                    data=v[table] if isinstance(v[table],pd.DataFrame) else pd.DataFrame(v[table])
                    z.writestr(f"{table}_{k}.csv",data.to_csv(index=False))
            hb=v.get("heat_boundary_audit")
            if hb:
                import pandas as pd
                z.writestr(f"heat_nodes_{k}.csv",pd.DataFrame(hb["nodes"]).to_csv(index=False))
                z.writestr(f"heat_pipes_{k}.csv",pd.DataFrame(hb["pipes"]).to_csv(index=False))
            audit={key:v.get(key) for key in ("market_clearing","network_mapping","lifecycle_ledger","execution_context","time_axis","integer_tasks","migration_cleanup","heat_network_audit","heat_boundary_audit","execution_serialization")}
            if v.get("integer_tasks"):
                for sub in ["events","ledger"]: z.writestr(f"integer_{sub}_{k}.csv",pd.DataFrame(v["integer_tasks"][sub]).to_csv(index=False))
            z.writestr(f"audit_{k}.json",json.dumps(audit,ensure_ascii=False,indent=2,default=str))
        z.writestr("reproduce.py", REPRO.format(root=root))
        rp = os.path.join(s.artifact_dir, "report.md")
        if os.path.isfile(rp): z.write(rp, "report.md")
        z.writestr("README.md", f"# 运行包：{sc.name}\n\n导出时间 {time.strftime('%Y-%m-%d %H:%M:%S')}\n\n- scenario.json：完整场景\n- params.json：参数表（含来源标注）\n"
                   "- formulation.json：本次使用的数学模型（目标项/约束/变量/规模）\n- solver_config.json：求解配置\n- runlog.json：运行日志（每次工具调用）\n"
                   "- results.json / dispatch_*.csv：结果\n- reproduce.py：独立复现脚本（`python reproduce.py`）\n")
    return buf.getvalue()
