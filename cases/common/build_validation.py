"""第二轮真实项目验证案例（8 个公开项目 + 极端场景）。气象 = Open-Meteo ERA5 2024 真实逐时数据（典型日/极端日）。
每个参数在 sources 中注明：URL=公开来源；【假设】=未公开、按量级假设；【校准】=按公开年值缩放。
用法: /workspace/sdco-env/bin/python cases/common/build_validation.py"""
import os, sys, json
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT); sys.path.insert(0, HERE)
import numpy as np
from app.scenario import Scenario, DCThermal, HeatNetwork, DREvent
from app.tools import cooling as CL
from thermal_params import thermal_for
from profiles import tou, hrs
import climate as CM

MEE = "https://www.mee.gov.cn/xxgk2018/xxgk/xxgk01/202412/t20241226_1099413.html"
PEAK_STD, VAL_STD = hrs((8, 11), (18, 22)), hrs((0, 7), (23, 24))
A_THERM = "【假设】RC 热参数按 IT 规模缩放（cases/common/thermal_params.py）；散热方式参数取 app/tools/cooling.py 文献典型值"

def wcal(prof, k): return [round(float(min(1.0, x*k)), 4) for x in prof]

def make(name, site, day, dcs, *, region, cf, price, wind=0, pv=0, hydro=None, ess=None, wind_k=1.0, grid_cap=None, n_tie=2,
         heat=None, dr=None, links=None, extra_dc=None, carbon_price=80.0, green=None, green_pen=None, ppa=None, src=None, note="", export=0.0):
    C = CM.pick(site, day) if isinstance(day, str) else day
    peak = sum(d["it"]*1.35 for d in dcs)
    B = [dict(name="省网 220kV", vn_kv=220), dict(name="新能源/电源汇集站 220kV", vn_kv=220), dict(name="园区 220kV 站", vn_kv=220)]
    B += [dict(name=f"{d['name']} 110kV", vn_kv=110) for d in dcs]
    L = [dict(name="公网联络线 220kV", from_bus=0, to_bus=2, length_km=20, r_ohm_per_km=0.054, x_ohm_per_km=0.39, c_nf_per_km=9.5,
              rating_mva=round(max(1.2*peak, 150)/2, 1), parallel=max(n_tie, 1))]   # 双回，每回 0.6×峰值；N-1 = 1 回
    if wind or pv or hydro: L.append(dict(name="绿电专线 220kV", from_bus=1, to_bus=2, length_km=35, r_ohm_per_km=0.054, x_ohm_per_km=0.39,
                                       c_nf_per_km=9.5, rating_mva=round(max(wind + pv + (hydro or {}).get("mw", 0), 100)*1.1, 1), parallel=1))
    T = [dict(name=f"{d['name']} 220/110kV", hv_bus=2, lv_bus=3 + i, sn_mva=round(d["it"]*1.6, 1), vk_percent=13, parallel=2) for i, d in enumerate(dcs)]
    E = [dict(bus=0, name="省网", vm_pu=1.02, import_max_mw=grid_cap or 1e4, price_cny_kwh=price, export_max_mw=export)]
    G = [dict(name="水电(等效)", bus=1, kind="hydro", pmax_mw=hydro["mw"], cost_cny_mwh=hydro.get("cost", 250), emission_t_mwh=0.0,
              energy_mwh_day=hydro.get("mwh_day"))] if hydro else []
    DCS = []
    for i, d in enumerate(dcs):
        cap = d["it"]; util = d.get("util", 0.75); flex = d.get("flex", 0.2); avg = util*cap; h = np.arange(24)
        inter = (1 - flex)*avg*(1 + 0.06*np.cos(2*np.pi*(h - 20)/24))
        th = DCThermal(**thermal_for(cap, d.get("tes", (0, 0))[0], d.get("tes", (0, 0))[1], hp_cap=d.get("hp", 0.0),
                                     cool_ratio=d.get("cr", 1.3 if CL.MODES[d["mode"]]["family"] == "air" else 0.6)))
        th.air_residual_mode = d.get("residual", "air_iec"); CL.apply_mode(th, d["mode"], d.get("lf"), cap_it=cap)
        if d.get("waste_heat_c") is not None: th.waste_heat_c = d["waste_heat_c"]
        if d.get("hr_frac") is not None: th.hr_max_frac = d["hr_frac"]
        if d.get("rej"): th.heat_rejection = d["rej"]
        th.utilization = util
        DCS.append(dict(name=d["name"], bus=3 + i, cap_it_mw=cap, pue=d.get("pue", 1.25), interactive_mw=[round(float(x), 3) for x in inter],
                        batch_mwh=round(flex*avg*24, 2), pf_q_ratio=0.25, thermal=th.model_dump()))
    PVs = []
    if wind: PVs.append(dict(bus=1, cap_mw=wind, kind="wind", name=f"风电 {wind:g}MW", profile=wcal(C["wind"], wind_k), ppa_price_cny_kwh=ppa))
    if pv: PVs.append(dict(bus=1, cap_mw=pv, kind="pv", name=f"光伏 {pv:g}MW", profile=C["pv"], ppa_price_cny_kwh=ppa))
    sc = dict(name=name, synthetic=False, note=note + f"（气象日 {C['date']}，{C['kind']}）", network_case="custom",
              network=dict(buses=B, lines=L, trafos=T, ext_grids=E, gens=G, note="等值网络：拓扑/阻抗/额定为【假设】"),
              price_kind="tou_assumed", price_cny_kwh=price, grid_markup_cny_mwh=0.0, data_centers=DCS, pv=PVs,
              storage=[dict(name=ess.get("name", "ESS"), bus=ess.get("bus", 2), energy_mwh=ess["mwh"], power_mw=ess["mw"], soc0=0.5)] if ess else [],
              mig_max_mw=20, mig_day_share=0.4, pv_curtail_penalty=30.0, min_green_share=green, green_shortfall_penalty_cny_mwh=green_pen,
              carbon_factor=cf, carbon_shape="flat", carbon_profiles={region: [cf]*24}, bus_region={i: region for i in range(len(B))},
              carbon_source="MEE 2022 省级电力平均因子（flat）", carbon_price_cny_t=carbon_price, carbon_weight=1.0, carbon_accounting="location",
              thermal_mode="coupled", outdoor_temp_c=C["T"], outdoor_temp_profiles={region: C["T"]}, outdoor_rh=float(np.mean(C["RH"])),
              outdoor_rh_profiles={region: C["RH"]}, dr_events=dr or [], links=links or [],
              sources={**(src or {}), "气象": C["source"], "碳因子": f"{region} {cf} tCO2/MWh（生态环境部 2022 省级电力平均因子）{MEE}", "热模型": A_THERM})
    if heat: sc["heat_network"] = heat
    if extra_dc:   # 远端 DC（独立电网，算力迁移目的地）
        nb = len(B); sc["network"]["buses"].append(dict(name=extra_dc["bus_name"], vn_kv=110))
        sc["network"]["ext_grids"].append(dict(bus=nb, name=extra_dc["grid_name"], price_cny_kwh=extra_dc["price"]))
        cap = extra_dc["it"]; inter = [round(0.6*cap, 3)]*24
        th = DCThermal(**thermal_for(cap)); CL.apply_mode(th, "air_iec", cap_it=cap)
        sc["data_centers"].append(dict(name=extra_dc["name"], bus=nb, cap_it_mw=cap, pue=1.3, interactive_mw=inter, batch_mwh=round(0.1*cap*24, 2), thermal=th.model_dump()))
        sc["bus_region"][nb] = extra_dc["region"]; sc["carbon_profiles"][extra_dc["region"]] = [extra_dc["cf"]]*24
        Ce = CM.pick(extra_dc["site"], C["date"]) if extra_dc.get("site") else C
        sc["outdoor_temp_profiles"][extra_dc["region"]] = Ce["T"]; sc["outdoor_rh_profiles"][extra_dc["region"]] = Ce["RH"]
    return Scenario.model_validate(sc)

def save(proj, sc):
    d = os.path.join(ROOT, "cases", proj); os.makedirs(d, exist_ok=True)
    open(os.path.join(d, f"{sc.name}.json"), "w").write(sc.model_dump_json(indent=1)); return sc.name

OUT = {}
# ---------- 1. 中金数据乌兰察布低碳算力基地 源网荷储一体化 ----------
S1 = {"风电200MW(26×7.7MW)/光伏100MW/储能45MW、年自发自用绿电8.48亿kWh、可再生替代率38.74%、2025-07投运": "https://www.goldwind.com/cn/news/focus-1140319739541904384/",
      "绿电约占总用电35%、2.5万架机柜、12栋机房、双回线路": "http://www.sasac.gov.cn/n2588025/n2588129/c34048855/content.html",
      "园区设计 PUE 1.147、WUE 0.97": "https://www.dtdata.cn/index.php?c=show&id=1122",
      "二期 280MW风+100MW光+57.5MW/230MWh 储能（≈4h，用于推断一期储能时长）": "https://www.ceec.net.cn/art/2025/10/18/art_11019_2536969.html",
      "【推断】IT 负荷": "8.48亿kWh ÷ 38.74% ≈ 21.9亿kWh/年 → 平均电网侧 ≈250MW；÷PUE1.147 → 平均 IT≈218MW；按利用率 0.8 → IT 容量 ≈270MW（≈10.8kW/柜×2.5万柜）",
      "【假设】": "储能 4h=180MWh（参照二期）；间接蒸发冷却；蒙西分时电价 0.48/0.36/0.22；PPA 0.26 元/kWh；碳价 80 元/t；网络阻抗",
      "【校准】风电": "ERA5 100m 风速+通用功率曲线年利用 1166h，远低于项目推算值（(8.48亿−100MW×1267h)/200MW≈3605h）；风电曲线 ×2.4 校准（截断至 1.0）后年值仍偏低，见报告"}
P_MX = tou(0.48, 0.36, 0.22, hrs((7, 11), (17, 22)), hrs((0, 6), (11, 15)))
U = [dict(name="中金_乌兰察布", it=270, mode="air_iec", util=0.8, flex=0.2, pue=1.147)]
for day, tag in [("summer_typical", "summer"), ("winter_typical", "winter"), ("lowwind", "lowwind"), ("coldwave", "coldwave")]:
    OUT.setdefault("ulanqab_cicdata", []).append(save("ulanqab_cicdata", make(f"ulanqab_cicdata_{tag}", "ulanqab", day, U, region="mengxi", cf=0.6849, price=P_MX,
        wind=200, pv=100, ess=dict(mw=45, mwh=180), wind_k=2.4, ppa=0.26, src=S1, note="中金数据乌兰察布 源网荷储一体化（风200+光100+储45MW）")))
sc = make("ulanqab_cicdata_carbon300", "ulanqab", "winter_typical", U, region="mengxi", cf=0.6849, price=P_MX, wind=200, pv=100, ess=dict(mw=45, mwh=180),
          wind_k=2.4, ppa=0.26, carbon_price=300.0, src={**S1, "【压力】碳价": "碳价 80→300 元/t（欧盟 EUA ≈ 70€/t 量级，【假设】）"}, note="乌兰察布 碳价飙升压力测试")
OUT["ulanqab_cicdata"].append(save("ulanqab_cicdata", sc))

# ---------- 2. 世纪互联乌兰察布 源网荷储（ODCC 算电协同案例） ----------
S2 = {"风电200MW/光伏100MW/储能45MW×4h、绿色专线直供、算力电力智慧协同": "https://www.odcc.org.cn/news/p-1932682835250749442.html",
      "【假设】": "IT 150MW（未公开）、风冷冷冻水+板换自然冷却、PUE 名义 1.20、利用率 0.75、灵活 30%、绿电占比下限 60%、电价同蒙西假设"}
V = [dict(name="世纪互联_乌兰察布", it=150, mode="air_chw", util=0.75, flex=0.3, pue=1.2)]
for day, tag in [("summer_typical", "summer"), ("lowwind", "lowwind")]:
    OUT.setdefault("ulanqab_21vianet", []).append(save("ulanqab_21vianet", make(f"ulanqab_21vianet_{tag}", "ulanqab", day, V, region="mengxi", cf=0.6849, price=P_MX,
        wind=200, pv=100, ess=dict(mw=45, mwh=180), wind_k=2.4, ppa=0.26, green=0.6, green_pen=60.0, src={**S2, "【假设】绿电缺口": "日内绿电 60% 为软约束，缺口按 60 元/MWh（≈绿证价格量级）计罚"},
        note="世纪互联乌兰察布 源网荷储（绿电直供，绿电≥60% 软约束）")))
OUT["ulanqab_21vianet"].append(save("ulanqab_21vianet", make("ulanqab_21vianet_lowwind_hardgreen", "ulanqab", "lowwind", V, region="mengxi", cf=0.6849, price=P_MX,
    wind=200, pv=100, ess=dict(mw=45, mwh=180), wind_k=2.4, ppa=0.26, green=0.6, src=S2, note="世纪互联乌兰察布 低风日 · 绿电 60% 硬约束（压力测试：预期不可行）")))

# ---------- 3. 韶关数据中心集群（华南数谷：冷板液冷 1 层 PUE1.15 + 风冷 2–5 层 PUE≈1.25） ----------
S3 = {"起步区 PUE≤1.25、上架率≥65%": "https://www.ndrc.gov.cn/xxgk/zcfb/tz/202202/t20220216_1315627.html",
      "华南数谷 液冷层 PUE1.15/风冷层≈1.25、韶关水电219万kW/光伏260万kW、绿电直供试点": "https://static.nfnews.com/content/202506/13/c11393901.html",
      "园区绿电利用率≥50% 目标、2025 集群负荷 90万kW": "https://www.sg.gov.cn/2021xzfb/lvsg/stpz/stcy/content/post_2378940.html",
      "【假设】": "园区 IT 100MW（液冷 20 + 风冷 80）、等效水电 120MW 日电量 1800MWh、园区光伏 60MW、广东分时电价 1.05/0.65/0.28、DR 参数"}
P_GD = tou(1.05, 0.65, 0.28, hrs((10, 12), (14, 19)), VAL_STD)
SG = [dict(name="华南数谷_液冷", it=20, mode="liquid_cold_plate", util=0.8, flex=0.25, pue=1.15, rej="hybrid", cr=1.0),
      dict(name="华南数谷_风冷", it=80, mode="air_chw", util=0.7, flex=0.2, pue=1.25, tes=(80, 20))]
DRg = [DREvent(name="广东迎峰度夏削峰", start=15, end=18, kind="reduce", request_mw=15, price_cny_mwh=3500, baseline_method="plan", max_mw=20)]
for day, tag, kw in [("summer_typical", "summer", {}), ("winter_typical", "winter", {}), ("heatwave", "heatwave_dr", dict(dr=DRg)),
                     ("heatwave", "heatwave_n1", dict(n_tie=1))]:
    OUT.setdefault("shaoguan", []).append(save("shaoguan", make(f"shaoguan_{tag}", "shaoguan", day, SG, region="guangdong", cf=0.4403, price=P_GD,
        pv=60, hydro=dict(mw=120, mwh_day=1800, cost=280), green=0.5, green_pen=60.0, src={**S3, "【假设】液冷排热": "冷板一次侧干湿联合冷却器（闭式塔）", "【假设】绿电缺口": "50% 目标为软约束 60 元/MWh"}, note="韶关集群·华南数谷（冷板液冷+风冷，水电+光伏）", **kw)))

# ---------- 4. 华为云贵安数据中心（直通风自然冷却，PUE 1.12） ----------
S4 = {"实际运行 PUE 1.12、直通风自然冷却+瀑布/湖水、余热回收、AI 削峰填谷、100万台服务器": "https://www.huawei.com/cn/sustainability/the-latest/stories/green-data-centers-optimal-pue",
      "贵安年均 15°C": "https://www.huaweicloud.com/cloudplus/eleventhphase/detail03.html",
      "【假设】": "IT 100MW（未公开 MW）、贵州分时电价 0.82/0.55/0.26、无本地新能源"}
P_GZ = tou(0.82, 0.55, 0.26, PEAK_STD, VAL_STD)
GA = [dict(name="华为云_贵安", it=100, mode="air_dec", util=0.7, flex=0.25, pue=1.12)]
for day, tag in [("summer_typical", "summer"), ("winter_typical", "winter"), ("heatwave", "heatwave")]:
    OUT.setdefault("guian_huawei", []).append(save("guian_huawei", make(f"guian_huawei_{tag}", "guian", day, GA, region="guizhou", cf=0.4989, price=P_GZ,
        src=S4, note="华为云贵安（直通风/直接蒸发自然冷却）")))

# ---------- 5. 阿里巴巴浙江云计算仁和数据中心（单相浸没液冷，PUE 1.09） ----------
S5 = {"全浸没液冷、PUE 低至 1.09、冷却不依赖气象条件、无冷机/空调": "https://developer.aliyun.com/article/785850",
      "5100 标准机架、10 万台设备、142 亩": "https://hznews.hangzhou.com.cn/jingji/content/2018-09/28/content_7075062.htm",
      "【假设】": "IT 40MW（5100 柜×≈8kW，未公开 MW）、浙江分时电价 1.02/0.66/0.30、浸没液冷由干冷器为主"}
P_ZJ = tou(1.02, 0.66, 0.30, PEAK_STD, VAL_STD)
RH_ = [dict(name="阿里_仁和浸没", it=40, mode="liquid_immersion", util=0.75, flex=0.2, pue=1.09)]
for day, tag in [("summer_typical", "summer"), ("heatwave", "heatwave"), ("winter_typical", "winter")]:
    OUT.setdefault("renhe_alibaba", []).append(save("renhe_alibaba", make(f"renhe_alibaba_{tag}", "hangzhou_renhe", day, RH_, region="zhejiang", cf=0.5153, price=P_ZJ,
        src=S5, note="阿里仁和单相浸没液冷数据中心（一次侧干冷器）")))
OUT["renhe_alibaba"].append(save("renhe_alibaba", make("renhe_alibaba_heatwave_hybrid", "hangzhou_renhe", "heatwave", [dict(RH_[0], rej="hybrid")], region="zhejiang", cf=0.5153,
    price=P_ZJ, src={**S5, "【假设】改进": "一次侧改为干湿联合冷却器（闭式塔湿工况补冷）"}, note="阿里仁和 热浪日 · 干湿联合排热")))

# ---------- 6. 中国电信长三角（芜湖）智算中心（液冷 DC 舱，芜湖集群 PUE 目标 1.25） ----------
S6 = {"规划超 8 万标准机柜、液冷 DC 舱、智算 600P→1000P": "https://www.dtdata.cn/news/show/2055.html",
      "芜湖集群 PUE 目标 1.25、实际约 1.3–1.5（建议稿）": "http://www.wuhurd.gov.cn/xbcs/rddb/yajy/8494471.html",
      "【假设】": "一期 IT 60MW、混合（液冷 60%+风冷冷冻水）、屋顶光伏 20MW、储能 20MW/40MWh、安徽分时电价 0.98/0.62/0.29"}
P_AH = tou(0.98, 0.62, 0.29, PEAK_STD, VAL_STD)
WH = [dict(name="电信_芜湖智算", it=60, mode="hybrid", lf=0.6, residual="air_chw", util=0.8, flex=0.3, pue=1.25, rej="hybrid", cr=1.0)]
for day, tag, cp in [("summer_typical", "summer", 80.0), ("heatwave", "heatwave", 80.0), ("summer_typical", "carbon300", 300.0)]:
    OUT.setdefault("wuhu_telecom", []).append(save("wuhu_telecom", make(f"wuhu_telecom_{tag}", "wuhu", day, WH, region="anhui", cf=0.6782, price=P_AH,
        pv=20, ess=dict(mw=20, mwh=40), carbon_price=cp, src={**S6, "【假设】冷源": "冷机 1.0×IT（N+1）+ 液冷一次侧干湿联合"}, note="中国电信芜湖智算中心（液冷 DC 舱混合）")))
OUT["wuhu_telecom"].append(save("wuhu_telecom", make("wuhu_telecom_heatwave_undersized", "wuhu", "heatwave", [dict(WH[0], rej=None, cr=0.6)], region="anhui", cf=0.6782, price=P_AH,
    pv=20, ess=dict(mw=20, mwh=40), src={**S6, "【压力】冷源欠配": "冷机 0.6×IT（构建器液冷默认）+ 干冷器"}, note="芜湖智算 热浪日 · 冷源按液冷默认 0.6×IT 欠配（预期不可行，检验诊断）")))

# ---------- 7. 上海临港智算中心 · 虚拟电厂需求响应（2026-07-10 实际事件） ----------
S7 = {"2026-07-10 15:00–17:00 申报削峰 23MW、实际 22.84MW（准确率 99.3%）、站内储能 18MW/36MWh、提前通知 ≤30min": "https://www.jfdaily.com/wx/detail.do?id=1153572",
      "2025 跨省算力转移至湖北十堰、单机负荷 −75%、全量最大可降 8MW": "https://www.shanghai.gov.cn/nw4411/20250710/0560ceb9113c4eed9f0e2ab276e68199.html",
      "【假设】": "临港 IT 30MW（冷板液冷）、可调批处理 25%、十堰 DC 20MW、迁移链路 8MW、上海分时电价 1.18/0.72/0.31、补偿 4000 元/MWh、精准响应偏差考核 2000 元/MWh"}
P_SH = tou(1.18, 0.72, 0.31, hrs((8, 11), (13, 15), (18, 21)), hrs((22, 24), (0, 6)))
LG = [dict(name="临港智算", it=30, mode="liquid_cold_plate", util=0.85, flex=0.25, pue=1.2)]
EXT = dict(name="十堰DC", it=20, bus_name="湖北十堰 DC 110kV", grid_name="华中电网(湖北)", price=tou(0.95, 0.62, 0.30, PEAK_STD, VAL_STD), region="hubei", cf=0.4364)
_d = CM.days(CM.fetch("shanghai_lingang", start="2026-07-01", end="2026-07-31")); _i = _d["date"].index("2026-07-10")
C_LG = dict(site="shanghai_lingang", kind="event", date="2026-07-10", T=[round(float(x), 1) for x in _d["T"][_i]], RH=[round(float(x)/100, 3) for x in _d["RH"][_i]],
            wind=[round(float(x), 4) for x in CM.wind_cf(_d["W"][_i])], pv=[round(float(x), 4) for x in CM.pv_cf(_d["G"][_i])],
            source="Open-Meteo ERA5 2026-07-10 上海临港（30.9N,121.9E）实际事件日 https://open-meteo.com/")
for tag, sto, link in [("dr_ess", ["ESS_临港"], 8.0), ("dr_noess", [], 8.0), ("dr_nomig", ["ESS_临港"], 0.0)]:
    ev = [DREvent(name="上海数据中心专项快速削峰", start=15, end=17, kind="reduce", request_mw=23, price_cny_mwh=4000, baseline_method="plan",
                  dcs=["临港智算"], storages=sto, shortfall_penalty_cny_mwh=2000)]
    lk = [dict(a="临港智算", b="十堰DC", latency_ms=18, bw_mw=link)] if link else [dict(a="临港智算", b="十堰DC", latency_ms=18, bw_mw=0.0)]
    OUT.setdefault("lingang_dr", []).append(save("lingang_dr", make(f"lingang_{tag}", "shanghai_lingang", C_LG, LG, region="shanghai", cf=0.5849,
        price=P_SH, ess=dict(name="ESS_临港", mw=18, mwh=36, bus=3), dr=ev, links=lk, extra_dc=EXT, src=S7, note="上海临港智算中心 虚拟电厂削峰（储能+跨省迁移）")))

# ---------- 8. Meta Odense 数据中心余热 → Fjernvarme Fyn 区域供热（国际对标） ----------
S8 = {"热泵总供热≈45MW、氨热泵升温至 70–75°C、215,000MWh/年 设计": "https://www.ramboll.com/projects/energy/meta-surplus-heat-to-district-heating",
      "当前 165,000MWh/年、约 9,000 户": "https://datacenters.atmeta.com/wp-content/uploads/2026/09/Metas-Odense-Data-Center.pdf",
      "首期热泵 24MW、COP 4.5–5.0、源水约 27°C、管网 70–80°C": "https://www.ca-eed.eu/wp-content/uploads/2021/10/2_IS6.6_Facebook_DK_Chan-Nguyen.pdf",
      "【假设】": "IT 90MW（未公开）、直接蒸发新风冷却、丹麦电价折合 0.9/1.3/0.6 元/kWh、电网因子 0.12 tCO2/MWh（量级）、热价 200 元/MWh_th、热网可接纳 60MW"}
P_DK = tou(1.3, 0.9, 0.6, hrs((17, 21),), hrs((0, 6),))
OD = [dict(name="Meta_Odense", it=90, mode="air_dec", util=0.75, flex=0.2, pue=1.1, hp=45.0, waste_heat_c=27.0, hr_frac=0.6)]
for day, tag, eta in [("winter_typical", "winter", 0.5), ("winter_typical", "winter_eta07", 0.7), ("coldwave", "coldwave", 0.5), ("summer_typical", "summer", 0.5)]:
    hn = HeatNetwork(name="Fjernvarme Fyn 区域供热", dcs=["Meta_Odense"], demand_mw_th=[60.0 if tag != "summer" else 20.0]*24, price_cny_mwh_th=200.0,
                     boiler_ef_t_mwh_th=0.22, pipe_loss=0.03, storage_mwh_th=200.0, storage_p_mw_th=30.0, terminal_type="radiator",
                     t_supply_min_c=70.0, t_supply_max_c=75.0, t_return_c=40.0, t_out_design_c=-8.0, pipe_length_km=0.6, hp_eta_carnot=eta, hp_max_out_c=80.0)
    OUT.setdefault("odense_meta", []).append(save("odense_meta", make(f"odense_meta_{tag}", "odense", day, OD, region="denmark", cf=0.12, price=P_DK,
        heat=hn, src=S8, note="Meta Odense 余热经热泵并入区域供热（国际对标）")))

if __name__ == "__main__":
    os.makedirs(os.path.join(ROOT, "cases", "validation", "out"), exist_ok=True)
    json.dump(OUT, open(os.path.join(ROOT, "cases", "validation", "out", "presets.json"), "w"), ensure_ascii=False, indent=1)
    print(json.dumps(OUT, ensure_ascii=False))
    print({s: CM.annual_cf(s) for s in ["ulanqab"]})
