"""生成 算-电-热-碳 耦合案例预设（中卫 / 和林格尔）。运行: python cases/common/build_coupled.py
所有热/冷/供热/DR 参数除注明来源外为【假设】，写入 scenario.sources。"""
import json, os, sys
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT); sys.path.insert(0, HERE)
from app.scenario import load_preset, DCThermal, HeatNetwork, DREvent
from app.carbon import synthetic_shape
from thermal_params import CLIMATE, thermal_for, heat_demand

SRC = {
    "热模型/冷却参数": "【假设】两节点 RC：C_air=0.01·IT、C_mass=0.08·IT MWh/K，UA_am=0.05·IT MW/K；冷机 1.3×IT 冷量、5 台 N+1；COP=5.5−0.12(T_out−25)∈[2.5,8]；自然冷却 0.9×IT（T_out≤8°C 满出力、≥18°C 无）；参考 ASHRAE TC9.9 与文献量级",
    "热安全边界": "ASHRAE TC9.9 (2021) A1 级：推荐 18–27°C，允许 15–32°C；温度变化率 ≤5°C/h（磁带设备 5°C/h、其他 20°C/h，此处取严）",
    "室外温度": "【假设】正弦典型日：中卫 7 月 17–30°C、1 月 −12–1°C；热浪 25–39°C；上海夏 26–34°C；呼和浩特 1 月 −19~−6°C（取气候平均量级）",
    "碳强度逐时形状": "【假设】西北/蒙西平均因子（MEE 2022）×合成午间光伏低谷形状；边际因子取燃煤机组 0.85–0.95 tCO2/MWh 量级",
}

def carbon_hourly(sc, region, factor):
    sh = synthetic_shape("solar_dip"); sc.carbon_profiles[region] = [round(float(factor*x), 4) for x in sh]
    sc.carbon_marginal_profiles[region] = [round(float(0.95 - 0.25*max(0.0, 1 - abs(h - 13)/6)), 4) for h in range(24)]

def couple(sc, climate, tes=None, hp=None, units=None):
    sc.thermal_mode = "coupled"; sc.outdoor_temp_profiles = climate; sc.carbon_weight = 1.0; sc.carbon_accounting = "location"
    for d in sc.data_centers:
        d.thermal = DCThermal(**thermal_for(d.cap_it_mw, *(tes or {}).get(d.name, (0, 0)), hp_cap=(hp or {}).get(d.name, 0.0),
                                            units=(units or {}).get(d.name, 5)))
    sc.sources.update(SRC); sc.synthetic = False
    return sc

def save(sc, proj, name, note):
    sc.name = name; sc.note = note
    p = os.path.join(ROOT, "cases", proj, f"{name}.json")
    open(p, "w").write(sc.model_dump_json(indent=1)); print("wrote", p)

TES_ZW = {"ZW_NEW_A": (160.0, 32.0), "ZW_NEW_B": (160.0, 32.0)}   # 【假设】新建园区冷冻水蓄冷罐 2h@0.4×IT
DR_ZW = [DREvent(name="宁夏晚高峰削峰", start=19, end=22, kind="reduce", request_mw=40.0, price_cny_mwh=2000.0, baseline_method="plan",
                 dcs=["ZW_EXIST", "ZW_NEW_A", "ZW_NEW_B"], max_mw=60.0, shortfall_penalty_cny_mwh=0.0),
         DREvent(name="午间新能源填谷", start=11, end=14, kind="increase", request_mw=30.0, price_cny_mwh=300.0, baseline_method="plan",
                 dcs=["ZW_EXIST", "ZW_NEW_A", "ZW_NEW_B"], max_mw=30.0)]
DRSRC = {"需求响应": "【假设】参照宁夏电力需求响应实施方案：削峰补偿上限量级 ≈2 元/kWh、填谷 ≈0.3 元/kWh；基线=无 DR 的日前优化计划曲线"}

# 中卫 夏季
s = couple(load_preset("zhongwei_summer_highwind"), {"northwest": CLIMATE["zhongwei_summer"], "shanghai": CLIMATE["shanghai_summer"]}, TES_ZW)
carbon_hourly(s, "northwest", 0.5857); carbon_hourly(s, "shanghai", 0.5849)
save(s, "zhongwei", "zhongwei_summer_coupled", "中卫夏季大风典型日 · 算-电-热-碳耦合（RC 热模型+动态 PUE+蓄冷罐+预冷，碳权重 1）。热参数为假设。")
s2 = s.model_copy(deep=True); s2.dr_events = DR_ZW; s2.sources.update(DRSRC)
save(s2, "zhongwei", "zhongwei_summer_coupled_dr", "中卫夏季 · 耦合 + 电网需求响应（19–22 时削峰 40MW、11–14 时填谷 30MW）。DR 参数为假设。")
# 热浪压力测试：39°C、ZW_NEW_A 1 台冷机检修（备用被占用），上海热浪
s3 = couple(load_preset("zhongwei_summer_highwind"), {"northwest": CLIMATE["zhongwei_heatwave"], "shanghai": CLIMATE["shanghai_heatwave"]}, TES_ZW,
            units={"ZW_NEW_A": 4})
for d in s3.data_centers:
    if d.name == "ZW_NEW_A": d.thermal.chiller_cap_mw_th = round(d.thermal.chiller_cap_mw_th*4/5, 1); d.thermal.redundancy_n1 = False
carbon_hourly(s3, "northwest", 0.5857); carbon_hourly(s3, "shanghai", 0.5849)
s3.dr_events = [DR_ZW[0]]; s3.sources.update(DRSRC); s3.sources["热浪工况"] = "【假设】室外 25–39°C；ZW_NEW_A 1 台冷机检修（5 台中 1 台停运，冷量 −20%，备用已被占用→无 N+1 冗余）"
save(s3, "zhongwei", "zhongwei_heatwave_stress", "中卫夏季热浪热安全压力测试：39°C + 冷机检修 + 晚高峰 DR，观察入口温度/冷量约束起作用。")
# 中卫 冬季 余热供热
s4 = couple(load_preset("zhongwei_winter_highwind"), {"northwest": CLIMATE["zhongwei_winter"], "shanghai": CLIMATE["shanghai_winter"]}, TES_ZW,
            hp={"ZW_EXIST": 20.0, "ZW_NEW_A": 30.0, "ZW_NEW_B": 30.0})
carbon_hourly(s4, "northwest", 0.5857); carbon_hourly(s4, "shanghai", 0.5849)
s4.heat_network = HeatNetwork(name="中卫城区集中供热（沙坡头）", dcs=["ZW_EXIST", "ZW_NEW_A", "ZW_NEW_B"], demand_mw_th=heat_demand(70.0),
                              price_cny_mwh_th=120.0, boiler_ef_t_mwh_th=0.40, pipe_loss=0.06, storage_mwh_th=150.0, storage_p_mw_th=35.0)
s4.dr_events = [DR_ZW[0]]; s4.sources.update(DRSRC)
s4.sources["余热供热"] = "【假设】中卫供暖季 11/15–3/15；余热可接纳热负荷峰值 70MW_th；热泵 COP 4；售热 120 元/MWh_th（≈33 元/GJ）；替代燃煤锅炉 0.40 tCO2/MWh_th（94.6 tCO2/TJ ÷ 效率 0.8 ≈ 0.43）；热网惯性+蓄热 150MWh_th"
save(s4, "zhongwei", "zhongwei_winter_coupled_heat", "中卫冬季 · 耦合 + 余热回收向城区集中供热（热泵 80MW_th + 热网虚拟储热）+ 晚高峰 DR。")
# 和林格尔 冬季 余热供热
s5 = couple(load_preset("helinger_typical_day"), {"mengxi": CLIMATE["hohhot_winter"], "beijing": CLIMATE["beijing_winter"]},
            {"移动_HLGE": (120.0, 25.0)}, hp={"移动_HLGE": 25.0, "电信_HLGE": 20.0, "并行科技_HLGE": 12.0, "中数云科_HLGE": 10.0})
carbon_hourly(s5, "mengxi", s5.carbon_factor if "mengxi" not in s5.carbon_profiles else sum(s5.carbon_profiles["mengxi"])/24)
if "beijing" in s5.carbon_profiles: carbon_hourly(s5, "beijing", sum(s5.carbon_profiles["beijing"])/24)
s5.heat_network = HeatNetwork(name="和林格尔新区集中供热", demand_mw_th=heat_demand(55.0), price_cny_mwh_th=110.0, boiler_ef_t_mwh_th=0.40,
                              pipe_loss=0.08, storage_mwh_th=100.0, storage_p_mw_th=25.0)
s5.sources["余热供热"] = "【假设】和林格尔新区供暖季 10/15–4/15；余热可接纳热负荷峰值 55MW_th；售热 110 元/MWh_th；替代燃煤锅炉 0.40 tCO2/MWh_th"
save(s5, "helinger", "helinger_winter_coupled_heat", "和林格尔冬季 · 算-电-热-碳耦合 + 数据中心余热供暖（热泵 67MW_th + 热网虚拟储热）。")
