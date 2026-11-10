"""三级优化（日前定基线 / 日内滚动校准 / 实时快速跟踪）与可行响应域。

向后兼容：默认不启用；仅当工具/API 显式调用时写入 session.state['tier']。
不替换主 LP；实时层为规则 / MPC-lite，不引入 RL。
"""
from __future__ import annotations
from ..solver_execution import serialized_pyomo, checked_solve
import copy, json, os, re, time
from typing import Any, Optional
import numpy as np
import pandas as pd

STAGE_DA, STAGE_ID, STAGE_RT = "day_ahead", "intra_day", "real_time"


# ─── forecast patch ───────────────────────────────────────────────────────────

def parse_forecast_nl(text: str) -> dict:
    """中文 → patch。例：「下午3点风电少10%」「光伏整体降15%」「电价涨0.1」「碳强度+0.05」。"""
    p: dict[str, Any] = {}
    if not text:
        return p
    # hour-specific renewable scale
    for m in re.finditer(
        r"(?:上午|下午|晚上)?(\d{1,2})\s*点.*?(风电|风机|风|光伏|光电|pv|风光).*?(少|降|减|低|cut|down)\s*(\d+(?:\.\d+)?)\s*%",
        text, re.I):
        h = int(m.group(1))
        ctx = text[max(0, m.start()-2): m.end()]
        if ("下午" in ctx or "午后" in ctx) and h < 12:
            h += 12
        if ("晚上" in ctx or "傍晚" in ctx) and h < 12 and h != 0:
            h += 12
        h = max(0, min(23, h))
        fac = 1.0 - float(m.group(4)) / 100.0
        kind = m.group(2)
        key = "wind_scale" if any(k in kind for k in ("风", "wind")) and "光" not in kind else (
            "pv_scale" if any(k in kind.lower() for k in ("光", "pv")) else "renew_scale")
        p.setdefault(key, {})[h] = fac
    # global scale
    m = re.search(r"(风电|风机|风|光伏|光电|pv|风光).*?(少|降|减|低)\s*(\d+(?:\.\d+)?)\s*%", text, re.I)
    if m and "点" not in text[max(0, m.start()-8):m.start()]:
        fac = 1.0 - float(m.group(3)) / 100.0
        kind = m.group(1)
        if any(k in kind for k in ("风",)) and "光" not in kind:
            p["wind_scale_global"] = fac
        elif any(k in kind.lower() for k in ("光", "pv")):
            p["pv_scale_global"] = fac
        else:
            p["renew_scale_global"] = fac
    m = re.search(r"(风电|光伏|风光).*?(多|增|升|高)\s*(\d+(?:\.\d+)?)\s*%", text, re.I)
    if m:
        fac = 1.0 + float(m.group(3)) / 100.0
        kind = m.group(1)
        if "风" in kind and "光" not in kind: p["wind_scale_global"] = fac
        elif "光" in kind or "pv" in kind.lower(): p["pv_scale_global"] = fac
        else: p["renew_scale_global"] = fac
    m = re.search(r"电价.*?(涨|升|加|提高)\s*(\d+(?:\.\d+)?)", text)
    if m: p["price_delta"] = float(m.group(2))
    m = re.search(r"电价.*?(降|跌|减)\s*(\d+(?:\.\d+)?)", text)
    if m: p["price_delta"] = -float(m.group(2))
    m = re.search(r"碳(?:强度|因子)?.*?(?:\+|升|涨|加|提高)\s*(\d+(?:\.\d+)?)", text)
    if m: p["carbon_delta"] = float(m.group(1))
    m = re.search(r"负荷.*?(增|升|高)\s*(\d+(?:\.\d+)?)\s*%", text)
    if m: p["load_scale_global"] = 1.0 + float(m.group(2)) / 100.0
    m = re.search(r"负荷.*?(少|降|减)\s*(\d+(?:\.\d+)?)\s*%", text)
    if m: p["load_scale_global"] = 1.0 - float(m.group(2)) / 100.0
    return p


def load_patch_file(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    if isinstance(raw, dict) and "patch" in raw:
        return raw["patch"]
    return raw if isinstance(raw, dict) else {}


def apply_forecast_patch(sc, patch: dict):
    """就地修改 Scenario 的风光/电价/碳/负荷曲线。返回变更摘要。"""
    from ..time_axis import require_hourly
    require_hourly(sc,"三级运行")
    if not patch:
        return {"ok": True, "changes": []}
    sc = copy.deepcopy(sc) if False else sc  # caller owns clone
    changes = []
    def _scale_list(arr, global_s=None, per_h=None):
        a = list(arr)
        if global_s is not None:
            a = [x * float(global_s) for x in a]
        if per_h:
            for h, f in per_h.items():
                h = int(h)
                if 0 <= h < len(a):
                    a[h] = a[h] * float(f)
        return a

    pv_g = patch.get("pv_scale_global", patch.get("renew_scale_global"))
    pv_h = patch.get("pv_scale", patch.get("renew_scale"))
    wind_g = patch.get("wind_scale_global", patch.get("renew_scale_global"))
    wind_h = patch.get("wind_scale", patch.get("renew_scale"))

    for p in sc.pv:
        old = list(p.profile) if p.profile else None
        if old is None:
            from ..scenario import pv_shape
            old = list(pv_shape())
        # PV plants: apply pv scales; name hint for wind-as-pv
        is_wind = any(k in (p.name or "").lower() for k in ("wind", "风"))
        g = wind_g if is_wind else pv_g
        h = wind_h if is_wind else pv_h
        # also apply renew global
        if patch.get("renew_scale_global") and g is None:
            g = patch["renew_scale_global"]
        new = _scale_list(old, g, h)
        p.profile = [round(float(x), 6) for x in new]
        changes.append(f"pv:{p.name} scaled")

    if sc.network and sc.network.gens:
        for g in sc.network.gens:
            if (g.kind or "").lower() in ("wind", "风电", "风机"):
                # energy_mwh_day or pmax derate via pmax_mw scale
                if wind_g is not None:
                    g.pmax_mw = float(g.pmax_mw) * float(wind_g)
                    changes.append(f"gen:{g.name} pmax*{wind_g}")
                if wind_h and g.energy_mwh_day is not None:
                    # approximate: scale daily energy by mean of hour factors if provided
                    mean_f = float(np.mean(list(wind_h.values())))
                    g.energy_mwh_day = float(g.energy_mwh_day) * mean_f
                    changes.append(f"gen:{g.name} eday*{mean_f:.3f}")

    if "price_delta" in patch:
        dlt = float(patch["price_delta"])
        sc.price_cny_kwh = [round(float(x) + dlt, 6) for x in sc.price_cny_kwh]
        changes.append(f"price+={dlt}")
    if "price_scale" in patch:
        s = float(patch["price_scale"])
        sc.price_cny_kwh = [round(float(x) * s, 6) for x in sc.price_cny_kwh]
        changes.append(f"price*={s}")
    if "carbon_delta" in patch:
        dlt = float(patch["carbon_delta"])
        for r, prof in list(sc.carbon_profiles.items()):
            sc.carbon_profiles[r] = [max(0.0, float(x) + dlt) for x in prof]
        changes.append(f"carbon+={dlt}")
    if "load_scale_global" in patch:
        s = float(patch["load_scale_global"])
        sc.load_scale = float(sc.load_scale) * s
        for d in sc.data_centers:
            d.interactive_mw = [round(float(x) * s, 6) for x in d.interactive_mw]
        changes.append(f"load*={s}")
    if "interactive_scale" in patch:
        per = patch["interactive_scale"]
        for d in sc.data_centers:
            d.interactive_mw = _scale_list(d.interactive_mw, None, per)
        changes.append("interactive per-hour scale")
    return {"ok": True, "changes": changes, "patch": patch}


# ─── baseline artifact ────────────────────────────────────────────────────────

def _site_mw(df: pd.DataFrame, sc) -> list:
    cols = [f"{d.name}_grid_MW" for d in sc.data_centers if f"{d.name}_grid_MW" in df.columns]
    if not cols:
        return [0.0] * 24
    return [float(x) for x in df[cols].sum(axis=1).values]


def _series_map(df: pd.DataFrame, sc) -> dict:
    out = {"site_grid_mw": _site_mw(df, sc), "price": [float(x) for x in df["price"].values] if "price" in df else []}
    for d in sc.data_centers:
        n = d.name
        for k, col in [("grid_mw", f"{n}_grid_MW"), ("it_mw", f"{n}_IT_MW"), ("it_work_mw", f"{n}_IT_work_MW"),
                       ("batch_mw", f"{n}_batch_IT"), ("tin_c", f"{n}_Tin_C"), ("cool_mw", f"{n}_cool_MW"),
                       ("chiller_mwth", f"{n}_chiller_MWth"), ("tes_soc", f"{n}_tes_soc_MWh"), ("pue", f"{n}_PUE")]:
            if col in df.columns:
                out.setdefault(n, {})[k] = [float(x) for x in df[col].values]
    for s in getattr(sc, "storage", []) or []:
        for k, col in [("ch", f"{s.name}_ch"), ("dis", f"{s.name}_dis"), ("soc", f"{s.name}_soc")]:
            if col in df.columns:
                out.setdefault("storage", {}).setdefault(s.name, {})[k] = [float(x) for x in df[col].values]
        if (getattr(s, "kind", "ess") or "ess") == "ups":
            out.setdefault("ups", {}).setdefault(s.name, out.get("storage", {}).get(s.name, {}))
            out["ups"][s.name]["meta"] = {
                "energy_mwh": s.energy_mwh, "power_mw": s.power_mw, "eta_ch": s.eta_ch, "eta_dis": s.eta_dis,
                "soc0": s.soc0, "soc_min": s.soc_min, "soc_max": s.soc_max,
                "reserve_frac": getattr(s, "reserve_frac", 0.0), "source_note": getattr(s, "source_note", "") or "",
            }
    return out


def make_baseline(sc, result: dict, label: str = "day_ahead", note: str = "") -> dict:
    df = result["df"]
    art = {
        "version": 1,
        "label": label,
        "stage": STAGE_DA,
        "created_ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "note": note,
        "objective_cny": float(result.get("objective", 0)),
        "cost_cny": float(result.get("cost_cny", result.get("objective", 0))),
        "emissions_tco2": float(result.get("emissions_t", 0)),
        "thermal_safe": (result.get("thermal") or {}).get("safe"),
        "thermal_violations": (result.get("thermal") or {}).get("violations"),
        "solver": result.get("solver"),
        "series": _series_map(df, sc),
        "dr": result.get("dr"),
    }
    return art


def save_baseline(art_dir: str, art: dict, name: str = "baseline") -> str:
    os.makedirs(art_dir, exist_ok=True)
    # versioning: baseline.json + baseline_v{n}.json
    path = os.path.join(art_dir, f"{name}.json")
    n = 1
    while os.path.exists(os.path.join(art_dir, f"{name}_v{n}.json")):
        n += 1
    ver_path = os.path.join(art_dir, f"{name}_v{n}.json")
    art = dict(art); art["artifact_version"] = n
    with open(ver_path, "w", encoding="utf-8") as f:
        json.dump(art, f, ensure_ascii=False, indent=2)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(art, f, ensure_ascii=False, indent=2)
    return ver_path


def load_baseline(art_dir: str, name: str = "baseline", version: int | None = None) -> dict:
    if version is not None:
        path = os.path.join(art_dir, f"{name}_v{version}.json")
    else:
        path = os.path.join(art_dir, f"{name}.json")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


# ─── rolling reoptimize ───────────────────────────────────────────────────────

def prepare_roll_scenario(sc, prior_result: dict, from_t: int):
    """把 from_t 时刻状态写入场景初值（SOC / 入口温度），供滚动重解。返回新 Scenario。"""
    from ..time_axis import require_hourly
    require_hourly(sc,"三级运行")
    sc2 = copy.deepcopy(sc)
    from_t = int(max(0, min(23, from_t)))
    if from_t <= 0 or prior_result is None:
        return sc2, from_t
    df = prior_result["df"]
    t_prev = from_t - 1
    for s in sc2.storage:
        col = f"{s.name}_soc"
        if col in df.columns:
            e = max(s.energy_mwh, 1e-9)
            s.soc0 = float(np.clip(df.loc[t_prev, col] / e, s.soc_min, s.soc_max))
    for d in sc2.data_centers:
        th = d.thermal
        if th is None:
            continue
        tin = f"{d.name}_Tin_C"
        if tin in df.columns:
            th.t0_c = float(df.loc[t_prev, tin])
        tes = f"{d.name}_tes_soc_MWh"
        if th.tes_mwh_th > 0 and tes in df.columns:
            th.tes_soc0 = float(np.clip(df.loc[t_prev, tes] / max(th.tes_mwh_th, 1e-9), 0, 1))
    return sc2, from_t


def run_day_ahead(sc, optimize=True, solver_opts=None, levers=None):
    from ..time_axis import require_hourly
    require_hourly(sc,"三级运行")
    from ..tools import sdco_engine as eng
    return eng.solve(sc, optimize=optimize, solver_opts=solver_opts, levers=levers)


def run_rolling(sc, prior_result: dict, from_t: int, baseline_art: dict | None = None,
                patch: dict | None = None, dev_penalty_cny_mwh: float = 80.0,
                solver_opts=None, levers=None, soc_measured=None, soc_end_use_measured: bool = False,
                emergency: bool | None = None):
    """日内滚动：应用预测补丁 → 锁定过去小时 → 相对基线偏离罚。

    注意：硬锁定过去小时时默认不改写 soc0/t0（否则与 prior 轨迹冲突导致不可行）。
    可选 soc_measured：在 from_t 处以实测 SOC 断开日前轨迹硬链接（过去小时仍锁定 prior）。
    发电机/外网保持自由，由功率平衡在锁定负荷/储能后重配。
    """
    from ..time_axis import require_hourly
    require_hourly(sc,"三级运行")
    from ..tools import sdco_engine as eng
    sc2 = copy.deepcopy(sc)
    patch_info = apply_forecast_patch(sc2, patch or {})
    from_t = int(max(0, min(23, from_t)))
    base_mw = None
    if baseline_art and baseline_art.get("series", {}).get("site_grid_mw"):
        base_mw = list(baseline_art["series"]["site_grid_mw"])
    elif prior_result is not None:
        base_mw = _site_mw(prior_result["df"], sc)
    soc_info = normalize_soc_measured(soc_measured, sc2, prior_result=prior_result, from_t=from_t)
    # from_t==0：直接改场景 soc0（无过去锁定）
    if from_t <= 0 and soc_info.get("mwh"):
        for s in sc2.storage:
            if s.name in soc_info["mwh"]:
                s.soc0 = float(np.clip(soc_info["mwh"][s.name] / max(s.energy_mwh, 1e-9), s.soc_min, s.soc_max))
    emerg = bool(sc2.emergency_mode if emergency is None else emergency)
    roll = {
        "from_t": from_t,
        "prior": prior_result,
        "baseline_site_mw": base_mw,
        "dev_penalty_cny_mwh": float(dev_penalty_cny_mwh or 0.0),
        "fix_gens": False,  # 保持可行：负荷/储能锁定后电源重配
        "fix_thermal": True,
        "fix_storage": True,
        "fix_batch": True,
        "soc_measured": soc_info.get("mwh") or None,
        "soc_end_use_measured": bool(soc_end_use_measured),
        "emergency": emerg,
    }
    r = eng.solve(sc2, optimize=True, solver_opts=solver_opts, levers=levers, roll=roll)
    r["tier"] = {
        "stage": STAGE_ID, "from_t": from_t, "patch": patch_info,
        "dev_penalty_cny_mwh": dev_penalty_cny_mwh,
        "soc_source": soc_info.get("source"),
        "soc_measured": soc_info,
        "emergency": emerg,
    }
    r["soc_source"] = soc_info.get("source")
    r["soc_deviation"] = soc_info.get("deviation")
    return r, sc2


# ─── feasible response envelope ───────────────────────────────────────────────

def _flex_expr_builder(m, sc, DC, D, STO, T, elec):
    """站点净关口功率代理：Σ DC 电网功率（含冷却）。"""
    def site(t):
        return sum(elec(d, t) for d in D)
    return site


def compute_envelope(sc, stage: str = STAGE_DA, from_t: int = 0, prior_result: dict | None = None,
                     baseline_art: dict | None = None, hours: list | None = None,
                     stride: int = 1, solver_opts=None, levers=None) -> dict:
    """逐时上/下调可行域（对站点关口功率做 max/min LP）。

    stage:
      day_ahead — 全日自由
      intra_day — 锁定 t < from_t
      real_time — 锁定全部小时后仅放开单小时的储能充放（冷却/批处理尽量贴基线）
    """
    from ..time_axis import require_hourly
    require_hourly(sc,"三级运行")
    from ..tools import sdco_engine as eng
    import pyomo.environ as pyo

    sc2 = copy.deepcopy(sc)
    # 包络探测：放开绿电硬占比（规划约束），聚焦运行灵活域；保留热/SOC/作业窗
    sc2.min_green_share = None
    sc2.green_shortfall_penalty_cny_mwh = None

    if hours is None:
        hours = list(range(0, 24, max(1, int(stride))))
    else:
        hours = [int(h) for h in hours]

    base_mw = None
    if baseline_art and baseline_art.get("series", {}).get("site_grid_mw"):
        base_mw = list(baseline_art["series"]["site_grid_mw"])

    rows = []
    for h in hours:
        # 已锁定小时：直接取 prior 关口，包络退化为点（体现收缩）
        if stage in (STAGE_ID, STAGE_RT) and prior_result is not None and h < from_t:
            site = _site_mw(prior_result["df"], sc2)
            ref = base_mw[h] if base_mw and h < len(base_mw) else site[h]
            val = float(site[h])
            rows.append({
                "hour": h, "p_up_mw": val, "p_down_mw": val, "bandwidth_mw": 0.0,
                "baseline_mw": ref, "headroom_up_mw": 0.0, "headroom_down_mw": 0.0,
                "ok": True, "locked": True,
            })
            continue
        bounds = {}
        for sense, sense_name in (("max", "up"), ("min", "down")):
            # Build a normal solve model via internal helper — reuse eng with roll + custom obj
            roll = None
            if stage == STAGE_ID:
                roll = {"from_t": from_t, "prior": prior_result, "fix_gens": False,
                        "envelope_hour": h, "envelope_sense": sense}
            elif stage == STAGE_RT:
                roll = {"from_t": 24, "prior": prior_result, "fix_gens": False,
                        "envelope_hour": h, "envelope_sense": sense, "rt_storage_only": True,
                        "baseline_site_mw": base_mw}
            else:
                roll = {"from_t": 0, "prior": None, "fix_gens": False,
                        "envelope_hour": h, "envelope_sense": sense}
            try:
                r = eng.solve(sc2, optimize=True, solver_opts=solver_opts, levers=levers, roll=roll)
                site = _site_mw(r["df"], sc2)
                bounds[sense_name] = float(site[h])
                bounds[f"obj_{sense_name}"] = float(r["objective"])
                bounds["ok"] = True
            except Exception as e:
                bounds[sense_name] = None
                bounds["ok"] = False
                bounds["error"] = str(e)
                break
        ref = base_mw[h] if base_mw and h < len(base_mw) else None
        up = bounds.get("up"); down = bounds.get("down")
        rows.append({
            "hour": h,
            "p_up_mw": up,
            "p_down_mw": down,
            "bandwidth_mw": (None if up is None or down is None else float(up - down)),
            "baseline_mw": ref,
            "headroom_up_mw": (None if up is None or ref is None else float(up - ref)),
            "headroom_down_mw": (None if down is None or ref is None else float(ref - down)),
            "ok": bounds.get("ok", False),
            "error": bounds.get("error"),
        })

    # shrinking summary vs day-ahead if provided in baseline_art
    bws = [r["bandwidth_mw"] for r in rows if r.get("ok") and r.get("bandwidth_mw") is not None and not r.get("locked")]
    summary = {
        "stage": stage,
        "from_t": from_t,
        "n_hours": len(rows),
        "n_ok": sum(1 for r in rows if r["ok"]),
        "n_locked": sum(1 for r in rows if r.get("locked")),
        "mean_bandwidth_mw": float(np.mean(bws)) if bws else 0.0,
    }
    return {"ok": summary["n_ok"] > 0, "stage": stage, "from_t": from_t, "hours": rows, "summary": summary}


def shrink_report(env_da: dict, env_id: dict | None = None, env_rt: dict | None = None) -> dict:
    """对比三阶段带宽收缩。"""
    def _bw(env):
        if not env: return {}
        return {r["hour"]: r.get("bandwidth_mw") for r in env.get("hours", []) if r.get("ok")}
    da, iid, rt = _bw(env_da), _bw(env_id), _bw(env_rt)
    hours = sorted(set(da) | set(iid) | set(rt))
    rows = []
    for h in hours:
        a, b, c = da.get(h), iid.get(h), rt.get(h)
        rows.append({
            "hour": h, "bw_da": a, "bw_id": b, "bw_rt": c,
            "shrink_id_vs_da": (None if a is None or b is None or a <= 1e-9 else round(1 - b / a, 4)),
            "shrink_rt_vs_da": (None if a is None or c is None or a <= 1e-9 else round(1 - c / a, 4)),
        })
    return {"ok": True, "rows": rows}


# ─── real-time rules / MPC-lite ───────────────────────────────────────────────

@serialized_pyomo('tiered_realtime')
def realtime_track(
    signal_mw: list,
    *,
    tin0_c: float = 24.0,
    t_allow_max_c: float = 32.0,
    t_rec_max_c: float = 27.0,
    c_air: float = 0.15,
    c_mass: float = 0.8,
    ua_am: float = 0.4,
    ua_env: float = 0.05,
    tout_c: float | list = 30.0,
    it_heat_mw: list | None = None,
    cool_cap_mw: float = 40.0,
    cool_cop: float = 3.5,
    bat_power_mw: float = 10.0,
    bat_energy_mwh: float = 40.0,
    soc0: float = 0.5,
    soc_min: float = 0.15,
    soc_max: float = 0.9,
    eta_ch: float = 0.95,
    eta_dis: float = 0.95,
    dt_min: int = 10,
    mode: str = "mpc_lite",
    upc_horizon: int = 6,
    track_weight: float = 10.0,
    cool_weight: float = 1.0,
    thermal_weight: float = 50.0,
) -> dict:
    """分钟级跟踪调度信号：电池 + 冷却流量（规则或短视窗 QP/LP）。不替代日前/日内主 LP。"""
    import pyomo.environ as pyo
    n = len(signal_mw)
    dt_h = dt_min / 60.0
    if it_heat_mw is None:
        it_heat_mw = [max(0.0, float(s) * 0.7) for s in signal_mw]  # 粗代理
    if isinstance(tout_c, (int, float)):
        tout = [float(tout_c)] * n
    else:
        tout = [float(x) for x in tout_c]
        if len(tout) < n:
            tout = tout + [tout[-1]] * (n - len(tout))

    if mode == "rules":
        return _rt_rules(signal_mw, it_heat_mw, tout, tin0_c, t_allow_max_c, t_rec_max_c,
                         c_air, c_mass, ua_am, ua_env, cool_cap_mw, cool_cop,
                         bat_power_mw, bat_energy_mwh, soc0, soc_min, soc_max, eta_ch, eta_dis, dt_h)

    # MPC-lite: rolling short-horizon LP
    tin, tm = float(tin0_c), float(tin0_c)
    soc = float(np.clip(soc0, soc_min, soc_max)) * bat_energy_mwh
    rows = []
    for k in range(n):
        H = min(upc_horizon, n - k)
        m = pyo.ConcreteModel()
        I = range(H)
        m.p_bat = pyo.Var(I, bounds=(-bat_power_mw, bat_power_mw))  # +放电 -充电
        m.qcool = pyo.Var(I, bounds=(0, cool_cap_mw))
        m.soc = pyo.Var(I, bounds=(soc_min * bat_energy_mwh, soc_max * bat_energy_mwh))
        m.ta = pyo.Var(I)
        m.tm = pyo.Var(I)
        m.e_pos = pyo.Var(I, within=pyo.NonNegativeReals)
        m.e_neg = pyo.Var(I, within=pyo.NonNegativeReals)
        m.texc = pyo.Var(I, within=pyo.NonNegativeReals)
        c = m.c = pyo.ConstraintList()
        for i in I:
            # site ≈ IT + cool_e - bat_discharge (+ bat_charge)
            cool_e = m.qcool[i] / max(cool_cop, 1e-6)
            site = it_heat_mw[k + i] + cool_e - m.p_bat[i]
            c.add(m.e_pos[i] - m.e_neg[i] == site - float(signal_mw[k + i]))
            prev_soc = soc if i == 0 else m.soc[i - 1]
            # p_bat>0 discharge
            c.add(m.soc[i] == prev_soc - dt_h * m.p_bat[i] / eta_dis * (1) )  # linear approx; refine below
            # Better SOC: split would need two vars; use signed approx with efficiency around 1 for lite
            prev_a = tin if i == 0 else m.ta[i - 1]
            prev_m = tm if i == 0 else m.tm[i - 1]
            # RC: C_a dTa = IT - qcool - UA_am(Ta-Tm) + UA_env(Tout-Ta)
            c.add(c_air * (m.ta[i] - prev_a) == dt_h * (
                float(it_heat_mw[k + i]) - m.qcool[i] - ua_am * (m.ta[i] - m.tm[i]) + ua_env * (tout[k + i] - m.ta[i])))
            c.add(c_mass * (m.tm[i] - prev_m) == dt_h * ua_am * (m.ta[i] - m.tm[i]))
            c.add(m.ta[i] <= t_allow_max_c)
            c.add(m.texc[i] >= m.ta[i] - t_rec_max_c)
        # Fix SOC dynamics with charge/discharge efficiencies via two nonnegative vars
        # Rebuild bat as ch/dis for first step accuracy — keep lite signed for speed; clamp after
        m.obj = pyo.Objective(expr=sum(
            track_weight * (m.e_pos[i] + m.e_neg[i])
            + cool_weight * m.qcool[i] / max(cool_cop, 1e-6)
            + thermal_weight * m.texc[i] for i in I))
        opt = pyo.SolverFactory("appsi_highs")
        try:
            res = checked_solve(opt,m,load_solutions=False)
            tc = str(res.solver.termination_condition)
            if tc != "optimal":
                # fallback rules for this step
                step = _rt_rules(signal_mw[k:k+1], it_heat_mw[k:k+1], tout[k:k+1], tin, t_allow_max_c, t_rec_max_c,
                                 c_air, c_mass, ua_am, ua_env, cool_cap_mw, cool_cop,
                                 bat_power_mw, bat_energy_mwh, soc / bat_energy_mwh, soc_min, soc_max,
                                 eta_ch, eta_dis, dt_h)
                row = step["trajectory"][0]
                tin, tm, soc = row["tin_c"], row.get("tmass_c", tin), row["soc_mwh"]
                rows.append({**row, "mode": "rules_fallback", "k": k})
                continue
            m.solutions.load_from(res)
            v = pyo.value
            p_bat = float(v(m.p_bat[0]))
            qcool = float(v(m.qcool[0]))
            tin = float(v(m.ta[0])); tm = float(v(m.tm[0]))
            # apply SOC with efficiency
            if p_bat >= 0:
                soc = soc - dt_h * p_bat / max(eta_dis, 1e-6)
            else:
                soc = soc - dt_h * p_bat * eta_ch  # p_bat negative → charge
            soc = float(np.clip(soc, soc_min * bat_energy_mwh, soc_max * bat_energy_mwh))
            cool_e = qcool / max(cool_cop, 1e-6)
            site = float(it_heat_mw[k]) + cool_e - p_bat
            rows.append({
                "k": k, "t_min": k * dt_min, "signal_mw": float(signal_mw[k]), "site_mw": site,
                "track_err_mw": site - float(signal_mw[k]), "bat_mw": p_bat, "cool_mwth": qcool,
                "cool_e_mw": cool_e, "tin_c": tin, "tmass_c": tm, "soc_mwh": soc,
                "soc_frac": soc / max(bat_energy_mwh, 1e-9), "mode": "mpc_lite",
                "thermal_exc_k": max(0.0, tin - t_rec_max_c),
            })
        except Exception as e:
            step = _rt_rules(signal_mw[k:k+1], it_heat_mw[k:k+1], tout[k:k+1], tin, t_allow_max_c, t_rec_max_c,
                             c_air, c_mass, ua_am, ua_env, cool_cap_mw, cool_cop,
                             bat_power_mw, bat_energy_mwh, soc / bat_energy_mwh, soc_min, soc_max,
                             eta_ch, eta_dis, dt_h)
            row = step["trajectory"][0]
            tin, tm, soc = row["tin_c"], row.get("tmass_c", tin), row["soc_mwh"]
            rows.append({**row, "mode": "rules_fallback", "k": k, "error": str(e)})

    traj = rows
    return {
        "ok": True, "mode": mode, "dt_min": dt_min,
        "rmse_mw": float(np.sqrt(np.mean([r["track_err_mw"] ** 2 for r in traj]))),
        "max_abs_err_mw": float(max(abs(r["track_err_mw"]) for r in traj)),
        "max_tin_c": float(max(r["tin_c"] for r in traj)),
        "thermal_violation": any(r["tin_c"] > t_allow_max_c + 1e-6 for r in traj),
        "trajectory": traj,
    }


def _rt_rules(signal, it_heat, tout, tin, t_allow, t_rec, c_air, c_mass, ua_am, ua_env,
              cool_cap, cool_cop, bat_p, bat_e, soc0, soc_min, soc_max, eta_ch, eta_dis, dt_h):
    tin, tm = float(tin), float(tin)
    soc = float(np.clip(soc0, soc_min, soc_max)) * bat_e
    rows = []
    for k, sig in enumerate(signal):
        # cooling: PI-like toward t_rec
        need = float(it_heat[k]) + ua_env * (tout[k] - tin)
        # if hot, cool more
        if tin > t_rec:
            need += (tin - t_rec) * (c_air + c_mass) / max(dt_h, 1e-6) * 0.5
        qcool = float(np.clip(need, 0, cool_cap))
        cool_e = qcool / max(cool_cop, 1e-6)
        # Track signal: site = IT + cool_e - p_bat (+p_bat = discharge), same as mpc_lite.
        # When facility above signal, discharge; when below, charge.
        need_discharge = (float(it_heat[k]) + cool_e) - float(sig)
        p_bat = float(np.clip(need_discharge, -bat_p, bat_p))
        # SOC corridor: prevent aggressive charge near full / discharge near empty
        if p_bat > 0 and soc <= soc_min * bat_e + 1e-6:
            p_bat = 0.0
        if p_bat < 0 and soc >= soc_max * bat_e - 1e-6:
            p_bat = 0.0
        # anti secondary peak: if previously discharged hard, limit charge ramp (simple)
        site = float(it_heat[k]) + cool_e - p_bat
        # RC update
        dTa = dt_h / max(c_air, 1e-6) * (float(it_heat[k]) - qcool - ua_am * (tin - tm) + ua_env * (tout[k] - tin))
        dTm = dt_h / max(c_mass, 1e-6) * ua_am * (tin - tm)
        tin = float(np.clip(tin + dTa, -10, t_allow + 5))
        tm = tm + dTm
        if p_bat >= 0:
            soc = soc - dt_h * p_bat / max(eta_dis, 1e-6)
        else:
            soc = soc - dt_h * p_bat * eta_ch
        soc = float(np.clip(soc, soc_min * bat_e, soc_max * bat_e))
        rows.append({
            "k": k, "t_min": k * int(round(dt_h * 60)), "signal_mw": float(sig), "site_mw": site,
            "track_err_mw": site - float(sig), "bat_mw": p_bat, "cool_mwth": qcool,
            "cool_e_mw": cool_e, "tin_c": tin, "tmass_c": tm, "soc_mwh": soc,
            "soc_frac": soc / max(bat_e, 1e-9), "mode": "rules",
            "thermal_exc_k": max(0.0, tin - t_rec),
        })
    return {
        "ok": True, "mode": "rules", "dt_min": int(round(dt_h * 60)),
        "rmse_mw": float(np.sqrt(np.mean([r["track_err_mw"] ** 2 for r in rows]))),
        "max_abs_err_mw": float(max(abs(r["track_err_mw"]) for r in rows)),
        "max_tin_c": float(max(r["tin_c"] for r in rows)),
        "thermal_violation": any(r["tin_c"] > t_allow + 1e-6 for r in rows),
        "trajectory": rows,
    }


# ─── coupling report ──────────────────────────────────────────────────────────

def coupling_report(sc, result: dict) -> dict:
    """负载率 ↔ 冷却流量 / 关口功率 双层对照表。"""
    df = result["df"]
    rows = []
    for d in sc.data_centers:
        n = d.name
        cap = max(float(d.cap_it_mw), 1e-9)
        for t in range(len(df)):
            it = float(df.loc[t, f"{n}_IT_MW"]) if f"{n}_IT_MW" in df else float(df.loc[t, f"{n}_IT_work_MW"]) if f"{n}_IT_work_MW" in df else 0.0
            grid = float(df.loc[t, f"{n}_grid_MW"]) if f"{n}_grid_MW" in df else it
            cool = float(df.loc[t, f"{n}_cool_MW"]) if f"{n}_cool_MW" in df else max(0.0, grid - it)
            chiller = float(df.loc[t, f"{n}_chiller_MWth"]) if f"{n}_chiller_MWth" in df else None
            tin = float(df.loc[t, f"{n}_Tin_C"]) if f"{n}_Tin_C" in df else None
            pue = float(df.loc[t, f"{n}_PUE"]) if f"{n}_PUE" in df else (grid / max(it, 1e-9))
            rows.append({
                "dc": n, "hour": t, "it_mw": round(it, 4), "load_rate": round(it / cap, 4),
                "cool_e_mw": round(cool, 4), "chiller_mwth": None if chiller is None else round(chiller, 4),
                "grid_mw": round(grid, 4), "pue": round(pue, 4),
                "tin_c": None if tin is None else round(tin, 3),
            })
    # aggregates
    by_h = {}
    for r in rows:
        h = r["hour"]
        by_h.setdefault(h, {"hour": h, "it_mw": 0, "cool_e_mw": 0, "grid_mw": 0})
        by_h[h]["it_mw"] += r["it_mw"]; by_h[h]["cool_e_mw"] += r["cool_e_mw"]; by_h[h]["grid_mw"] += r["grid_mw"]
    site = [by_h[h] for h in sorted(by_h)]
    corr = None
    if len(site) >= 3:
        a = np.array([x["it_mw"] for x in site]); b = np.array([x["cool_e_mw"] for x in site])
        if a.std() > 1e-9 and b.std() > 1e-9:
            corr = float(np.corrcoef(a, b)[0, 1])
    return {
        "ok": True,
        "rows": rows,
        "site_hourly": site,
        "corr_it_cool": corr,
        "note": "经济层看 grid/it 时移；热安全层看 tin/chiller；二者经负载率→发热→冷量耦合",
    }


def compare_tiers(baseline_result: dict, rolling_result: dict | None = None,
                  rt_result: dict | None = None) -> dict:
    """成本 / 碳 / 热违约 对照。"""
    def pack(tag, r):
        if r is None: return None
        th = r.get("thermal") or {}
        return {
            "tag": tag,
            "cost_cny": round(float(r.get("cost_cny", r.get("objective", 0))), 2),
            "objective_cny": round(float(r.get("objective", 0)), 2),
            "emissions_tco2": round(float(r.get("emissions_t", 0)), 4),
            "thermal_safe": th.get("safe"),
            "thermal_violations": th.get("violations"),
            "curtail_mwh": round(float(r.get("curtail_mwh", 0)), 3),
        }
    rows = [pack("day_ahead", baseline_result)]
    if rolling_result: rows.append(pack("intra_day", rolling_result))
    if rt_result and "rmse_mw" in rt_result:
        rows.append({"tag": "real_time", "rmse_mw": rt_result["rmse_mw"],
                     "max_tin_c": rt_result.get("max_tin_c"),
                     "thermal_violation": rt_result.get("thermal_violation")})
    da = rows[0]
    deltas = []
    for r in rows[1:]:
        if r and "cost_cny" in r and da:
            deltas.append({
                "vs": r["tag"],
                "d_cost_cny": round(r["cost_cny"] - da["cost_cny"], 2),
                "d_emissions_t": round(r["emissions_tco2"] - da["emissions_tco2"], 4),
            })
    return {"ok": True, "rows": [x for x in rows if x], "deltas_vs_day_ahead": deltas}



# ─── SOC 实测 / UPS·柴发资源 ─────────────────────────────────────────────────

def parse_soc_measured_nl(text: str) -> dict:
    """中文 → soc_measured 草稿。例：「SOC实测0.42」「储能ESS_ZW荷电状态0.35」「电池SOC少5个百分点」。"""
    out: dict[str, Any] = {}
    if not text:
        return out
    # named
    for m in re.finditer(r"(?:储能|电池|UPS|ups)?\s*([A-Za-z0-9_\u4e00-\u9fff]+)?\s*(?:的)?\s*(?:SOC|soc|荷电状态)\s*(?:实测|测量|更新)?\s*(?:为|=|到|:)?\s*(\d+(?:\.\d+)?)\s*(%|％|p\.u\.|pu)?", text):
        name = (m.group(1) or "").strip() or "_default"
        val = float(m.group(2)); unit = (m.group(3) or "").strip()
        if unit in ("%", "％") or val > 1.0 + 1e-9:
            val = val / 100.0
        out.setdefault("by_name", {})[name] = {"value": val, "unit": "frac", "source": "nl"}
    if "by_name" not in out:
        m = re.search(r"(?:SOC|soc|荷电状态).{0,6}(?:实测|测量|更新)?.{0,4}(\d+(?:\.\d+)?)", text)
        if m:
            val = float(m.group(1))
            if val > 1.0: val /= 100.0
            out["by_name"] = {"_default": {"value": val, "unit": "frac", "source": "nl"}}
    m = re.search(r"SOC.{0,4}(?:少|降|低|偏少)\s*(\d+(?:\.\d+)?)\s*(?:个)?(?:百分点|%)?", text)
    if m:
        out["delta_frac"] = -float(m.group(1)) / 100.0
        out["delta_source"] = "nl"
    m = re.search(r"SOC.{0,4}(?:多|升|高|偏高)\s*(\d+(?:\.\d+)?)\s*(?:个)?(?:百分点|%)?", text)
    if m:
        out["delta_frac"] = float(m.group(1)) / 100.0
        out["delta_source"] = "nl"
    return out


def load_soc_measured_file(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    if isinstance(raw, dict) and "soc_measured" in raw:
        return raw["soc_measured"]
    return raw if isinstance(raw, dict) else {}


def normalize_soc_measured(raw, sc, prior_result: dict | None = None, from_t: int = 0) -> dict:
    """统一为 {mwh:{name:MWh}, frac:{name:p.u.}, source, deviation, ...}。

    接受：
      - None / {} → 来源 day_ahead_prior（不修正）
      - {name: 0.42} 或 {name: {"value":0.42,"unit":"frac"|"mwh"|"%"}}
      - {"ESS": 0.4, "unit": "frac"}
      - NL parse / 文件内容（含 by_name / delta_frac）
    """
    from_t = int(max(0, min(23, from_t)))
    sto = {s.name: s for s in (getattr(sc, "storage", None) or [])}
    if not sto:
        return {"mwh": {}, "frac": {}, "source": "none", "deviation": [], "note": "场景无储能"}
    prior_frac = {}
    if prior_result is not None and "df" in prior_result:
        df = prior_result["df"]
        t_ref = max(0, from_t - 1) if from_t > 0 else 0
        for n, s in sto.items():
            col = f"{n}_soc"
            if col in df.columns:
                prior_frac[n] = float(df.loc[t_ref, col]) / max(float(s.energy_mwh), 1e-9)
            else:
                prior_frac[n] = float(s.soc0)
    else:
        prior_frac = {n: float(s.soc0) for n, s in sto.items()}

    if not raw:
        return {
            "mwh": {}, "frac": {}, "source": "day_ahead_prior",
            "prior_frac": prior_frac, "deviation": [],
            "note": "未提供实测，滚动沿用日前锁定 SOC 轨迹",
        }

    data = dict(raw)
    if "by_name" in data and isinstance(data["by_name"], dict):
        for k, v in data["by_name"].items():
            data[k] = v
    global_unit = data.get("unit") or data.get("default_unit") or "frac"
    delta = data.get("delta_frac")
    skip = {"unit", "default_unit", "by_name", "delta_frac", "delta_source", "source", "note", "path"}
    mwh: dict[str, float] = {}
    frac: dict[str, float] = {}
    sources: dict[str, str] = {}

    def _one(name: str, spec):
        S = sto.get(name)
        if S is None:
            return
        if isinstance(spec, dict):
            raw_v = spec.get("value", spec.get("soc", spec.get("frac", spec.get("mwh"))))
            if raw_v is None:
                return
            val = float(raw_v)
            unit = (spec.get("unit") or global_unit or "frac").lower()
            src = spec.get("source") or "api"
        else:
            val = float(spec); unit = str(global_unit).lower(); src = "api"
        if unit in ("%", "percent", "pct"):
            val = val / 100.0; unit = "frac"
        if unit in ("mwh", "abs"):
            f = val / max(float(S.energy_mwh), 1e-9)
        else:
            f = val
        f = float(np.clip(f, float(S.soc_min), float(S.soc_max)))
        frac[name] = f
        mwh[name] = f * float(S.energy_mwh)
        sources[name] = src

    for k, v in list(data.items()):
        if k in skip or k == "_default":
            continue
        if isinstance(v, (int, float, dict)) and k in sto:
            _one(k, v)

    if "_default" in data:
        for n in sto:
            if n not in mwh:
                _one(n, data["_default"])

    if delta is not None and not mwh:
        for n, pf in prior_frac.items():
            _one(n, {"value": float(np.clip(pf + float(delta), 0, 1)), "unit": "frac",
                     "source": data.get("delta_source") or "delta"})

    if not mwh:
        nums = [(k, v) for k, v in data.items() if k not in skip and isinstance(v, (int, float))]
        if len(sto) == 1 and nums:
            _one(next(iter(sto)), nums[0][1])

    deviation = []
    for n, f in frac.items():
        pf = prior_frac.get(n)
        deviation.append({
            "name": n,
            "measured_frac": round(f, 6),
            "measured_mwh": round(mwh[n], 6),
            "prior_frac": None if pf is None else round(pf, 6),
            "prior_mwh": None if pf is None else round(pf * float(sto[n].energy_mwh), 6),
            "delta_frac": None if pf is None else round(f - pf, 6),
            "delta_mwh": None if pf is None else round(mwh[n] - pf * float(sto[n].energy_mwh), 6),
            "unit": "p.u. / MWh",
            "source": sources.get(n, "api"),
            "from_t": from_t,
        })
    source = "measured" if mwh else "day_ahead_prior"
    return {
        "mwh": mwh, "frac": frac, "source": source, "prior_frac": prior_frac,
        "deviation": deviation, "sources": sources,
        "note": ("滚动在 from_t 以实测 SOC 作为自由窗初值；t<from_t 仍锁定日前轨迹"
                 if mwh else "无实测修正"),
    }



def attach_backup_resources(sc, ups=None, diesel=None, emergency_mode: bool | None = None, replace: bool = False):
    """向场景附加 UPS / 柴发（默认不调用=无资源）。参数需带 source_note；缺省填【假设】。

    ups: dict | list[dict] — energy_mwh/power_mw/eta_*/soc*/reserve_frac/bus/name/dc
    diesel: dict | list[dict] — pmax_mw/pmin_mw/ramp_mw_h/cost/emission/bus/name/dispatch_mode
    """
    from ..scenario import Storage, NetGen
    sc2 = copy.deepcopy(sc)
    notes = []
    if emergency_mode is not None:
        sc2.emergency_mode = bool(emergency_mode)
        notes.append(f"emergency_mode={sc2.emergency_mode}")

    def _ups_one(u: dict, idx: int):
        u = dict(u or {})
        # size defaults from first DC 【假设】
        d0 = sc2.data_centers[0] if sc2.data_centers else None
        bus = int(u.get("bus", d0.bus if d0 else 0))
        it = float(d0.cap_it_mw) if d0 else 10.0
        # 【假设】UPS：0.25 h×IT 容量、效率 0.94、日常保留 50% 备用带
        e = float(u.get("energy_mwh", round(it * 0.25, 3)))
        pw = float(u.get("power_mw", round(it, 3)))
        name = u.get("name") or f"UPS_{idx+1}"
        src = u.get("source_note") or "【假设】EUPS：能量≈0.25h×IT装机、η=0.94、reserve_frac=0.5（非现场铭牌）"
        st = Storage(
            name=name, bus=bus, energy_mwh=e, power_mw=pw,
            eta_ch=float(u.get("eta_ch", u.get("eta", 0.94))),
            eta_dis=float(u.get("eta_dis", u.get("eta", 0.94))),
            soc0=float(u.get("soc0", 0.9)), soc_min=float(u.get("soc_min", 0.2)),
            soc_max=float(u.get("soc_max", 0.95)), kind="ups",
            reserve_frac=float(u.get("reserve_frac", 0.5)), source_note=src,
        )
        return st, src

    def _dg_one(d: dict, idx: int):
        d = dict(d or {})
        d0 = sc2.data_centers[0] if sc2.data_centers else None
        bus = int(d.get("bus", d0.bus if d0 else 0))
        it = float(sum(x.cap_it_mw for x in sc2.data_centers)) if sc2.data_centers else 10.0
        # 【假设】柴发：覆盖全站 IT+冷却裕度约 1.3×IT，成本 1800 元/MWh，排放 0.7 t/MWh，爬坡=Pmax
        pmax = float(d.get("pmax_mw", round(it * 1.3, 1)))
        src = d.get("source_note") or "【假设】柴发：Pmax≈1.3×ΣIT、成本1800元/MWh、排放0.7t/MWh、连续爬坡模型（非现场铭牌；GB50174语境备用）"
        g = NetGen(
            name=d.get("name") or f"DG_{idx+1}", bus=bus, kind="diesel",
            pmax_mw=pmax, pmin_mw=float(d.get("pmin_mw", 0.0)),
            cost_cny_mwh=float(d.get("cost_cny_mwh", 1800.0)),
            emission_t_mwh=float(d.get("emission_t_mwh", 0.7)),
            ramp_mw_h=d.get("ramp_mw_h", pmax),
            startup_cost_cny=float(d.get("startup_cost_cny", 0.0)),
            min_up_h=int(d.get("min_up_h", 0)),
            dispatch_mode=d.get("dispatch_mode") or "emergency_only",
            source_note=src,
        )
        return g, src

    if replace:
        sc2.storage = [s for s in sc2.storage if (getattr(s, "kind", "ess") or "ess") != "ups"]
        if sc2.network and sc2.network.gens:
            sc2.network.gens = [g for g in sc2.network.gens if (g.kind or "") != "diesel"]

    if ups is not None:
        items = ups if isinstance(ups, list) else [ups]
        # ups=True → 默认一套
        if ups is True:
            items = [{}]
        for i, u in enumerate(items):
            if u is False: continue
            st, src = _ups_one(u if isinstance(u, dict) else {}, i)
            # avoid name clash
            names = {s.name for s in sc2.storage}
            if st.name in names:
                st.name = f"{st.name}_{i}"
            sc2.storage.append(st)
            notes.append(f"UPS {st.name}: E={st.energy_mwh}MWh P={st.power_mw}MW η={st.eta_ch}/{st.eta_dis} reserve={st.reserve_frac} | {src}")
            sc2.sources[f"UPS:{st.name}"] = src

    if diesel is not None:
        if sc2.network_case != "custom" or sc2.network is None:
            raise ValueError("柴发需 custom 网络（network_case='custom'）；IEEE14 预设请先切自定义网或仅用 UPS")
        if diesel is True:
            # 多 DC：默认每座数据中心母线一套【假设】柴发（GB50174 语境就地备用）
            if len(sc2.data_centers) > 1:
                items = [{"name": f"DG_{d.name}", "bus": d.bus,
                          "pmax_mw": round(float(d.cap_it_mw) * 1.5, 1),
                          "ramp_mw_h": round(float(d.cap_it_mw) * 1.5, 1),
                          "source_note": f"【假设】{d.name} 就地柴发 Pmax=1.5×IT（含冷却裕度，非铭牌）"}
                         for d in sc2.data_centers]
            else:
                items = [{}]
        else:
            items = diesel if isinstance(diesel, list) else [diesel]
        for i, d in enumerate(items):
            if d is False: continue
            g, src = _dg_one(d if isinstance(d, dict) else {}, i)
            names = {x.name for x in sc2.network.gens}
            if g.name in names:
                g.name = f"{g.name}_{i}"
            sc2.network.gens.append(g)
            notes.append(f"柴发 {g.name}: Pmax={g.pmax_mw}MW ramp={g.ramp_mw_h} mode={g.dispatch_mode} | {src}")
            sc2.sources[f"diesel:{g.name}"] = src

    return sc2, {"ok": True, "notes": notes, "emergency_mode": sc2.emergency_mode,
                 "n_ups": sum(1 for s in sc2.storage if (getattr(s, "kind", "ess") or "ess") == "ups"),
                 "n_diesel": sum(1 for g in (sc2.network.gens if sc2.network else []) if g.kind == "diesel")}


def backup_resource_params(sc) -> dict:
    """透明列出当前场景 UPS/柴发参数（值/单位/来源）。"""
    rows = []
    for s in sc.storage or []:
        if (getattr(s, "kind", "ess") or "ess") != "ups":
            continue
        rows.append({"type": "ups", "name": s.name, "bus": s.bus,
                     "params": [
                         {"key": "energy_mwh", "value": s.energy_mwh, "unit": "MWh", "source": s.source_note or "场景"},
                         {"key": "power_mw", "value": s.power_mw, "unit": "MW", "source": s.source_note or "场景"},
                         {"key": "eta_ch", "value": s.eta_ch, "unit": "", "source": s.source_note or "场景"},
                         {"key": "eta_dis", "value": s.eta_dis, "unit": "", "source": s.source_note or "场景"},
                         {"key": "soc0", "value": s.soc0, "unit": "p.u.", "source": s.source_note or "场景"},
                         {"key": "soc_min", "value": s.soc_min, "unit": "p.u.", "source": s.source_note or "场景"},
                         {"key": "soc_max", "value": s.soc_max, "unit": "p.u.", "source": s.source_note or "场景"},
                         {"key": "reserve_frac", "value": s.reserve_frac, "unit": "", "source": s.source_note or "场景"},
                     ]})
    for g in (sc.network.gens if (sc.network_case == "custom" and sc.network) else []) or []:
        if g.kind != "diesel":
            continue
        rows.append({"type": "diesel", "name": g.name, "bus": g.bus,
                     "params": [
                         {"key": "pmax_mw", "value": g.pmax_mw, "unit": "MW", "source": g.source_note or "场景"},
                         {"key": "pmin_mw", "value": g.pmin_mw, "unit": "MW", "source": g.source_note or "场景"},
                         {"key": "ramp_mw_h", "value": g.ramp_mw_h, "unit": "MW/h", "source": g.source_note or "场景"},
                         {"key": "cost_cny_mwh", "value": g.cost_cny_mwh, "unit": "元/MWh", "source": g.source_note or "场景"},
                         {"key": "emission_t_mwh", "value": g.emission_t_mwh, "unit": "tCO2/MWh", "source": g.source_note or "场景"},
                         {"key": "dispatch_mode", "value": g.dispatch_mode, "unit": "", "source": g.source_note or "场景"},
                         {"key": "startup_cost_cny", "value": g.startup_cost_cny, "unit": "元", "source": "简化未进目标" if g.startup_cost_cny else g.source_note or "场景"},
                         {"key": "min_up_h", "value": g.min_up_h, "unit": "h", "source": "简化未建模二进制" if g.min_up_h else g.source_note or "场景"},
                     ]})
    return {"ok": True, "emergency_mode": bool(getattr(sc, "emergency_mode", False)), "resources": rows}
