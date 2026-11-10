"""内蒙古和林格尔数据中心集群绿色能源供给示范项目（中国华电，一期 36 万kW：风 30 + 光 6，储能 6.48万kW/25.92万kWh）。
"点对点"绿电直供 4 家数据中心（中国移动/中国电信/并行科技/中数云科，合计 23.38 万kW 负荷），41 km 专线，公网托底、防倒送；PPA 锁定基础电价。
已核实参数见 SRC；网络阻抗、出力曲线形状、电价/需量电价/PPA 价、各 DC 负荷拆分、北京节点等为【假设】。
用法: python cases/helinger/build_helinger.py"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..")); sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app.scenario import Scenario, generate_jobs
from common.profiles import pv, wind, tou, dc, hrs
OUT = os.path.dirname(os.path.abspath(__file__))
SRC = {
 "一期 风30万kW/光6万kW/储能6.48万kW·25.92万kWh(18%/4h)、直供4家DC合计23.38万kW、总算力1.5万P": "http://hlgena.huhhot.gov.cn/zxzx/xqdt/202408/t20240829_1769166.html",
 "年发电7.6亿kWh、全部由DC新增负荷消纳、点对点直供": "https://www.dtdata.cn/news/show/3311.html",
 "41 km 绿电专线、220kV/110kV 专属输电专线、二期20万+三期30万kW(2026底)、蒙西电网": "https://www.21jingji.com/article/20260909/herald/ecd3d08b1b2710cd92f0f0a294ca8cca.html",
 "PUE 1.15、PPA 多年期购电协议、储能放电补缺口并防止倒送公网、公网托底": "https://www.cpnn.com.cn/news/xny/202604/t20260416_1881375.html",
 "综合到户电价0.33~0.36元/kWh、绿电使用比例>85%、到北京单向时延3.5ms": "http://hlgena.huhhot.gov.cn/zxzx/xqdt/202609/t20260915_2036494.html",
 "内蒙古0.6849、北京0.5580 kgCO2/kWh（2022省级电力平均因子）": "https://www.mee.gov.cn/xxgk2018/xxgk/xxgk01/202412/t20241226_1099413.html",
 "假设": "等值网络阻抗/额定、风光典型日形状（按7.6亿kWh年发电校准：风≈2200h/光≈1500h）、蒙西分时电价(0.48/0.36/0.22)、需量电价28元/kW·月、"
        "PPA直供价0.26元/kWh、4家DC负荷拆分(80/70/45/38.4MW)、负载率0.8、灵活比例25%、北京DC(30MW IT/PUE1.3)与北京电价、链路带宽、碳价80元/t 均为假设",
}
PEAK, VALLEY = hrs((7, 11), (17, 22)), hrs((0, 6), (11, 15))   # 假设时段（蒙西午间光伏多→谷段假设在午间）
def build(day="typical", with_bj=True, green=None, n_jobs=0):
    cf = {"typical": 0.25, "highwind": 0.42, "lowwind": 0.12}[day]
    B = [("蒙西电网220kV(公网托底)", 220), ("华电风电场220kV升压站", 220), ("光伏场35kV母线", 35), ("集群220kV用户站", 220), ("集群110kV配电母线A", 110), ("集群110kV配电母线B", 110)]
    L = [dict(name="绿电直供专线220kV(41km)", from_bus=1, to_bus=3, length_km=41, r_ohm_per_km=0.054, x_ohm_per_km=0.39, c_nf_per_km=9.5, rating_mva=300, parallel=2),
         dict(name="公网联络线220kV", from_bus=0, to_bus=3, length_km=15, r_ohm_per_km=0.054, x_ohm_per_km=0.39, c_nf_per_km=9.5, rating_mva=300, parallel=1)]
    T = [dict(name="光伏35/220kV升压变", hv_bus=1, lv_bus=2, sn_mva=70, vk_percent=10.5),
         dict(name="用户站220/110kV#1", hv_bus=3, lv_bus=4, sn_mva=180, vk_percent=13),
         dict(name="用户站220/110kV#2", hv_bus=3, lv_bus=5, sn_mva=180, vk_percent=13)]
    E = [dict(bus=0, name="蒙西电网", vm_pu=1.02, price_cny_kwh=tou(0.48, 0.36, 0.22, PEAK, VALLEY), export_max_mw=0.0,
              demand_charge_cny_mw_day=28000/30)]
    pue = 1.15
    dcs = [dc("移动_HLGE", 4, 80, pue), dc("电信_HLGE", 4, 70, pue), dc("并行科技_HLGE", 5, 45, pue, flex=0.35), dc("中数云科_HLGE", 5, 38.4, pue)]
    sc = dict(name=f"helinger_{day}{'' if with_bj else '_noBJ'}{f'_green{int(round(green*100))}' if green else ''}", synthetic=False,
              note="和林格尔数据中心集群绿色能源供给示范项目（一期36万kW 风光储，点对点直供）。规模/负荷/PUE 来自公开报道；网络/曲线/价格等为假设，见 sources。",
              network_case="custom", network=dict(buses=[dict(name=n, vn_kv=v) for n, v in B], lines=L, trafos=T, ext_grids=E,
                                                   note="等值网络：参数为假设值（非接入系统报告）"),
              sources=SRC, price_kind="mengxi_tou_assumed", price_cny_kwh=tou(0.48, 0.36, 0.22, PEAK, VALLEY), grid_markup_cny_mwh=0.0,
              data_centers=dcs,
              pv=[dict(bus=1, cap_mw=300, kind="wind", name="华电风电30万kW", profile=wind(cf), ppa_price_cny_kwh=0.26),
                  dict(bus=2, cap_mw=60, kind="pv", name="华电光伏6万kW", profile=pv(1500), ppa_price_cny_kwh=0.26)],
              storage=[dict(name="ESS_HD", bus=1, energy_mwh=259.2, power_mw=64.8, soc0=0.5)],
              mig_max_mw=20, mig_day_share=0.4, pv_curtail_penalty=30.0, min_green_share=green,
              carbon_factor=0.6849, carbon_shape="flat", carbon_profiles={"mengxi": [0.6849]*24, **({"beijing": [0.5580]*24} if with_bj else {})},
              bus_region={**{i: "mengxi" for i in range(6)}, **({6: "beijing"} if with_bj else {})},
              carbon_source="MEE 2022 省级电力平均因子（flat）", carbon_price_cny_t=80.0, carbon_accounting="generation", mig_energy_mwh_per_mwh=0.02)
    if with_bj:
        sc["network"]["buses"].append(dict(name="北京DC 110kV(华北)", vn_kv=110))
        sc["network"]["ext_grids"].append(dict(bus=6, name="华北电网(北京)", price_cny_kwh=tou(1.05, 0.68, 0.32, hrs((10, 15), (18, 21)), hrs((23, 24), (0, 7)))))
        sc["data_centers"].append(dc("BJ_研发", 6, 39, 1.3, peak_h=15))
        sc["links"] = [dict(a="移动_HLGE", b="电信_HLGE", latency_ms=1, bw_mw=20), dict(a="移动_HLGE", b="并行科技_HLGE", latency_ms=1, bw_mw=15),
                       dict(a="电信_HLGE", b="中数云科_HLGE", latency_ms=1, bw_mw=15), dict(a="并行科技_HLGE", b="BJ_研发", latency_ms=3.5, bw_mw=10),
                       dict(a="移动_HLGE", b="BJ_研发", latency_ms=3.5, bw_mw=10)]
    s = Scenario.model_validate(sc)
    if n_jobs: s.jobs = generate_jobs(s, n_jobs, 7); s.name += f"_jobs{n_jobs}"
    return s

if __name__ == "__main__":
    out = [build("typical"), build("highwind"), build("lowwind"), build("typical", with_bj=False), build("typical", green=0.85), build("highwind", with_bj=False, green=0.6), build("typical", n_jobs=40)]
    out[0].name = "helinger_typical_day"
    for s in out: open(os.path.join(OUT, f"{s.name}.json"), "w").write(s.model_dump_json(indent=1))
    print([s.name for s in out])
