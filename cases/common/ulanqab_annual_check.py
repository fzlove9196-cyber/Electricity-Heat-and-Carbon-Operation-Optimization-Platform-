"""乌兰察布 年风电复核：ERA5 100m 风速 × 不同功率曲线/轮毂高度/年份，对比公开 8.48 亿 kWh（风200MW+光100MW）。"""
import sys, os, json, numpy as np
sys.path.insert(0, os.path.dirname(__file__)); import climate as CM

def curve(v, vin=3.0, vr=11.5, vout=25.0, loss=0.92):
    cf = np.where(v < vin, 0, np.where(v < vr, (v**3 - vin**3)/(vr**3 - vin**3), np.where(v < vout, 1, 0)))
    return np.clip(cf*loss, 0, 1)

def run():
    out = []
    for yr in (2022, 2023, 2024):
        D = CM.days(CM.fetch("ulanqab", yr)); W = np.nan_to_num(D["W"].reshape(-1))/3.6; G = np.nan_to_num(D["G"].reshape(-1))
        pvh = float(CM.pv_cf(G).sum())
        for nm, kw in [("通用曲线 额定11.5m/s，100m", dict()), ("低比功率机组 额定9.5m/s，100m", dict(vr=9.5, vin=2.5)),
                       ("低比功率 9.5m/s + 风切变至140m(α=0.14)", dict(vr=9.5, vin=2.5, shear=(140/100)**0.14))]:
            sh = kw.pop("shear", 1.0); wh = float(curve(W*sh, **kw).sum())
            tot = (200*wh + 100*pvh)/1e5   # 亿kWh
            out.append(dict(year=yr, model=nm, mean_v=round(float(W.mean()*sh), 2), wind_h=round(wh), pv_h=round(pvh), total_yi_kwh=round(tot, 2), ratio=round(tot/8.48, 2)))
    return out

if __name__ == "__main__":
    R = run(); [print(r) for r in R]
    json.dump(R, open(os.path.join(os.path.dirname(__file__), "..", "validation", "out", "ulanqab_annual_check.json"), "w"), ensure_ascii=False, indent=1)
