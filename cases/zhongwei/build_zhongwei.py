"""生成 大唐中卫云基地数据中心绿电供应项目 场景 JSON（典型日 × 是否含上海迁移节点）。
已核实参数见 SOURCES；网络参数、出力曲线形状、上海 DC 规模等为【假设】并在 JSON 的 sources 字段标注。
用法: python cases/zhongwei/build_zhongwei.py   -> cases/zhongwei/*.json"""
import json, os, sys
import numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from app.scenario import Scenario, generate_jobs

OUT = os.path.dirname(os.path.abspath(__file__)); h = np.arange(24)
SRC = {
 "项目规模/年用电22.9亿kWh": "https://www.nea.gov.cn/20260508/b975a9364d18444c808318430bf660cf/c.html ; https://xbj.nea.gov.cn/dtyw/hyxx/202605/t20260506_300641.html",
 "存量10.5万kW/7.4亿kWh、增量19.2万kW/15.5亿kWh、4回110kV+2座开关站、π接沙坡头750/塞上330、风电3座330kV升压站接天都山750": "http://www.china.com.cn/txt/2026-03/02/content_118355455.shtml",
 "年供清洁电力约41.4亿kWh（用于风光年利用小时校准）": "http://www.china.com.cn/txt/2026-03/02/content_118355455.shtml",
 "宁夏峰平谷时段(峰7-9,17-23;谷9-17;平0-7,23-24)": "https://fzggw.nx.gov.cn/tzgg/202412/t20241220_4765880.html",
 "宁夏110kV两部制分时电度电价(2025-06: 0.5503/0.3755/0.2010) 与交易价(0.4551/0.2803/0.1058)": "https://energydc.cn/policy/ningxia/2025-06/e1bd96c6-d441-11f0-936e-46a1f660a16d",
 "西北区域电力平均排放因子0.5857、上海0.5849 kgCO2/kWh(2022)": "https://www.mee.gov.cn/xxgk2018/xxgk/xxgk01/202412/t20241226_1099413.html",
 "上海两部制110kV一般工商业(2025-07: 尖1.2957/峰1.0521/平0.6191/谷0.2943)及时段": "https://energydc.cn/policy/shanghai/2025-07/ee772264-d325-11f0-baa7-46a1f660a16d",
 "DC灵活性25%/3h/15min爬坡": "https://arxiv.org/abs/2507.00909",
 "PUE≈1.2（中卫园区设计PUE<1.2 示例）": "http://www.china.com.cn/txt/2026-03/02/content_118355455.shtml",
 "假设": "等值网络线路长度/阻抗/额定、风光典型日形状、储能75MW/150MWh(PV的15%×2h)、上海DC 60MW IT/PUE1.3、链路时延带宽、外送上限1200MW、碳价80元/t、弃电惩罚50元/MWh 均为假设",
}

def tou_nx(kind="buy"):
    pk, fl, vl = (0.5503, 0.3755, 0.2010) if kind == "buy" else (0.4551, 0.2803, 0.1058)
    return [pk if (7 <= t < 9 or 17 <= t < 23) else vl if 9 <= t < 17 else fl for t in h]

def tou_sh(season):
    out = []
    for t in h:
        if t >= 22 or t < 6: p = 0.2943
        elif season == "summer" and (8 <= t < 15 or 18 <= t < 21): p = 1.2957 if 12 <= t < 14 else 1.0521
        elif season == "winter" and (8 <= t < 11 or 18 <= t < 21): p = 1.2957 if 19 <= t < 21 else 1.0521
        else: p = 0.6191
        out.append(p)
    return out

def pv_raw(season):
    a, b = (6.5, 20.5) if season == "summer" else (8.5, 18.5)   # 北京时间日出/日落（中卫≈105°E，太阳正午≈13:00）
    x = np.clip(np.sin((h + 0.5 - a)/(b - a)*np.pi), 0, None)
    x[(h + 0.5 < a) | (h + 0.5 > b)] = 0
    return x*(1.0 if season == "summer" else 0.85)

def wind_raw():
    return 1 + 0.35*np.cos(2*np.pi*(h - 2)/24)   # 夜间偏大（假设形状）

# 校准：4 典型日等权，PV 年利用 = 41.4亿kWh 拆分（PV≈1550h, 风≈(4140-775)/1500≈2243h）
PV_H, WIND_H = 1550.0, (4140 - 500*1.55)/1.5
pv_mean = np.mean([pv_raw("summer").mean(), pv_raw("winter").mean()])
PV_K = PV_H/8760/pv_mean
CF_HI, CF_LO = 0.42, 2*WIND_H/8760 - 0.42
DAYS = {"summer_highwind": ("summer", CF_HI), "summer_lowwind": ("summer", CF_LO),
        "winter_highwind": ("winter", CF_HI), "winter_lowwind": ("winter", CF_LO)}

def network(with_sh):
    B = [("沙坡头750kV", 750), ("天都山750kV", 750), ("塞上330kV", 330), ("大唐光伏升压站330kV", 330), ("光伏直供110kV母线", 110),
         ("110kV开关站A", 110), ("110kV开关站B", 110), ("风电330kV升压站(3座等值)", 330), ("存量DC 110kV", 110), ("沙坡头330kV侧", 330)]
    if with_sh: B.append(("上海DC 110kV(华东)", 110))
    L = [dict(name="沙坡头-天都山750", from_bus=0, to_bus=1, length_km=120, r_ohm_per_km=0.012, x_ohm_per_km=0.27, c_nf_per_km=13.5, rating_mva=2500),
         dict(name="光伏站-沙坡头330(π接)", from_bus=3, to_bus=9, length_km=30, r_ohm_per_km=0.04, x_ohm_per_km=0.31, c_nf_per_km=11.5, rating_mva=900),
         dict(name="光伏站-塞上330(π接)", from_bus=3, to_bus=2, length_km=25, r_ohm_per_km=0.04, x_ohm_per_km=0.31, c_nf_per_km=11.5, rating_mva=900),
         dict(name="直供110kV-开关站A(2回)", from_bus=4, to_bus=5, length_km=6, r_ohm_per_km=0.08, x_ohm_per_km=0.40, c_nf_per_km=9, rating_mva=130, parallel=2),
         dict(name="直供110kV-开关站B(2回)", from_bus=4, to_bus=6, length_km=6, r_ohm_per_km=0.08, x_ohm_per_km=0.40, c_nf_per_km=9, rating_mva=130, parallel=2)]
    T = [dict(name="沙坡头750/330", hv_bus=0, lv_bus=9, sn_mva=1500, parallel=2),
         dict(name="天都山750/330(风电)", hv_bus=1, lv_bus=7, sn_mva=750, parallel=3),
         dict(name="光伏站330/110", hv_bus=3, lv_bus=4, sn_mva=360, parallel=2, vk_percent=12),
         dict(name="塞上330/110(存量DC)", hv_bus=2, lv_bus=8, sn_mva=180, parallel=2, vk_percent=12)]
    E = [dict(bus=0, name="西北电网(宁夏)", vm_pu=1.02, price_cny_kwh=tou_nx("buy"), export_max_mw=1200, export_price_cny_kwh=tou_nx("sell"))]
    return B, L, T, E

def dc(name, bus, cap_it, avg_it, pue, peak_h=21, flex=0.25):
    inter = (1 - flex)*avg_it*(1 + 0.06*np.cos(2*np.pi*(h - peak_h)/24))
    return dict(name=name, bus=bus, cap_it_mw=round(cap_it, 2), pue=pue, interactive_mw=[round(float(x), 3) for x in inter],
                batch_mwh=round(flex*avg_it*24, 2), pf_q_ratio=0.25)

def build(day, with_sh=True, n_jobs=0, storage=True):
    season, cf = DAYS[day]
    B, L, T, E = network(with_sh)
    pue = 1.2
    dcs = [dc("ZW_EXIST", 8, 105/pue, 740e3/8760/pue, pue),           # 存量：105MW峰、7.4亿kWh/年
           dc("ZW_NEW_A", 5, 96/pue, 1550e3/8760/2/pue, pue),          # 增量：192MW峰、15.5亿kWh/年，均分两开关站
           dc("ZW_NEW_B", 6, 96/pue, 1550e3/8760/2/pue, pue)]
    if with_sh: dcs.append(dc("SH_EAST", 10, 60, 48, 1.3, peak_h=15))
    pv = (pv_raw(season)*PV_K).clip(0, 1); w = wind_raw(); w = (w/w.mean()*cf).clip(0, 1)
    sc = dict(name=f"zhongwei_{day}{'' if with_sh else '_noSH'}", synthetic=False,
              note="大唐中卫云基地数据中心绿电供应项目（一期200万kW）。规模/负荷来自公开报道；网络/曲线/储能等为假设，见 sources。",
              network_case="custom", network=dict(buses=[dict(name=n, vn_kv=v) for n, v in B], lines=L, trafos=T, ext_grids=E,
                                                   note="等值网络：参数为假设值（非接入系统报告）"),
              sources=SRC, price_kind="ningxia_tou_110kV", price_cny_kwh=tou_nx("buy"), grid_markup_cny_mwh=0.0,
              data_centers=dcs, pv=[dict(bus=4, cap_mw=500, profile=[round(float(x), 4) for x in pv]),
                                    dict(bus=7, cap_mw=1500, profile=[round(float(x), 4) for x in w])],
              storage=[dict(name="ESS_ZW", bus=4, energy_mwh=150, power_mw=75, soc0=0.5)] if storage else [],
              mig_max_mw=30, mig_day_share=0.4, pv_curtail_penalty=50.0,
              carbon_factor=0.5857, carbon_shape="flat",
              carbon_profiles={"northwest": [0.5857]*24, **({"shanghai": [0.5849]*24} if with_sh else {})},
              bus_region={**{i: "northwest" for i in range(10)}, **({10: "shanghai"} if with_sh else {})},
              carbon_source="MEE 2022 区域/省级电力平均因子（flat，无逐时数据）", carbon_price_cny_t=80.0,
              carbon_accounting="generation", mig_energy_mwh_per_mwh=0.02)
    if with_sh:
        sc["network"]["ext_grids"].append(dict(bus=10, name="华东电网(上海)", vm_pu=1.0, price_cny_kwh=tou_sh(season)))
        sc["links"] = [dict(a="ZW_NEW_A", b="ZW_NEW_B", latency_ms=1, bw_mw=30), dict(a="ZW_EXIST", b="ZW_NEW_A", latency_ms=2, bw_mw=20),
                       dict(a="ZW_EXIST", b="ZW_NEW_B", latency_ms=2, bw_mw=20), dict(a="ZW_NEW_A", b="SH_EAST", latency_ms=30, bw_mw=15),
                       dict(a="ZW_NEW_B", b="SH_EAST", latency_ms=30, bw_mw=15), dict(a="ZW_EXIST", b="SH_EAST", latency_ms=30, bw_mw=10)]
    s = Scenario.model_validate(sc)
    if n_jobs: s.jobs = generate_jobs(s, n_jobs, 42)
    return s

if __name__ == "__main__":
    for d in DAYS:
        for sh in (True, False):
            s = build(d, sh); fn = os.path.join(OUT, f"{s.name}.json")
            open(fn, "w").write(s.model_dump_json(indent=1))
    s = build("summer_highwind", True, n_jobs=40); s.name = "zhongwei_summer_highwind_jobs40"
    open(os.path.join(OUT, f"{s.name}.json"), "w").write(s.model_dump_json(indent=1))
    print("PV_K", PV_K, "CF_LO", CF_LO, "WIND_H", WIND_H); print(sorted(os.listdir(OUT)))
