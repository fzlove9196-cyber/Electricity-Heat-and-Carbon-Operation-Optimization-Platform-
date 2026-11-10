"""任务 / 利用率 trace 加载：Alibaba / Azure / Borg CSV → Job 或小时利用率 → 功率。

真实 trace 多为 kW 级单作业，这里按 target_mwh 等比缩放到场景数据中心规模
（缩放后的数据需标注为“trace 派生/缩放”）。

功率映射（可选）：
  - identity：利用率×cap → IT 工作功率（旧）
  - idle_dynamic / pdu_pwl：经 app.power_model 转为电气 IT 功率曲线
"""
from __future__ import annotations
import math
import numpy as np, pandas as pd
from .scenario import Job
from . import power_model as pm

ALI_COLS = ["job_name", "task_name", "inst_num", "status", "start_time", "end_time", "plan_cpu", "plan_mem", "plan_gpu", "gpu_type"]
BORG_COLS = ["start_time", "end_time", "cpu_usage", "mem_usage", "job_id"]

def _read(path, cols):
    df = pd.read_csv(path)
    if not set(cols[:3]) & set(df.columns):   # 原始 trace 无表头
        df = pd.read_csv(path, header=None, names=cols[:pd.read_csv(path, header=None, nrows=1).shape[1]])
    return df

def load_alibaba_gpu(path, dc_names, target_mwh=300.0, max_jobs=40, gpu_kw=0.4, slack=2.0, seed=0) -> list[Job]:
    """pai_task_table 格式：start/end 为秒；plan_gpu 为百分比（100=1 卡）。功率 = inst_num×plan_gpu/100×gpu_kw。"""
    df = _read(path, ALI_COLS)
    df = df[(df.get("status", "Terminated") != "Failed")].dropna(subset=["start_time", "end_time"])
    df = df[df.end_time > df.start_time].copy()
    df["dur_h"] = (df.end_time - df.start_time)/3600
    df["kw"] = df.inst_num.fillna(1)*df.plan_gpu.fillna(100)/100*gpu_kw
    df["kwh"] = df.kw*df.dur_h
    df = df.sort_values("kwh", ascending=False).head(max_jobs)
    if df.empty: raise ValueError("trace 中没有可用任务")
    scale = target_mwh*1000/df.kwh.sum(); jobs = []
    for i, r in enumerate(df.itertuples()):
        rel = int(r.start_time//3600) % 24
        dur = min(24 - rel, max(1, math.ceil(r.dur_h)))
        dl = min(24, rel + max(dur, math.ceil(dur*slack)))
        e = r.kwh*scale/1000
        jobs.append(Job(id=f"ALI{i:03d}", dc=dc_names[i % len(dc_names)], release=rel, deadline=dl, energy_mwh=round(e, 4),
                        max_mw=round(max(r.kw*scale/1000, e/(dl-rel)*1.05), 4), source="alibaba-gpu-v2020(scaled)"))
    return jobs

def load_azure_llm(path, dc_names, target_mwh=60.0, latency_ms=15.0) -> list[Job]:
    """AzureLLMInferenceTrace 格式：TIMESTAMP, ContextTokens, GeneratedTokens。按小时聚合 token→能量，作为时延敏感的 1 小时窗口任务。"""
    df = pd.read_csv(path)
    ts = pd.to_datetime(df["TIMESTAMP"]); tok = df["ContextTokens"].fillna(0) + df["GeneratedTokens"].fillna(0)*4
    hourly = tok.groupby(ts.dt.hour).sum().reindex(range(24), fill_value=0)
    if hourly.sum() <= 0: raise ValueError("trace token 数为 0")
    e = hourly/hourly.sum()*target_mwh; jobs = []
    for h, v in e.items():
        if v <= 0: continue
        jobs.append(Job(id=f"AZ{h:02d}", dc=dc_names[h % len(dc_names)], release=int(h), deadline=int(h)+1, energy_mwh=round(float(v), 4),
                        max_mw=round(float(v)*1.05, 4), max_latency_ms=latency_ms, source="azure-llm-inference(scaled)"))
    return jobs

def load_borg_util(path, hour_col=None, util_col=None) -> np.ndarray:
    """Google Borg 风格：CSV 含小时利用率（0-1 或 0-100）。返回长度 24 的利用率数组。"""
    df = pd.read_csv(path)
    cols = {c.lower(): c for c in df.columns}
    uc = util_col or next((cols[k] for k in ("util", "cpu_usage", "cpu", "utilization", "usage") if k in cols), None)
    if uc is None:
        # 无表头两列：hour, util
        df = pd.read_csv(path, header=None)
        if df.shape[1] < 2: raise ValueError("Borg util CSV 需要 hour, util 两列")
        h, u = df.iloc[:, 0].astype(int) % 24, df.iloc[:, 1].astype(float)
    else:
        hc = hour_col or next((cols[k] for k in ("hour", "hr", "t", "time") if k in cols), None)
        u = df[uc].astype(float)
        if u.max() > 1.5: u = u / 100.0
        if hc: h = df[hc].astype(int) % 24
        else: h = np.arange(len(u)) % 24
    out = np.zeros(24)
    cnt = np.zeros(24)
    for hh, uu in zip(np.asarray(h), np.asarray(u)):
        out[int(hh)] += float(uu); cnt[int(hh)] += 1
    cnt = np.maximum(cnt, 1)
    return np.clip(out / cnt, 0, 1)

def hourly_util_from_alibaba(path, max_rows=50000) -> np.ndarray:
    """从 Alibaba pai_task_table 粗估 24h 集群 GPU 利用率（按 plan_gpu·inst 加权占用，再归一到峰值）。"""
    df = _read(path, ALI_COLS).head(max_rows)
    df = df.dropna(subset=["start_time", "end_time"])
    df = df[df.end_time > df.start_time]
    load = np.zeros(24)
    for r in df.itertuples():
        kw = float((r.inst_num if not pd.isna(r.inst_num) else 1) * (r.plan_gpu if not pd.isna(r.plan_gpu) else 100) / 100.0)
        t0 = int(r.start_time // 3600); t1 = int(math.ceil(r.end_time / 3600))
        for t in range(t0, max(t0 + 1, t1)):
            load[t % 24] += kw
    peak = load.max()
    return load / peak if peak > 0 else load

def util_to_power_mw(util_24, dc) -> list:
    """小时利用率 → 站点电气 IT 功率 MW（经 DC 功率模型；identity 时 = util×cap）。"""
    util = np.clip(np.asarray(util_24, float), 0, 1)
    if len(util) != 24: raise ValueError("util 必须 24 点")
    work = util * float(dc.cap_it_mw)
    return [round(pm.power_mw(dc, w), 6) for w in work]

def util_to_interactive_batch(util_24, dc, flex_share=0.3):
    """利用率曲线 → (interactive_mw[24], batch_mwh)：刚性= (1-flex)×util×cap，灵活能量= flex×Σ util×cap。"""
    util = np.clip(np.asarray(util_24, float), 0, 1)
    work = util * float(dc.cap_it_mw)
    inter = [round(float(w * (1 - flex_share)), 4) for w in work]
    batch = round(float(work.sum() * flex_share), 4)
    return inter, batch

def apply_util_curve_to_dc(dc, util_24, flex_share=0.3, as_power=False):
    """把利用率写入 DC：默认写工作功率曲线；as_power=True 时把电气功率写回 interactive（仅演示，会打乱 flex）。"""
    inter, batch = util_to_interactive_batch(util_24, dc, flex_share)
    if as_power and pm.is_hardware(dc):
        # 将电气功率曲线按同一 flex 拆分（近似）
        pwr = np.asarray(util_to_power_mw(util_24, dc), float)
        inter = [round(float(p * (1 - flex_share)), 4) for p in pwr]
        batch = round(float(pwr.sum() * flex_share), 4)
    dc.interactive_mw = inter
    dc.batch_mwh = batch
    return dc
