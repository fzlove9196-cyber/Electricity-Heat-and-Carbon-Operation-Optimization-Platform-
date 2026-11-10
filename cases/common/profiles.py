"""多案例共用：典型日风/光出力形状、分时电价、数据中心负荷构造（形状均为【假设】，按公开年利用小时校准）。"""
import numpy as np
h = np.arange(24)

def pv(util_h_year, season="summer", sunrise=None, sunset=None):
    a, b = (sunrise or (6.0 if season == "summer" else 8.0)), (sunset or (20.0 if season == "summer" else 18.0))
    x = np.clip(np.sin((h + 0.5 - a)/(b - a)*np.pi), 0, None); x[(h + 0.5 < a) | (h + 0.5 > b)] = 0
    x = x*(1.0 if season == "summer" else 0.8)
    k = util_h_year/8760/np.mean(x if season == "summer" else x/0.8)   # 以夏季形状校准年均，冬季再乘 0.8
    return [round(float(v), 4) for v in np.clip(x*k, 0, 1)]

def wind(cf, night_peak_h=2, amp=0.35):
    w = 1 + amp*np.cos(2*np.pi*(h - night_peak_h)/24)
    return [round(float(v), 4) for v in np.clip(w/w.mean()*cf, 0, 1)]

def tou(peak, flat, valley, peak_hours, valley_hours):
    return [peak if t in peak_hours else valley if t in valley_hours else flat for t in h]

def dc(name, bus, peak_mw, pue, util=0.8, flex=0.25, peak_h=20):
    """peak_mw：电网侧峰值负荷 MW；IT 容量 = peak/PUE；平均 IT = util×IT 容量；flex 为可时移批处理比例。"""
    cap = peak_mw/pue; avg = util*cap
    inter = (1 - flex)*avg*(1 + 0.06*np.cos(2*np.pi*(h - peak_h)/24))
    return dict(name=name, bus=bus, cap_it_mw=round(cap, 2), pue=pue, interactive_mw=[round(float(x), 3) for x in inter],
                batch_mwh=round(flex*avg*24, 2), pf_q_ratio=0.25)

def hrs(*ranges):
    out = set()
    for a, b in ranges: out |= set(range(a, b))
    return out
