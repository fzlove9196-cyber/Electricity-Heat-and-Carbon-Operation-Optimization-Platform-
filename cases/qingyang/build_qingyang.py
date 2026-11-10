"""甘肃庆阳“东数西算”产业园区绿电聚合试点项目（甘肃电投，一期 100 万kW：风 75 + 光 25，按 10%/2h 配储，2 座 330kV 升压站，就近接入公网）。
“绿电聚合”：新能源与园区负荷经公网（同一 330kV 供区）发用匹配，约 55% 园区用电由聚合绿电满足，余量市场购入，余电上网；到户 ≤0.4 元/kWh。
多电压等级：750/330/110/35 kV。已核实参数见 SRC；其余为【假设】。"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..")); sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app.scenario import Scenario, generate_jobs
from common.profiles import pv, wind, tou, dc, hrs
OUT = os.path.dirname(os.path.abspath(__file__))
SRC = {
 "总规划200万kW(风150/光50)、按10%/2h配储(200MW/400MWh)": "https://www.nengyuanjie.net/article/102877.html ; https://www.escn.com.cn/news/show-1724351.html",
 "一期100万kW(风75/光25)、2座330kV升压站、风电2042.2h/光伏1456h、就近接入公网、55%发用匹配、到户<0.4元/kWh、已建机架3.1万架": "http://gs.news.cn/20250827/640db481973d432cb25de2cef9be4aae/c.html",
 "一期年发电19.96亿kWh、首批机组2026-01-30并网": "https://www.news.cn/20260130/c30d20909b2c4ef0ac9bf0da16d58fa3/c.html",
 "绿电直供+余电上网 聚合供应模式、园区绿电占比≥80%": "http://www.sasac.gov.cn/n2588025/n2588129/c35451088/content.html",
 "甘肃0.4772 kgCO2/kWh（2022省级）": "https://www.mee.gov.cn/xxgk2018/xxgk/xxgk01/202412/t20241226_1099413.html",
 "假设": "一期储能按10%/2h=100MW/200MWh；园区平均负荷≈19.96亿kWh/55%/8760≈414MW（推算），拆分3个等值DC；PUE1.25；"
        "甘肃分时电价(0.55/0.37/0.19，谷段午间)、上网电价0.2595元/kWh(燃煤基准价口径假设)、网络阻抗/额定、出力形状均为假设",
}
PEAK, VALLEY = hrs((6, 8), (18, 23)), hrs((9, 17))
def build(day="typical", n_jobs=0, green=None):
    cf, season = {"typical": (0.233, "summer"), "highwind": (0.38, "summer"), "winter_lowwind": (0.12, "winter")}[day]
    B = [("甘肃主网750kV(庆阳)", 750), ("庆阳330kV汇集站", 330), ("环县风电330kV升压站", 330), ("光伏330kV升压站", 330),
         ("风电场35kV集电", 35), ("园区330kV变电站", 330), ("园区110kV母线A", 110), ("园区110kV母线B", 110)]
    L = [dict(name="风电升压站-汇集站330kV", from_bus=2, to_bus=1, length_km=60, r_ohm_per_km=0.04, x_ohm_per_km=0.31, c_nf_per_km=11.5, rating_mva=900),
         dict(name="光伏升压站-汇集站330kV", from_bus=3, to_bus=1, length_km=35, r_ohm_per_km=0.04, x_ohm_per_km=0.31, c_nf_per_km=11.5, rating_mva=600),
         dict(name="汇集站-园区站330kV(双回)", from_bus=1, to_bus=5, length_km=45, r_ohm_per_km=0.04, x_ohm_per_km=0.31, c_nf_per_km=11.5, rating_mva=600, parallel=2)]
    T = [dict(name="庆阳750/330kV", hv_bus=0, lv_bus=1, sn_mva=1500, parallel=2), dict(name="风电35/330kV主变", hv_bus=2, lv_bus=4, sn_mva=400, parallel=2, vk_percent=12),
         dict(name="园区330/110kV#1(2台)", hv_bus=5, lv_bus=6, sn_mva=360, vk_percent=12, parallel=2), dict(name="园区330/110kV#2", hv_bus=5, lv_bus=7, sn_mva=360, vk_percent=12)]
    price = tou(0.55, 0.37, 0.19, PEAK, VALLEY)
    E = [dict(bus=0, name="甘肃电网(市场购电/余电上网)", vm_pu=1.02, price_cny_kwh=price, export_max_mw=1000, export_price_cny_kwh=[0.2595]*24)]
    dcs = [dc("QY_DC_A", 6, 200, 1.25, util=0.8), dc("QY_DC_B", 6, 170, 1.25, util=0.8), dc("QY_DC_C", 7, 150, 1.25, util=0.8, flex=0.35)]
    sc = dict(name=f"qingyang_{day}{'_jobs%d' % n_jobs if n_jobs else ''}{'_green55' if green else ''}", synthetic=False,
              note="庆阳“东数西算”园区绿电聚合试点（一期100万kW风光+储能，经公网聚合匹配）。规模/利用小时/匹配比例来自公开报道；网络/负荷拆分/价格为假设。",
              network_case="custom", network=dict(buses=[dict(name=n, vn_kv=v) for n, v in B], lines=L, trafos=T, ext_grids=E, note="等值网络（假设）"),
              sources=SRC, price_kind="gansu_tou_assumed", price_cny_kwh=price, grid_markup_cny_mwh=0.0, data_centers=dcs,
              pv=[dict(bus=4, cap_mw=750, kind="wind", name="环县风电75万kW", profile=wind(cf), ppa_price_cny_kwh=0.28),
                  dict(bus=3, cap_mw=250, kind="pv", name="光伏25万kW", profile=pv(1456, season), ppa_price_cny_kwh=0.28)],
              storage=[dict(name="ESS_QY", bus=1, energy_mwh=200, power_mw=100, soc0=0.5)],
              mig_max_mw=30, mig_day_share=0.4, pv_curtail_penalty=30.0, min_green_share=green,
              carbon_factor=0.4772, carbon_shape="flat", carbon_profiles={"gansu": [0.4772]*24}, bus_region={i: "gansu" for i in range(8)},
              carbon_source="MEE 2022 省级（flat）", carbon_price_cny_t=80.0, carbon_accounting="generation", mig_energy_mwh_per_mwh=0.01,
              links=[dict(a="QY_DC_A", b="QY_DC_B", latency_ms=1, bw_mw=25), dict(a="QY_DC_B", b="QY_DC_C", latency_ms=1, bw_mw=25), dict(a="QY_DC_A", b="QY_DC_C", latency_ms=1, bw_mw=20)])
    s = Scenario.model_validate(sc)
    if n_jobs: s.jobs = generate_jobs(s, n_jobs, 11)
    return s
if __name__ == "__main__":
    out = [build("typical"), build("highwind"), build("winter_lowwind"), build("typical", n_jobs=40), build("typical", green=0.55), build("highwind", green=0.55)]
    for s in out: open(os.path.join(OUT, f"{s.name}.json"), "w").write(s.model_dump_json(indent=1))
    print([s.name for s in out])
