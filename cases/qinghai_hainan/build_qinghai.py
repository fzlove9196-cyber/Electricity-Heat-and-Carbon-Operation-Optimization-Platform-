"""青海海南州：龙羊峡“水光互补”（水电 128 万kW + 光伏 85 万kW，330kV 48km 接入水电站开关站）+ 海南州大数据产业园（全国首个 100% 清洁能源运营数据中心）。
变体：grid=并网典型日；clean100=物理口径 100% 清洁（禁止外网购电进入 DC 统计）；offgrid=离网直供微网（风光储+小水电，无外网）。
已核实参数见 SRC；水电日电量、DC 规模拆分、电价、网络阻抗等为【假设】。"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..")); sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app.scenario import Scenario
from common.profiles import pv, wind, tou, dc, hrs
OUT = os.path.dirname(os.path.abspath(__file__))
SRC = {
 "龙羊峡水电4×32万kW=128万kW、多年调节水库；光伏85万kW 经330kV线路(约36~48km)接入水电站、年发电约14.94亿kWh、送出线路利用小时4621→5019h": "http://www.qhnews.com/newscenter/system/2021/06/21/013405876.shtml ; https://www.china5e.com/energy/news-913758-1.html",
 "海南州大数据产业园：全国首个100%清洁能源运营DC、规划10万机架/年耗电57亿kWh、实测PUE<1.4（华为一期）": "https://e.huawei.com/cn/news/ebg/2020/the-first-clean-energy-operation-data-center-in-china-launched-in-qinghai ; https://digitalpower.huawei.com/cn/cases/data-center-facility/hainan-prefecturep-clean-energy-data-center",
 "在用在建8个DC、机架31149架、PUE<1.2、年清洁能源发电400亿kWh": "http://qh.news.cn/2023-05/23/c_1129638386.htm",
 "园区已建DC PUE稳定在1.2以下、7个大型DC在用在建、中电万界智算1606架/2500P": "https://www.hainanzhou.gov.cn/xwzx/hnyw/content_1013652677",
 "青海0.1567 kgCO2/kWh（2022省级）": "https://www.mee.gov.cn/xxgk2018/xxgk/xxgk01/202412/t20241226_1099413.html",
 "假设": "水电日可用电量（按送出通道5019h扣除光伏≈3900h×128万kW/365≈13.7GWh/日，枯水日取60%）、水电最小出力20%（生态流量）、水电成本50元/MWh；"
        "DC 负荷：31149架×6kW×50%≈93MW IT，拆分华为海南州DC(30MW峰)+园区等值DC(85MW峰)；PUE1.2；青海分时电价(0.42/0.30/0.18)、上网0.2277元/kWh；离网微网规模均为假设",
}
PEAK, VALLEY = hrs((7, 9), (18, 23)), hrs((9, 17))
def build(variant="grid", season="summer"):
    pv_prof = pv(1758, season)   # 14.94亿kWh / 85万kW ≈ 1758h
    if variant == "offgrid":
        B = [("园区直供微网35kV母线", 35), ("微网光伏35kV", 35), ("小水电35kV", 35), ("DC 10kV配电(等值)", 35)]
        L = [dict(name="光伏-微网35kV", from_bus=1, to_bus=0, length_km=8, r_ohm_per_km=0.12, x_ohm_per_km=0.38, c_nf_per_km=10, rating_mva=120),
             dict(name="小水电-微网35kV", from_bus=2, to_bus=0, length_km=12, r_ohm_per_km=0.12, x_ohm_per_km=0.38, c_nf_per_km=10, rating_mva=60),
             dict(name="微网-DC 35kV(双回)", from_bus=0, to_bus=3, length_km=3, r_ohm_per_km=0.12, x_ohm_per_km=0.38, c_nf_per_km=10, rating_mva=60, parallel=2)]
        net = dict(buses=[dict(name=n, vn_kv=v) for n, v in B], lines=L, trafos=[], ext_grids=[],
                   gens=[dict(name="小水电(等值)", bus=2, kind="hydro", pmax_mw=30, pmin_mw=4, cost_cny_mwh=50, emission_t_mwh=0, energy_mwh_day=420 if season == "summer" else 260, vm_pu=1.0)],
                   note="离网直供微网（假设规模）：无外网，风光储+小水电")
        sc = dict(name=f"qinghai_hainan_offgrid_{season}", network=net, data_centers=[dc("HNZ_微网DC", 3, 45, 1.2, util=0.75, flex=0.3)],
                  pv=[dict(bus=1, cap_mw=120, kind="pv", name="微网光伏120MW", profile=pv_prof), dict(bus=1, cap_mw=30, kind="wind", name="微网风电30MW", profile=wind(0.25))],
                  storage=[dict(name="ESS_MG", bus=0, energy_mwh=160, power_mw=40, soc0=0.5)], bus_region={i: "qinghai" for i in range(4)})
    else:
        B = [("青海主网330kV(海南州)", 330), ("龙羊峡水电站330kV开关站", 330), ("塔拉滩光伏330kV升压站", 330), ("共和330kV变电站", 330), ("大数据产业园110kV", 110), ("华为DC 110kV", 110)]
        L = [dict(name="光伏-龙羊峡330kV(48km)", from_bus=2, to_bus=1, length_km=48, r_ohm_per_km=0.04, x_ohm_per_km=0.31, c_nf_per_km=11.5, rating_mva=1000),
             dict(name="龙羊峡-主网330kV送出(多回等值)", from_bus=1, to_bus=0, length_km=60, r_ohm_per_km=0.04, x_ohm_per_km=0.31, c_nf_per_km=11.5, rating_mva=900, parallel=3),
             dict(name="主网-共和330kV", from_bus=0, to_bus=3, length_km=30, r_ohm_per_km=0.04, x_ohm_per_km=0.31, c_nf_per_km=11.5, rating_mva=600)]
        T = [dict(name="共和330/110kV#1", hv_bus=3, lv_bus=4, sn_mva=240, vk_percent=12), dict(name="共和330/110kV#2", hv_bus=3, lv_bus=5, sn_mva=120, vk_percent=12)]
        net = dict(buses=[dict(name=n, vn_kv=v) for n, v in B], lines=L, trafos=T,
                   ext_grids=[dict(bus=0, name="青海电网(含青豫直流外送)", vm_pu=1.02, price_cny_kwh=tou(0.42, 0.30, 0.18, PEAK, VALLEY), export_max_mw=2200, export_price_cny_kwh=[0.2277]*24)],
                   gens=[dict(name="龙羊峡水电128万kW", bus=1, kind="hydro", pmax_mw=1280, pmin_mw=256, cost_cny_mwh=50, emission_t_mwh=0,
                              energy_mwh_day=13700 if season == "summer" else 8200, vm_pu=1.02)], note="等值网络（假设）")
        sc = dict(name=f"qinghai_hainan_{variant}_{season}", network=net,
                  data_centers=[dc("华为海南州DC", 5, 30, 1.2, util=0.8), dc("海南州园区DC(等值)", 4, 85, 1.2, util=0.75, flex=0.3)],
                  pv=[dict(bus=2, cap_mw=850, kind="pv", name="龙羊峡水光互补光伏85万kW", profile=pv_prof, ppa_price_cny_kwh=0.2277)],
                  storage=[dict(name="ESS_HNZ(共享储能,假设)", bus=4, energy_mwh=200, power_mw=50, soc0=0.5)],
                  bus_region={i: "qinghai" for i in range(6)}, links=[dict(a="华为海南州DC", b="海南州园区DC(等值)", latency_ms=1, bw_mw=15)],
                  min_green_share=1.0 if variant == "clean100" else None)
    sc.update(synthetic=False, network_case="custom", sources=SRC, price_kind="qinghai_tou_assumed", price_cny_kwh=tou(0.42, 0.30, 0.18, PEAK, VALLEY), grid_markup_cny_mwh=0.0,
              note="青海海南州 水光互补 + 100%清洁能源数据中心。规模来自公开报道；水电电量/DC 拆分/价格/网络为假设，见 sources。",
              mig_max_mw=15, mig_day_share=0.4, pv_curtail_penalty=30.0, carbon_factor=0.1567, carbon_shape="flat",
              carbon_profiles={"qinghai": [0.1567]*24}, carbon_source="MEE 2022 省级（flat）", carbon_price_cny_t=80.0, carbon_accounting="generation")
    return Scenario.model_validate(sc)
if __name__ == "__main__":
    out = [build("grid", "summer"), build("grid", "winter"), build("clean100", "winter"), build("offgrid", "summer"), build("offgrid", "winter")]
    for s in out: open(os.path.join(OUT, f"{s.name}.json"), "w").write(s.model_dump_json(indent=1))
    print([s.name for s in out])
