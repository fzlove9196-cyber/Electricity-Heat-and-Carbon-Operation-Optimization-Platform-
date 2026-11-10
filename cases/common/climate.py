"""真实气象（Open-Meteo 历史再分析 ERA5，免费、无需 Key）→ 典型日/极端日 24h 温度、湿度、风电/光伏出力系数。
https://open-meteo.com/en/docs/historical-weather-api ；结果缓存到 cases/common/climate/<site>_<year>.json。
风电/光伏折算为【假设】：100m 风速 → 通用 IEC II 类功率曲线（切入 3、额定 11.5、切出 25 m/s）×0.92 可用率/尾流；
光伏 = GHI/1000 × 0.82（系统效率+温升，固定倾角近似）。"""
import json, os, urllib.request
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); CACHE = os.path.join(HERE, "climate")
SITES = {  # 名称: (lat, lon, tz)
    "ulanqab": (41.03, 113.13, "Asia/Shanghai"), "shaoguan": (24.80, 113.60, "Asia/Shanghai"), "guian": (26.40, 106.50, "Asia/Shanghai"),
    "hangzhou_renhe": (30.45, 120.15, "Asia/Shanghai"), "wuhu": (31.33, 118.38, "Asia/Shanghai"), "shanghai_lingang": (30.90, 121.90, "Asia/Shanghai"),
    "odense": (55.40, 10.40, "Europe/Copenhagen"), "zhongwei": (37.50, 105.19, "Asia/Shanghai"), "hohhot_helinger": (40.38, 111.82, "Asia/Shanghai"),
}
URL = "https://archive-api.open-meteo.com/v1/archive?latitude={lat}&longitude={lon}&start_date={a}&end_date={b}&hourly=temperature_2m,relative_humidity_2m,wind_speed_100m,shortwave_radiation&timezone={tz}"

def fetch(site, year=2024, start=None, end=None):
    lat, lon, tz = SITES[site]; a, b = start or f"{year}-01-01", end or f"{year}-12-31"
    os.makedirs(CACHE, exist_ok=True); p = os.path.join(CACHE, f"{site}_{a}_{b}.json")
    if os.path.exists(p): return json.load(open(p))
    u = URL.format(lat=lat, lon=lon, a=a, b=b, tz=tz.replace("/", "%2F"))
    d = json.loads(urllib.request.urlopen(u, timeout=60).read()); d["_url"] = u
    json.dump(d, open(p, "w")); return d

def wind_cf(v_kmh):
    v = np.asarray(v_kmh, float)/3.6
    cf = np.where(v < 3, 0, np.where(v < 11.5, (v**3 - 27)/(11.5**3 - 27), np.where(v < 25, 1, 0)))
    return np.clip(cf*0.92, 0, 1)

def pv_cf(ghi): return np.clip(np.asarray(ghi, float)/1000*0.82, 0, 1)

def days(d):
    H = d["hourly"]; n = len(H["time"])//24
    f = lambda k: np.asarray([x if x is not None else np.nan for x in H[k]], float)[:n*24].reshape(n, 24)
    return dict(date=[H["time"][i*24][:10] for i in range(n)], T=f("temperature_2m"), RH=f("relative_humidity_2m"), W=f("wind_speed_100m"), G=f("shortwave_radiation"))

def pick(site, kind, year=2024):
    """kind: summer_typical/winter_typical（当月日均温最接近月中位数的日）、heatwave（6–8 月日最高温最高）、coldwave（12–2 月日均温最低）、
    lowwind/highwind（全年日均风电出力最低/最高）、date:YYYY-MM-DD。返回 24h 曲线 + 元数据（含 URL）。"""
    D = days(fetch(site, year)); dates = np.array(D["date"]); mon = np.array([int(x[5:7]) for x in dates])
    Tm = np.nanmean(D["T"], 1); wcf = np.array([wind_cf(w).mean() for w in D["W"]])
    if kind == "summer_typical": idx = np.where(mon == 7)[0]; i = idx[np.argmin(abs(Tm[idx] - np.median(Tm[idx])))]
    elif kind == "winter_typical": idx = np.where(mon == 1)[0]; i = idx[np.argmin(abs(Tm[idx] - np.median(Tm[idx])))]
    elif kind == "heatwave": idx = np.where((mon >= 6) & (mon <= 8))[0]; i = idx[np.argmax(np.nanmax(D["T"][idx], 1))]
    elif kind == "coldwave": idx = np.where((mon == 12) | (mon <= 2))[0]; i = idx[np.argmin(Tm[idx])]
    elif kind == "lowwind": i = int(np.argmin(wcf))
    elif kind == "highwind": i = int(np.argmax(wcf))
    else: i = int(np.where(dates == kind)[0][0])
    out = dict(site=site, kind=kind, date=str(dates[i]), T=[round(float(x), 1) for x in D["T"][i]], RH=[round(float(x)/100, 3) for x in D["RH"][i]],
               wind=[round(float(x), 4) for x in wind_cf(D["W"][i])], pv=[round(float(x), 4) for x in pv_cf(D["G"][i])],
               source=f"Open-Meteo ERA5 历史再分析 {site} {dates[i]}（{SITES[site][0]}N,{SITES[site][1]}E）https://open-meteo.com/")
    return out

def annual_cf(site, year=2024):
    """全年等效利用小时（用于与公开年发电量对比校验风/光折算模型）。"""
    D = days(fetch(site, year))
    return dict(wind_h=round(float(wind_cf(D["W"]).sum()), 0), pv_h=round(float(pv_cf(D["G"]).sum()), 0),
                t_mean=round(float(np.nanmean(D["T"])), 1), t_max=round(float(np.nanmax(D["T"])), 1), t_min=round(float(np.nanmin(D["T"])), 1))

if __name__ == "__main__":
    for s in SITES: print(s, annual_cf(s))
