"""逐时边际碳因子（免费、可复核的方法）：省级“剩余负荷-优先顺序（merit-order）”估计。

方法（文档化假设，全部参数可在 REGIONS 中修改，均标注为【假设】，非官方数据）：
  1) 省级负荷形状 L(t)：基荷 + 日内双峰 + 温度驱动（制冷/采暖度时）——按站点 ERA5 逐时气温构造并归一到年峰值 1.0。
  2) 剩余负荷 RL(t) = L(t) − 风电渗透率×风电出力系数(t) − 光伏渗透率×光伏出力系数(t) − 必开机组（水电/核电，常数）。
     风/光出力系数用站点 ERA5 作为全省代理（单站代表全省是主要简化）。
  3) 边际机组按优先顺序：RL ≤ rl_curt → 新能源弃电为边际（MEF=mef_curt≈0）；
     rl_curt..1 区间为煤电（高效超超临界 → 低效亚临界，MEF 由 coal[0] 线性升至 coal[1]）；
     若省内燃气调峰占比 gas_top>0，则 RL 处于最高 gas_top 分位时燃气为边际（MEF=gas_ef）。
     机组排放因子取量级：超超临界 ~0.78、亚临界 ~0.95、燃气 ~0.40 tCO2/MWh（IPCC/行业常用量级）。
  4) 平均因子选项保留（avg，生态环境部 2023 年省级电力平均排放因子量级），可对比。
不确定性：这是“诊断性”估计，不是调度机构公布的边际排放；省际联络线、抽蓄、开机组合与检修均未建模。
"""
import numpy as np

REGIONS = {  # 【假设】渗透率 = 装机/省峰荷 的量级；avg 为平均因子（tCO2/MWh）
    "mengxi":    dict(cn="蒙西", avg=0.6849, wind_pen=0.55, pv_pen=0.25, must=0.05, rl_curt=0.30, coal=(0.78, 0.98), gas_top=0.0, gas_ef=0.40, mef_curt=0.0),
    "ningxia":   dict(cn="宁夏", avg=0.6423, wind_pen=0.45, pv_pen=0.55, must=0.05, rl_curt=0.30, coal=(0.78, 0.98), gas_top=0.0, gas_ef=0.40, mef_curt=0.0),
    "guangdong": dict(cn="广东", avg=0.4403, wind_pen=0.10, pv_pen=0.20, must=0.30, rl_curt=0.35, coal=(0.78, 0.92), gas_top=0.15, gas_ef=0.40, mef_curt=0.0),
    "denmark":   dict(cn="丹麦", avg=0.12, wind_pen=1.10, pv_pen=0.40, must=0.05, rl_curt=0.10, coal=(0.40, 0.75), gas_top=0.30, gas_ef=0.40, mef_curt=0.0),
    "national":  dict(cn="全国", avg=0.5306, wind_pen=0.25, pv_pen=0.30, must=0.20, rl_curt=0.30, coal=(0.78, 0.95), gas_top=0.05, gas_ef=0.40, mef_curt=0.0),
}

def load_shape(T, hours_of_day):
    T = np.asarray(T, float); h = np.asarray(hours_of_day)
    diurnal = 0.06*np.exp(-((h - 11)/3.0)**2) + 0.08*np.exp(-((h - 20)/2.5)**2) - 0.06*np.exp(-((h - 4)/3.0)**2)
    temp = 0.012*np.maximum(T - 22, 0) + 0.006*np.maximum(5 - T, 0)
    L = 0.80 + diurnal + temp
    return L/L.max()

def marginal(region, T, wind_cf, pv_cf):
    P = REGIONS.get(region, REGIONS["national"]); T = np.asarray(T, float)
    h = np.arange(T.size) % 24
    L = load_shape(T, h)
    RL = L - P["wind_pen"]*np.asarray(wind_cf) - P["pv_pen"]*np.asarray(pv_cf) - P["must"]
    lo, (c0, c1) = P["rl_curt"], P["coal"]
    top = np.quantile(RL, 1 - P["gas_top"]) if P["gas_top"] > 0 else np.inf
    hi = min(RL.max(), top)
    x = np.clip((RL - lo)/max(hi - lo, 1e-6), 0, 1)
    mef = np.where(RL <= lo, P["mef_curt"], c0 + (c1 - c0)*x)
    if P["gas_top"] > 0: mef = np.where(RL >= top, P["gas_ef"], mef)
    return dict(mef=mef, rl=RL, load=L, avg=P["avg"], region=region, cn=P["cn"],
                stats=dict(mef_mean=float(mef.mean()), share_curt=float((RL <= lo).mean()), avg=P["avg"],
                           mef_p10=float(np.quantile(mef, .1)), mef_p90=float(np.quantile(mef, .9))))

ASSUMPTIONS = __doc__
