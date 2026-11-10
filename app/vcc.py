"""Google 风格 Virtual Capacity Curve（VCC）日前整形。

默认 vcc_mode='off'：不引入任何约束/目标项，与旧引擎一致。
模式：
  - carbon：按逐时碳强度压低高碳时段的灵活容量上限
  - price：按电价整形
  - weighted：α_c·碳 + α_p·电价

阶段：
  - day_ahead：先解小 LP 得 Cap_vcc(t)，再作为主问题硬上限
  - joint：与 DC-OPF 同层；Cap ≥ 灵活负荷，目标含整形项（最优时 Cap≈灵活负荷，
           等价于对灵活负荷施加额外碳/电价权重，并在结果中输出等效 VCC 曲线）

日能量：Σ_t Cap_vcc(d,t) ≥ 日灵活需求（batch_mwh 或 jobs 能量），且
        Cap_vcc(d,t) ≤ Cap_IT − interactive(t)（残差容量）。
"""
from __future__ import annotations
from .solver_execution import serialized_pyomo, checked_solve
from typing import Dict, List, Optional, Tuple
import numpy as np
import pyomo.environ as pyo
from .scenario import carbon_profile


def active(sc) -> bool:
    return (getattr(sc, "vcc_mode", "off") or "off") != "off"


def _ci_for_vcc(sc, dc) -> np.ndarray:
    """VCC 用碳强度：平坦区域因子时按核算口径选代理形状，避免 Cap 退化任意解。

    - location 核算：用 solar_dip（谷在正午）叠加，均值保持不变。
    - generation 核算：优先用场景 PV 可用率反比作代理（高可再生时段信号低）；
      无 PV 时不加假形状，仅靠 signal() 中电价微扰打破平手——避免与风电/夜间可再生打架
      而抬高 generation 排放（曾在 zhongwei_summer_highwind 复现 +7.7%）。
    """
    ci = np.asarray(carbon_profile(sc, dc.bus), float)
    if (ci.max() - ci.min()) > 1e-9 * max(abs(ci.mean()), 1e-9):
        return ci
    mean = float(ci.mean() if ci.mean() > 0 else getattr(sc, "carbon_factor", 0.5) or 0.5)
    accounting = (getattr(sc, "carbon_accounting", "location") or "location").lower()
    if accounting == "generation":
        def _default_pv_shape():
            # 与 sdco_engine.pv_shape 同构的正午峰，避免循环导入
            h = np.arange(24)
            s = np.clip(np.sin((h - 6) / 12.0 * np.pi), 0, None)
            return s / max(s.max(), 1e-9)
        pv = np.zeros(24)
        for plant in (getattr(sc, "pv", None) or []):
            if getattr(plant, "profile", None):
                prof = np.asarray(plant.profile, float)
            else:
                prof = _default_pv_shape()
            if prof.size != 24:
                prof = _default_pv_shape()
            pv = pv + float(plant.cap_mw) * prof
        if float(pv.max() - pv.min()) > 1e-9:
            inv = (pv.max() - pv) / (pv.max() - pv.min())
            return mean * (0.7 + 0.6 * inv)  # 约 [0.7μ, 1.3μ]
        return ci  # 保持平坦；signal 用电价微扰
    from .carbon import synthetic_profile
    shape = getattr(sc, "carbon_shape", None) or "solar_dip"
    if shape == "flat":
        shape = "solar_dip"
    return np.asarray(synthetic_profile(mean, shape), float)


def signal(sc, dc, mode: str) -> np.ndarray:
    """逐时整形信号（越大越不希望安排灵活负荷）。"""
    price = np.asarray(sc.price_cny_kwh, float) * 1000.0 + float(sc.grid_markup_cny_mwh)  # 元/MWh
    ci = _ci_for_vcc(sc, dc)  # tCO2/MWh（平坦曲线时用 synthetic 形状）
    wc = float(getattr(sc, "vcc_carbon_weight", 1.0) or 0.0)
    wp = float(getattr(sc, "vcc_price_weight", 1.0) or 0.0)
    if mode == "carbon":
        # 电价作极小扰动打破平手，避免求解器任意选时段
        return ci + 1e-6 * price / max(price.mean(), 1e-9)
    if mode == "price":
        return price / max(price.mean(), 1e-9)  # 无量纲化到 ~1
    # weighted：碳价×碳强度 + 电价，再按均值归一
    raw = wc * float(sc.carbon_price_cny_t) * ci + wp * price
    return raw / max(raw.mean(), 1e-9)


def residual_cap(dc) -> np.ndarray:
    return np.maximum(np.asarray([dc.cap_it_mw - x for x in dc.interactive_mw], float), 0.0)


def flexible_demand_mwh(sc, dc) -> float:
    if sc.jobs:
        return float(sum(j.energy_mwh for j in sc.jobs if j.dc == dc.name))
    return float(dc.batch_mwh)


@serialized_pyomo('vcc_day_ahead')
def day_ahead_curve(sc, dc) -> Dict:
    """单 DC 日前 VCC：min Σ s_t Cap_t  s.t. Σ Cap ≥ B, 0≤Cap≤residual。纯 LP。"""
    mode = sc.vcc_mode
    s = signal(sc, dc, mode)
    resid = residual_cap(dc)
    B = flexible_demand_mwh(sc, dc)
    if B <= 1e-9:
        cap = np.zeros(24)
        return dict(cap_mw=cap.tolist(), signal=s.tolist(), demand_mwh=0.0, mode=mode,
                    objective=0.0, feasible=True, stage="day_ahead")
    if resid.sum() + 1e-6 < B:
        # 不可行：放宽为按残差比例分配（仍给出曲线，主问题可能靠迁移/未完成）
        cap = resid * (B / max(resid.sum(), 1e-9))
        return dict(cap_mw=cap.tolist(), signal=s.tolist(), demand_mwh=B, mode=mode,
                    objective=float((s * cap).sum()), feasible=False, stage="day_ahead",
                    note="残差容量之和 < 日灵活需求，VCC 按残差比例放大（可能需迁移/弃负荷）")
    m = pyo.ConcreteModel()
    T = range(24)
    m.cap = pyo.Var(T, within=pyo.NonNegativeReals)
    m.c = pyo.ConstraintList()
    for t in T:
        m.c.add(m.cap[t] <= float(resid[t]))
    m.c.add(sum(m.cap[t] for t in T) >= B)
    m.obj = pyo.Objective(expr=sum(float(s[t]) * m.cap[t] for t in T))
    opt = pyo.SolverFactory("appsi_highs")
    res = checked_solve(opt,m,load_solutions=False)
    tc = str(res.solver.termination_condition)
    if tc != "optimal":
        # 退化：贪心填低信号时段
        order = np.argsort(s)
        cap = np.zeros(24); left = B
        for t in order:
            take = min(float(resid[t]), left)
            cap[t] = take; left -= take
            if left <= 1e-9:
                break
    else:
        m.solutions.load_from(res)
        cap = np.array([pyo.value(m.cap[t]) for t in T])
    # 稀疏 Cap 展开：与 DC-OPF 耦合时，硬清零大量小时会抬高网损/外购。
    # generation 核算默认更强展开；可用 vcc_cap_spread ∈ [0,1] 覆盖。
    acct = (getattr(sc, "carbon_accounting", "location") or "location").lower()
    # vcc_cap_spread=0 表示自动：generation 0.45 / location 0.05；>0 则按用户指定
    spread_user = float(getattr(sc, "vcc_cap_spread", 0.0) or 0.0)
    if spread_user > 0:
        spread = spread_user
    else:
        spread = 0.45 if acct == "generation" else 0.05
    spread = float(np.clip(spread, 0.0, 1.0))
    if spread > 0 and resid.sum() > 1e-9:
        uniform = resid * (B / resid.sum())
        cap = (1.0 - spread) * cap + spread * uniform
    return dict(cap_mw=cap.tolist(), signal=s.tolist(), demand_mwh=B, mode=mode,
                objective=float((s * cap).sum()), feasible=True, solver=tc, stage="day_ahead",
                cap_spread=spread)


def day_ahead_all(sc) -> Dict[str, dict]:
    return {d.name: day_ahead_curve(sc, d) for d in sc.data_centers}


def apply_day_ahead_bounds(m, sc, DC, D, T, flex_fn, c, curves: Dict[str, dict]):
    """主问题：灵活负荷 ≤ Cap_vcc(t)（日前曲线）。flex_fn(d,t)=batch/jobs 功率。"""
    for d in D:
        cap = curves[d]["cap_mw"]
        for t in T:
            c.add(flex_fn(d, t) <= float(cap[t]) + 1e-6)
    return curves


def add_joint(m, sc, DC, D, T, flex_fn, c, optimize: bool):
    """同层 VCC：Cap ≥ flex，Σ Cap ≥ B，Cap ≤ residual；返回整形目标项与曲线提取器。"""
    if not active(sc) or not optimize:
        return 0.0, None
    mode = sc.vcc_mode
    m.vcap = pyo.Var(D, T, within=pyo.NonNegativeReals)
    sig = {d: signal(sc, DC[d], mode) for d in D}
    for d in D:
        resid = residual_cap(DC[d]); B = flexible_demand_mwh(sc, DC[d])
        for t in T:
            c.add(m.vcap[d, t] >= flex_fn(d, t))
            c.add(m.vcap[d, t] <= float(resid[t]))
        if getattr(sc, "vcc_preserve_daily", True):
            c.add(sum(m.vcap[d, t] for t in T) >= B - 1e-6)
    # 整形项：信号 × Cap（元当量）。carbon 模式用碳价把 tCO2 转为元，与主目标量纲一致。
    scale = float(getattr(sc, "vcc_objective_scale", 1.0) or 1.0)
    term = 0.0
    for d in D:
        s = sig[d]
        if mode == "carbon":
            # 元：碳价 × CI(tCO2/MWh) × Cap(MWh)
            term = term + float(sc.carbon_price_cny_t) * sum(float(s[t]) * m.vcap[d, t] for t in T)
        else:
            # price / weighted：信号已归一，乘以参考电价水平保持量级
            ref = float(np.mean(sc.price_cny_kwh)) * 1000.0
            term = term + ref * sum(float(s[t]) * m.vcap[d, t] for t in T)
    term = scale * term

    def extract(v):
        out = {}
        for d in D:
            out[d] = dict(
                cap_mw=[float(v(m.vcap[d, t])) for t in T],
                signal=sig[d].tolist(),
                demand_mwh=flexible_demand_mwh(sc, DC[d]),
                mode=mode, stage="joint",
            )
        return out

    return term, extract


def summarize(curves: Dict[str, dict], df=None, D=None) -> dict:
    rows = []
    for name, cur in curves.items():
        cap = np.asarray(cur["cap_mw"], float)
        rows.append(dict(
            dc=name, mode=cur.get("mode"), demand_mwh=cur.get("demand_mwh"),
            cap_sum_mwh=round(float(cap.sum()), 3),
            cap_peak_mw=round(float(cap.max()), 3),
            cap_offpeak_share=round(float(cap[list(range(0, 7)) + list(range(22, 24))].sum() / max(cap.sum(), 1e-9)), 3),
            feasible=cur.get("feasible", True),
            stage=cur.get("stage", "day_ahead"),
        ))
    return dict(dcs=rows, mode=next(iter(curves.values())).get("mode") if curves else "off")
