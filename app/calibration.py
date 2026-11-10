"""站点功率标定：CSV(timestamp, util|IT_kW, PDU_kW) → idle+dynamic / PDU PWL 拟合。

不臆造参数；拟合指标（R²/MAPE/RMSE）一并返回。缺省场景仍为 identity。
"""
from __future__ import annotations
import csv, io, os
from typing import Any, Dict, List, Optional, Tuple
import numpy as np

from . import power_model as pm


REQUIRED_HINT = "CSV 需含 timestamp 与 PDU_kW（或 power_kw/pdu_kw），以及 util(0..1) 或 IT_kW/it_kw"


def _col(row: dict, *names) -> Optional[str]:
    lower = {k.lower().strip(): k for k in row}
    for n in names:
        if n.lower() in lower:
            return lower[n.lower()]
    return None


def load_csv(text_or_path: str) -> Dict[str, np.ndarray]:
    """读 CSV（路径或文本）→ util[0..1], pdu_kw, ts(可选)。"""
    if os.path.isfile(text_or_path):
        raw = open(text_or_path, encoding="utf-8").read()
    else:
        raw = text_or_path
    # strip BOM
    if raw.startswith("\ufeff"):
        raw = raw[1:]
    rdr = csv.DictReader(io.StringIO(raw))
    if not rdr.fieldnames:
        raise ValueError(REQUIRED_HINT)
    rows = list(rdr)
    if not rows:
        raise ValueError("CSV 无数据行")
    ku = _col(rows[0], "util", "utilization", "u", "cpu_util")
    ki = _col(rows[0], "IT_kW", "it_kw", "it_power_kw", "work_kw")
    kp = _col(rows[0], "PDU_kW", "pdu_kw", "power_kw", "p_kw", "pdu_power_kw")
    kt = _col(rows[0], "timestamp", "time", "ts", "datetime")
    if kp is None:
        raise ValueError(REQUIRED_HINT + f"；现有列={list(rows[0].keys())}")
    if ku is None and ki is None:
        raise ValueError(REQUIRED_HINT + "：缺 util 或 IT_kW")
    pdu, util, ts = [], [], []
    for r in rows:
        try:
            p = float(r[kp])
        except (TypeError, ValueError):
            continue
        if ku is not None:
            try:
                u = float(r[ku])
            except (TypeError, ValueError):
                continue
            if u > 1.0 + 1e-6:  # 百分比
                u = u / 100.0
        else:
            # IT_kW / peak 稍后归一；此处先存 IT_kW，用 pdu 最大值粗归一
            try:
                u = float(r[ki])  # temporary IT_kW
            except (TypeError, ValueError):
                continue
        pdu.append(p); util.append(u)
        ts.append(r.get(kt, "") if kt else "")
    if len(pdu) < 5:
        raise ValueError(f"有效样本过少（{len(pdu)}），至少需要 5 点")
    pdu_a = np.asarray(pdu, float)
    util_a = np.asarray(util, float)
    if ku is None:
        # util = IT_kW / max(IT_kW)；若全 0 则失败
        mx = float(np.max(util_a))
        if mx <= 1e-9:
            raise ValueError("IT_kW 全为 0，无法推算利用率")
        util_a = np.clip(util_a / mx, 0, 1)
    else:
        util_a = np.clip(util_a, 0, 1)
    return dict(util=util_a, pdu_kw=pdu_a, ts=ts, n=len(pdu_a))


def _metrics(y_true: np.ndarray, y_hat: np.ndarray) -> Dict[str, float]:
    y_true, y_hat = np.asarray(y_true, float), np.asarray(y_hat, float)
    resid = y_true - y_hat
    ss_res = float(np.sum(resid ** 2))
    ss_tot = float(np.sum((y_true - y_true.mean()) ** 2))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 1e-12 else float("nan")
    mape = float(np.mean(np.abs(resid) / np.maximum(np.abs(y_true), 1e-6))) * 100.0
    rmse = float(np.sqrt(np.mean(resid ** 2)))
    return dict(r2=round(r2, 4), mape_pct=round(mape, 3), rmse_kw=round(rmse, 3), n=int(y_true.size))


def fit_idle_dynamic(util: np.ndarray, pdu_kw: np.ndarray) -> Dict[str, Any]:
    """P ≈ a + b·u → P_idle=a, P_peak=a+b（kW）。强制 b≥0, a≥0。"""
    u, p = np.asarray(util, float), np.asarray(pdu_kw, float)
    # 最小二乘 [1, u] @ [a,b] = p
    A = np.column_stack([np.ones_like(u), u])
    coef, *_ = np.linalg.lstsq(A, p, rcond=None)
    a, b = float(coef[0]), float(coef[1])
    if b < 0:
        # 退化：常数功率
        a, b = float(np.mean(p)), 0.0
    a = max(a, 0.0)
    peak = a + b
    hat = a + b * u
    return dict(
        model="idle_dynamic",
        p_idle_kw=round(a, 4),
        p_peak_kw=round(peak, 4),
        metrics=_metrics(p, hat),
        note="最小二乘 P=P_idle+(P_peak-P_idle)·u；来源=标定",
    )


def fit_pdu_pwl(util: np.ndarray, pdu_kw: np.ndarray, n_seg: int = 3) -> Dict[str, Any]:
    """按 util 分位数取断点，段内线性插值；返回 [{util, power_mw}]（站点 MW 需外部乘 n 或已是站点 kW→MW）。

    此处断点功率单位与输入 pdu_kw 相同（kW）；调用方换算 MW。
    """
    u, p = np.asarray(util, float), np.asarray(pdu_kw, float)
    n_seg = max(2, int(n_seg))
    qs = np.linspace(0, 1, n_seg + 1)
    bps = []
    for q in qs:
        # 取 util 最接近分位的邻域均值
        target = float(np.quantile(u, q))
        mask = np.abs(u - target) <= max(0.05, 1.0 / n_seg)
        if not np.any(mask):
            mask = np.argsort(np.abs(u - target))[: max(3, len(u) // 10)]
            pu = float(np.mean(p[mask])); uu = float(np.mean(u[mask]))
        else:
            pu = float(np.mean(p[mask])); uu = float(target)
        bps.append((uu, pu))
    # 强制端点 0 / 1
    p0 = float(np.mean(p[u <= np.percentile(u, 10)])) if np.any(u <= np.percentile(u, 10)) else bps[0][1]
    p1 = float(np.mean(p[u >= np.percentile(u, 90)])) if np.any(u >= np.percentile(u, 90)) else bps[-1][1]
    bps[0] = (0.0, p0); bps[-1] = (1.0, p1)
    # 单调非降（功率随 util）
    mono = [bps[0]]
    for uu, pp in bps[1:]:
        mono.append((uu, max(pp, mono[-1][1])))
    bps = mono
    hat = np.array([pm.eval_pwl(float(ui), [{"util": a, "power_mw": b} for a, b in bps]) for ui in u])
    return dict(
        model="pdu_pwl",
        breakpoints_kw=[{"util": round(a, 4), "power_kw": round(b, 4)} for a, b in bps],
        metrics=_metrics(p, hat),
        note=f"分位断点 {n_seg} 段 PWL；来源=标定",
    )


def calibrate(text_or_path: str, mode: str = "idle_dynamic", n_seg: int = 3,
              n_servers: Optional[int] = None, scale_to_site_mw: bool = True) -> Dict[str, Any]:
    """主入口。返回 fit + 可写入 DataCenter 的字段（站点 MW）。

    - 若 CSV 为整站 PDU：n_servers=None，直接 kW→MW。
    - 若为单机：传 n_servers，站点 = 单机 × n。
    """
    data = load_csv(text_or_path)
    mode = (mode or "idle_dynamic").lower()
    if mode == "pdu_pwl":
        fit = fit_pdu_pwl(data["util"], data["pdu_kw"], n_seg=n_seg)
        scale = (float(n_servers) if n_servers else 1.0) / 1000.0
        bps = [{"util": b["util"], "power_mw": round(b["power_kw"] * scale, 6)} for b in fit["breakpoints_kw"]]
        apply = dict(power_model="pdu_pwl", pdu_breakpoints=bps, p_idle_mw=None, p_peak_mw=None)
        if n_servers:
            apply.update(n_servers=int(n_servers),
                         p_idle_kw=fit["breakpoints_kw"][0]["power_kw"],
                         p_peak_kw=fit["breakpoints_kw"][-1]["power_kw"])
    else:
        fit = fit_idle_dynamic(data["util"], data["pdu_kw"])
        if n_servers:
            apply = dict(power_model="idle_dynamic", n_servers=int(n_servers),
                         p_idle_kw=fit["p_idle_kw"], p_peak_kw=fit["p_peak_kw"],
                         p_idle_mw=round(fit["p_idle_kw"] * n_servers / 1000.0, 6),
                         p_peak_mw=round(fit["p_peak_kw"] * n_servers / 1000.0, 6))
        else:
            apply = dict(power_model="idle_dynamic",
                         p_idle_mw=round(fit["p_idle_kw"] / 1000.0, 6),
                         p_peak_mw=round(fit["p_peak_kw"] / 1000.0, 6))
    return dict(ok=True, fit=fit, apply=apply, n_samples=data["n"], source_tag="标定",
                util_mean=round(float(data["util"].mean()), 4),
                pdu_kw_mean=round(float(data["pdu_kw"].mean()), 3))


def apply_to_dc(dc, apply: dict, sources: Optional[dict] = None) -> dict:
    """写入 DataCenter；返回更新后的 sources 片段。"""
    for k, v in apply.items():
        if v is not None:
            setattr(dc, k, v)
    note = f"【标定】power_model={apply.get('power_model')}"
    if apply.get("power_model") == "idle_dynamic":
        note += f", P_idle={apply.get('p_idle_mw')} MW, P_peak={apply.get('p_peak_mw')} MW"
    else:
        note += f", 断点数={len(apply.get('pdu_breakpoints') or [])}"
    return {f"功率标定:{dc.name}": note}
