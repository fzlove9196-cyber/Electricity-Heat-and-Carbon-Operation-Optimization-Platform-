"""逐时碳强度曲线（kgCO2/kWh = tCO2/MWh）。
默认：全国电网平均排放因子 0.5306 kgCO2/kWh（生态环境部 2023 年因子）× 合成日内形状（SYNTHETIC，日均值保持 0.5306）。
可选适配器（存根）：Carbon Aware SDK WebAPI / WattTime —— 通过设置 CARBON_SOURCE 启用，失败时回退合成曲线并标注。"""
from __future__ import annotations
import datetime as _dt
import numpy as np
from . import settings

NATIONAL_FACTOR = 0.5306
H = 24

def synthetic_shape(kind: str = "solar_dip") -> np.ndarray:
    """日内相对形状，均值 = 1。solar_dip：午间光伏多发碳强度低、晚高峰火电顶峰碳强度高（合成）。"""
    h = np.arange(H)
    if kind == "flat": return np.ones(H)
    pv = np.clip(np.sin((h - 6) / 12 * np.pi), 0, None)
    eve = np.exp(-((h - 19.5) / 2.5) ** 2)
    s = 1.0 - 0.30 * pv + 0.12 * eve
    return s / s.mean()

def synthetic_profile(factor: float = NATIONAL_FACTOR, kind: str = "solar_dip") -> list[float]:
    return [round(float(x), 4) for x in factor * synthetic_shape(kind)]

def carbon_aware_sdk_profile(location: str, base_url: str, day: _dt.date | None = None) -> list[float]:
    """Carbon Aware SDK WebAPI：GET /emissions/bylocation?location=..&time=..&toTime=..，rating 单位 gCO2/kWh。"""
    import httpx
    day = day or _dt.date.today()
    t0 = _dt.datetime.combine(day, _dt.time()); t1 = t0 + _dt.timedelta(days=1)
    r = httpx.get(base_url.rstrip("/") + "/emissions/bylocation", params=dict(location=location, time=t0.isoformat(), toTime=t1.isoformat()), timeout=10)
    r.raise_for_status(); data = r.json()
    hourly = [[] for _ in range(H)]
    for d in data:
        hr = _dt.datetime.fromisoformat(d["time"].replace("Z", "+00:00")).hour
        hourly[hr].append(float(d["rating"]) / 1000.0)
    if not all(hourly): raise RuntimeError("Carbon Aware SDK 返回的逐时数据不完整")
    return [round(float(np.mean(x)), 4) for x in hourly]

def watttime_profile(region: str, user: str, password: str) -> list[float]:
    """WattTime v3 存根：需账号；返回 MOER(lbs/MWh) 需换算。此处未实现在线调用。"""
    raise NotImplementedError("WattTime 适配器为存根：请配置账号并实现 /v3/forecast 调用（MOER lbs/MWh × 0.4536/1000 → t/MWh）")


def file_hourly_profile(path: str) -> list[float]:
    """从本地 CSV/JSON 读逐时碳强度（tCO2/MWh 或 kgCO2/kWh 同数值）。
    CSV: hour,ci 或 timestamp,carbon_intensity_kg_kwh；JSON: [24 floats] 或 {"profile":[...]}。
    """
    import json, csv
    if not path or not __import__("os").path.isfile(path):
        raise FileNotFoundError(f"碳强度文件不存在: {path}")
    if path.lower().endswith(".json"):
        data = json.load(open(path, encoding="utf-8"))
        if isinstance(data, list):
            arr = [float(x) for x in data]
        elif isinstance(data, dict) and "profile" in data:
            arr = [float(x) for x in data["profile"]]
        else:
            raise ValueError("JSON 需为长度 24 的数组或含 profile 字段")
    else:
        rows = list(csv.DictReader(open(path, encoding="utf-8")))
        if not rows: raise ValueError("碳强度 CSV 为空")
        keys = {k.lower(): k for k in rows[0]}
        ck = keys.get("ci") or keys.get("carbon_intensity") or keys.get("carbon_intensity_kg_kwh") or keys.get("kgco2_kwh") or keys.get("tco2_mwh") or keys.get("value")
        if ck is None: raise ValueError(f"CSV 缺碳强度列，现有={list(rows[0])}")
        arr = [float(r[ck]) for r in rows]
    if len(arr) == 1: arr = arr * H
    if len(arr) >= 8760:  # 取首日
        arr = arr[:H]
    if len(arr) != H:
        # 折到 24：按小时聚合或截断/填充
        if len(arr) > H: arr = arr[:H]
        else: arr = arr + [arr[-1]] * (H - len(arr))
    return [round(float(x), 4) for x in arr]


def url_hourly_profile(url: str) -> list[float]:
    """GET JSON 数组或 {profile:[...]}；失败抛错由 get_profile 回退。"""
    import httpx, json
    r = httpx.get(url, timeout=10); r.raise_for_status()
    data = r.json()
    if isinstance(data, list): arr = data
    elif isinstance(data, dict) and "profile" in data: arr = data["profile"]
    elif isinstance(data, dict) and "emissions" in data:
        # 兼容粗粒度 SDK 风格
        arr = [float(x.get("rating", x.get("value", 0))) / 1000.0 for x in data["emissions"]]
    else:
        raise ValueError("URL JSON 无法解析为 24h 碳强度")
    if len(arr) != H:
        if len(arr) > H: arr = arr[:H]
        else: arr = list(arr) + [arr[-1]] * (H - len(arr))
    return [round(float(x), 4) for x in arr]

def get_profile(region: str = "national", factor: float = NATIONAL_FACTOR, shape: str = "solar_dip") -> dict:
    """返回 {profile, source, synthetic}。按设置 CARBON_SOURCE = synthetic(默认) | carbon_aware_sdk | watttime。"""
    src = (settings.get("CARBON_SOURCE", "synthetic") or "synthetic").lower()
    try:
        if src == "file" and settings.get("CARBON_FILE"):
            path = settings.get("CARBON_FILE")
            return dict(profile=file_hourly_profile(path), source=f"file:{path}", synthetic=False)
        if src == "url" and settings.get("CARBON_URL"):
            url = settings.get("CARBON_URL")
            return dict(profile=url_hourly_profile(url), source=f"url:{url}", synthetic=False)
        if src == "carbon_aware_sdk" and settings.get("CARBON_AWARE_URL"):
            loc = settings.get("CARBON_LOCATION") or region
            return dict(profile=carbon_aware_sdk_profile(loc, settings.get("CARBON_AWARE_URL")), source=f"carbon_aware_sdk:{loc}", synthetic=False)
        if src == "watttime":
            return dict(profile=watttime_profile(region, settings.get("WATTTIME_USER"), settings.get("WATTTIME_PASSWORD")), source="watttime", synthetic=False)
    except Exception as e:
        return dict(profile=synthetic_profile(factor, shape), source=f"synthetic(回退: {type(e).__name__}: {str(e)[:120]})", synthetic=True)
    return dict(profile=synthetic_profile(factor, shape), source=f"synthetic:{shape}×{factor}", synthetic=True)
