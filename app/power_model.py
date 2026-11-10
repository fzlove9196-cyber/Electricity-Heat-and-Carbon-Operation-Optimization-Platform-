"""IT 硬件功率模型（Fan idle+动态 / PDU 分段线性）。

默认 power_model='identity'：P_IT = IT 工作功率（与历史引擎完全一致）。
可选：
  - idle_dynamic: P_IT = P_idle + (P_peak − P_idle)·u，u = IT_work / Cap_IT
  - pdu_pwl: 利用率→功率分段线性（凸组合 + SOS2，启用时可能变为 MILP）

站点级参数优先；若仅给 per-server + n_servers 则换算为站点 MW。
所有缺省/unset 路径保持 identity，不改变既有算例数值。
"""
from __future__ import annotations
from typing import List, Optional, Tuple
import numpy as np


def resolve_idle_peak(dc) -> Tuple[Optional[float], Optional[float]]:
    """返回 (p_idle_mw, p_peak_mw)；两者都有效才启用硬件层，否则 identity。"""
    idle = getattr(dc, "p_idle_mw", None)
    peak = getattr(dc, "p_peak_mw", None)
    if idle is not None and peak is not None:
        return float(idle), float(peak)
    n = getattr(dc, "n_servers", None)
    ik = getattr(dc, "p_idle_kw", None)
    pk = getattr(dc, "p_peak_kw", None)
    if n and ik is not None and pk is not None and n > 0:
        return float(n) * float(ik) / 1000.0, float(n) * float(pk) / 1000.0
    return None, None


def is_hardware(dc) -> bool:
    """是否启用硬件功率层（非 identity）。"""
    mode = getattr(dc, "power_model", "identity") or "identity"
    if mode == "identity":
        return False
    if mode == "pdu_pwl":
        bps = getattr(dc, "pdu_breakpoints", None) or []
        return len(bps) >= 2
    idle, peak = resolve_idle_peak(dc)
    return idle is not None and peak is not None and peak >= idle >= 0


def util_of(work_mw, cap_it_mw: float) -> float:
    return float(work_mw) / max(float(cap_it_mw), 1e-9)


def idle_dynamic_power(work_mw, cap_it_mw: float, p_idle_mw: float, p_peak_mw: float):
    """仿射：P = P_idle + (P_peak−P_idle)·(work/Cap)。work 可为数值或 Pyomo 表达式。"""
    u_scale = (p_peak_mw - p_idle_mw) / max(cap_it_mw, 1e-9)
    return p_idle_mw + u_scale * work_mw


def eval_idle_dynamic(work_mw, cap_it_mw: float, p_idle_mw: float, p_peak_mw: float) -> float:
    return float(idle_dynamic_power(work_mw, cap_it_mw, p_idle_mw, p_peak_mw))


def normalize_breakpoints(bps) -> List[Tuple[float, float]]:
    """[{util, power_mw} | (util, power_mw)] → 按 util 排序的 (u, P) 列表，强制含 0 与 1 端点外推。"""
    pts = []
    for b in bps:
        if isinstance(b, dict):
            pts.append((float(b["util"]), float(b["power_mw"])))
        else:
            pts.append((float(b[0]), float(b[1])))
    pts = sorted(pts, key=lambda x: x[0])
    if not pts:
        return [(0.0, 0.0), (1.0, 1.0)]
    if pts[0][0] > 1e-9:
        pts = [(0.0, pts[0][1])] + pts  # 左端用首点功率外推（常见：u=0 已给 idle）
    if pts[-1][0] < 1.0 - 1e-9:
        pts = pts + [(1.0, pts[-1][1])]
    # 去重 util
    out = [pts[0]]
    for u, p in pts[1:]:
        if abs(u - out[-1][0]) < 1e-12:
            out[-1] = (u, p)
        else:
            out.append((u, p))
    return out


def eval_pwl(util: float, bps) -> float:
    pts = normalize_breakpoints(bps)
    u = float(np.clip(util, 0.0, 1.0))
    for i in range(len(pts) - 1):
        u0, p0 = pts[i]; u1, p1 = pts[i + 1]
        if u0 - 1e-12 <= u <= u1 + 1e-12:
            if abs(u1 - u0) < 1e-12:
                return p1
            w = (u - u0) / (u1 - u0)
            return p0 + w * (p1 - p0)
    return pts[-1][1]


def power_mw(dc, work_mw) -> float:
    """数值：由 IT 工作功率得到电气 IT 功率。identity → 原样返回。"""
    mode = getattr(dc, "power_model", "identity") or "identity"
    if mode == "identity" or not is_hardware(dc):
        return float(work_mw)
    if mode == "pdu_pwl":
        return eval_pwl(util_of(work_mw, dc.cap_it_mw), dc.pdu_breakpoints)
    idle, peak = resolve_idle_peak(dc)
    return eval_idle_dynamic(work_mw, dc.cap_it_mw, idle, peak)


def describe(dc) -> dict:
    mode = getattr(dc, "power_model", "identity") or "identity"
    idle, peak = resolve_idle_peak(dc)
    return dict(
        name=dc.name, power_model=mode, hardware=is_hardware(dc),
        p_idle_mw=idle, p_peak_mw=peak, cap_it_mw=dc.cap_it_mw,
        pdu_n=len(getattr(dc, "pdu_breakpoints", None) or []),
        note=("identity：P_IT=IT 工作功率（旧行为）" if not is_hardware(dc)
              else (f"idle_dynamic：P={idle:.3g}+({peak:.3g}-{idle:.3g})·u"
                    if mode != "pdu_pwl" else f"pdu_pwl：{len(dc.pdu_breakpoints)} 个断点")),
    )


def add_pyomo_power(m, sc, DC, D, T, work_fn, c, optimize: bool = True):
    """在模型上添加 P_IT 变量/约束。返回 pit(d,t) 可调用对象。

    work_fn(d,t) = interactive + batch（IT 工作功率表达式）。
    identity DC：pit ≡ work（无额外变量）。
    idle_dynamic：线性等式。
    pdu_pwl：SOS2 分段（引入二进制，问题变为 MILP）。
    """
    import pyomo.environ as pyo
    hard = [d for d in D if is_hardware(DC[d])]
    if not hard:
        return work_fn, dict(hardware=[], milp=False)

    m.pit = pyo.Var(hard, T, within=pyo.NonNegativeReals)
    milp = False
    info = {}
    pdu_dcs = [d for d in hard if (DC[d].power_model or "") == "pdu_pwl" and (DC[d].pdu_breakpoints or [])]
    if pdu_dcs:
        m.pdu_lam = pyo.Var([(dd, t, k) for dd in pdu_dcs for t in T for k in range(20)],
                            within=pyo.NonNegativeReals)
        m.pdu_y = pyo.Var([(dd, t, s) for dd in pdu_dcs for t in T for s in range(19)],
                          within=pyo.Binary)
    for d in hard:
        dc = DC[d]
        mode = dc.power_model or "identity"
        if mode == "pdu_pwl" and (dc.pdu_breakpoints or []):
            pts = normalize_breakpoints(dc.pdu_breakpoints)
            K = range(len(pts))
            for t in T:
                # 仅对本 DC 的断点建约束
                ks = list(range(len(pts)))
                c.add(sum(m.pdu_lam[d, t, k] for k in ks) == 1)
                c.add(work_fn(d, t) == dc.cap_it_mw * sum(pts[k][0] * m.pdu_lam[d, t, k] for k in ks))
                c.add(m.pit[d, t] == sum(pts[k][1] * m.pdu_lam[d, t, k] for k in ks))
                segs = list(range(len(pts) - 1))
                c.add(sum(m.pdu_y[d, t, s] for s in segs) == 1)
                for k in ks:
                    # λ_k ≤ y_{k-1} + y_k（端点只邻一段）
                    if k == 0:
                        c.add(m.pdu_lam[d, t, k] <= m.pdu_y[d, t, 0])
                    elif k == len(pts) - 1:
                        c.add(m.pdu_lam[d, t, k] <= m.pdu_y[d, t, k - 1])
                    else:
                        c.add(m.pdu_lam[d, t, k] <= m.pdu_y[d, t, k - 1] + m.pdu_y[d, t, k])
                # 未用 λ 固定 0
                for k in range(len(pts), 20):
                    m.pdu_lam[d, t, k].fix(0)
                for s in range(len(pts) - 1, 19):
                    m.pdu_y[d, t, s].fix(0)
            milp = True
            info[d] = dict(mode="pdu_pwl", n_bp=len(pts), pts=pts)
        else:
            idle, peak = resolve_idle_peak(dc)
            for t in T:
                c.add(m.pit[d, t] == idle_dynamic_power(work_fn(d, t), dc.cap_it_mw, idle, peak))
            info[d] = dict(mode="idle_dynamic", p_idle_mw=idle, p_peak_mw=peak)

    def pit(d, t):
        if d in hard:
            return m.pit[d, t]
        return work_fn(d, t)

    return pit, dict(hardware=hard, milp=milp, info=info)


def breakpoints_from_curve(util, power_mw, idle_mw=None, knots=(0.0, 0.2, 0.5, 0.8, 1.0)):
    """由实测/公开利用率-功率曲线（如 SPECpower_ssj2008 11 级负载）生成 pdu_pwl 断点。
    公开基准 B2 (cases/public_bench) 表明：仅用 idle+peak 两点的线性 idle_dynamic 对近年服务器
    中位 MAPE≈10%（曲线下凹），5 断点 PWL 可显著降低。不改变任何默认行为，仅供标定使用。"""
    u = np.asarray(util, float); p = np.asarray(power_mw, float); o = np.argsort(u); u, p = u[o], p[o]
    if idle_mw is not None:
        u = np.r_[0.0, u]; p = np.r_[float(idle_mw), p]
    out = []
    for k in knots:
        k = float(np.clip(k, u.min(), u.max())) if k not in (0.0, 1.0) else k
        if k <= u.min(): pk = p[0] if u.min() <= 1e-9 else p[0] + (p[1]-p[0])/(u[1]-u[0])*(k-u[0])
        elif k >= u.max(): pk = p[-1] + (p[-1]-p[-2])/(u[-1]-u[-2])*(k-u[-1])
        else: pk = float(np.interp(k, u, p))
        out.append({"util": float(k), "power_mw": float(pk)})
    return out
