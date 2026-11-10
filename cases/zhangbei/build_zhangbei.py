"""河北张北：阿里巴巴张北数据中心基地 + 明阳察北“源网荷储一体化”（20 万kW 风电 + 4 万kW/16 万kWh 储能，新建 220kV 线路接入银沙 220kV 站，
与庙滩北/察哈尔 DC 同一变电台区）；全生命周期绿电 PPA；跨区算力调度（南通→张北，2022 华北调峰辅助服务试运行）及与内蒙古（乌兰察布）绿电交易。
三区域迁移：河北张北 / 江苏南通 / 内蒙古乌兰察布。已核实参数见 SRC；其余为【假设】。"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..")); sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app.scenario import Scenario, generate_jobs
from common.profiles import pv, wind, tou, dc, hrs
OUT = os.path.dirname(os.path.abspath(__file__))
SRC = {
 "5大园区/规划60万台服务器、200MW风电+40MW/160MWh储能(20%/4h)、新建220kV线路接入银沙220kV站与庙滩北/察哈尔同台区、就地消纳5亿kWh/年、绿电PPA、跨省绿电交易、11.1MW园区风光储": "https://www.10100.com/article/38853150",
 "张北PUE 冬季最低1.09/夏季约1.3、全年<1.2": "https://news.sciencenet.cn/htmlnews/2021/7/462109.shtm",
 "南通→张北 算力-电力跨区域优化调度（华北调峰辅助服务试运行, 2022-05）": "https://developer.aliyun.com/article/979711",
 "阿里云自建DC PUE 1.200（FY2024）、租赁DC PUE 1.269": "https://tech.cnr.cn/techph/20240722/t20240722_526807992.shtml",
 "河北0.7252、江苏0.5978、内蒙古0.6849 kgCO2/kWh（2022省级）": "https://www.mee.gov.cn/xxgk2018/xxgk/xxgk01/202412/t20241226_1099413.html",
 "假设": "风电利用小时≈2500h（按5亿kWh/年 /200MW 校准）、DC负荷(庙滩北70MW/察哈尔60MW/南通40MW/乌兰察布50MW峰值)、冀北/江苏/蒙西分时电价与需量电价(32元/kW·月)、"
        "PPA价0.30元/kWh、链路时延带宽、网络阻抗均为假设",
}
def build(season="summer", n_jobs=0):
    cf = 0.24 if season == "summer" else 0.33; pue_zb = 1.3 if season == "summer" else 1.12
    B = [("冀北主网220kV(张家口)", 220), ("银沙220kV变电站", 220), ("明阳察北风电220kV升压站", 220), ("风电35kV集电", 35),
         ("庙滩北DC 110kV", 110), ("察哈尔DC 110kV", 110), ("南通DC 110kV(江苏)", 110), ("乌兰察布DC 110kV(蒙西)", 110)]
    L = [dict(name="风电-银沙220kV(新建)", from_bus=2, to_bus=1, length_km=25, r_ohm_per_km=0.054, x_ohm_per_km=0.39, c_nf_per_km=9.5, rating_mva=300),
         dict(name="银沙-冀北主网220kV", from_bus=1, to_bus=0, length_km=40, r_ohm_per_km=0.054, x_ohm_per_km=0.39, c_nf_per_km=9.5, rating_mva=300, parallel=2)]
    T = [dict(name="风电35/220kV主变", hv_bus=2, lv_bus=3, sn_mva=240, vk_percent=12), dict(name="银沙220/110kV#1(庙滩北)", hv_bus=1, lv_bus=4, sn_mva=120, vk_percent=13),
         dict(name="银沙220/110kV#2(察哈尔)", hv_bus=1, lv_bus=5, sn_mva=120, vk_percent=13)]
    jb = tou(0.75, 0.50, 0.28, hrs((7, 11), (17, 23)), hrs((0, 7), (11, 13)))
    E = [dict(bus=0, name="冀北电网", vm_pu=1.02, price_cny_kwh=jb, export_max_mw=150, export_price_cny_kwh=[0.372]*24, demand_charge_cny_mw_day=32000/30),
         dict(bus=6, name="江苏电网(南通)", price_cny_kwh=tou(1.02, 0.62, 0.30, hrs((8, 11), (17, 22)), hrs((0, 8))), demand_charge_cny_mw_day=40000/30),
         dict(bus=7, name="蒙西电网(乌兰察布)", price_cny_kwh=tou(0.48, 0.36, 0.22, hrs((7, 11), (17, 22)), hrs((0, 6), (11, 15))))]
    dcs = [dc("阿里_庙滩北", 4, 70, pue_zb), dc("阿里_察哈尔", 5, 60, pue_zb), dc("阿里_南通", 6, 40, 1.27, peak_h=15), dc("阿里_乌兰察布", 7, 50, 1.2)]
    sc = dict(name=f"zhangbei_{season}{'_jobs%d' % n_jobs if n_jobs else ''}", synthetic=False,
              note="阿里张北基地 + 明阳察北源网荷储一体化（200MW 风电 + 40MW/160MWh 储能，同台区就地消纳）+ 三区域算力迁移。规模来自公开报道，其余假设。",
              network_case="custom", network=dict(buses=[dict(name=n, vn_kv=v) for n, v in B], lines=L, trafos=T, ext_grids=E, note="等值网络（假设）；南通/乌兰察布为独立电气岛"),
              sources=SRC, price_kind="jibei_tou_assumed", price_cny_kwh=jb, grid_markup_cny_mwh=0.0, data_centers=dcs,
              pv=[dict(bus=3, cap_mw=200, kind="wind", name="明阳察北风电200MW", profile=wind(cf), ppa_price_cny_kwh=0.30),
                  dict(bus=4, cap_mw=10, kind="pv", name="园区屋顶光伏10MW", profile=pv(1450, season))],
              storage=[dict(name="ESS_察北", bus=2, energy_mwh=160, power_mw=40, soc0=0.5)],
              mig_max_mw=25, mig_day_share=0.4, pv_curtail_penalty=30.0, carbon_factor=0.7252, carbon_shape="flat",
              carbon_profiles={"hebei": [0.7252]*24, "jiangsu": [0.5978]*24, "mengxi": [0.6849]*24},
              bus_region={**{i: "hebei" for i in range(6)}, 6: "jiangsu", 7: "mengxi"}, carbon_source="MEE 2022 省级（flat）",
              carbon_price_cny_t=80.0, carbon_accounting="location", carbon_weight=1.0, mig_energy_mwh_per_mwh=0.02,
              links=[dict(a="阿里_庙滩北", b="阿里_察哈尔", latency_ms=1, bw_mw=30), dict(a="阿里_南通", b="阿里_庙滩北", latency_ms=25, bw_mw=15),
                     dict(a="阿里_察哈尔", b="阿里_乌兰察布", latency_ms=6, bw_mw=15), dict(a="阿里_南通", b="阿里_乌兰察布", latency_ms=30, bw_mw=10)])
    s = Scenario.model_validate(sc)
    if n_jobs: s.jobs = generate_jobs(s, n_jobs, 5)
    return s
if __name__ == "__main__":
    out = [build("summer"), build("winter"), build("summer", n_jobs=40)]
    for s in out: open(os.path.join(OUT, f"{s.name}.json"), "w").write(s.model_dump_json(indent=1))
    print([s.name for s in out])
