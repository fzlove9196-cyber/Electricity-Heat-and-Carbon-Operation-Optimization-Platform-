"""散热方式库（风冷/液冷/混合）+ 逐时性能预计算（保持 LP 线性）。
每种方式给出：送/回风(液)温度、机械制冷 COP 对室外干球/湿球的分段线性曲线、自然冷却阈值、风机水泵电耗、
热容/惯性、热安全边界、WUE、余热源温度、投资量级。数值为文献典型值（见 sources），工程中应以厂家/实测替换。"""
from __future__ import annotations
import numpy as np

SRC = {
    "ASHRAE": "ASHRAE TC9.9 Thermal Guidelines for Data Processing Environments 5th ed.（A1 推荐 18-27°C，允许 15-32°C；液冷 W17-W45/W+ 等级） https://www.ashrae.org/technical-resources/bookstore/datacom-series",
    "ASHRAE_LIQ": "ASHRAE TC9.9 Liquid Cooling Guidelines / Water-Cooled Servers (W32/W40/W45/W+) https://www.ashrae.org/file%20library/technical%20resources/bookstore/supplemental%20files/referencecard_2021thermalguidelines.pdf",
    "ODCC": "ODCC《冷板式液冷服务器可靠性白皮书》/中国移动·电信·联通《电信运营商液冷技术白皮书》(2023) 冷板供液 35-45°C、PUE≤1.25/1.15 https://www.odcc.org.cn/",
    "IEC_PUE": "间接蒸发冷却：《数据中心间接蒸发冷却技术白皮书》（ODCC/华为）年均 PUE 1.15-1.25 量级；WUE 0.5-1.0 L/kWh",
    "WUE": "The Green Grid WP#35 Water Usage Effectiveness (WUE)；冷却塔数据中心典型 1.0-1.8 L/kWh https://www.thegreengrid.org/",
    "IMM": "单相浸没：阿里巴巴仁和/千岛湖浸没液冷 PUE≈1.09（阿里云公开资料） https://www.alibabacloud.com/ ; 3M/GRC 单相浸没回液 45-60°C",
    "SDP": "Stockholm Data Parks：数据中心余热经热泵并入 Stockholm Exergi 区域供热（回收源温度 25-35°C，热泵升至 68-90°C） https://stockholmdataparks.com/",
    "TENCENT": "腾讯天津数据中心余热回收：机房回风/冷凝热经热泵为园区及周边供暖（公开报道） https://cloud.tencent.com/",
    "CARNOT": "热泵 COP 卡诺效率法：COP = η·T_sink/(T_sink−T_evap)，η≈0.45-0.6（IEA HPT Annex 47/48；Arpagaus et al., Energy 2018 高温热泵综述）",
    "DH": "CJJ 34《城镇供热管网设计标准》/ GB 50736：地暖供水 35-45°C(≤60)、风机盘管 45-55、散热器 60-75(85/60 设计)、一次网 70-130°C；保温管沿程温降约 0.1-0.3 K/km",
    "DEC": "ASHRAE Handbook—HVAC Systems & Equipment ch.41 Evaporative Air-Cooling：直接蒸发送风温度 T_s = T_db − ε(T_db − T_wb)，饱和效率 ε≈0.70–0.95",
    "TOWER": "闭式冷却塔/干湿联合冷却器：出水温度 ≈ T_wb + 逼近度 4–6 K；冷板 CDU 板换端差 2–3 K（ODCC 液冷白皮书、CTI 冷却塔手册量级）",
    "STULL": "Stull (2011) 湿球温度经验公式，J. Appl. Meteor. Climatol. 50:2267",
}

# family: air / liquid；node: RC 模型主节点代表的温度（air=机柜入口空气；liquid=冷却液供液温度）
MODES = {
  "air_chw": dict(cn="风冷-冷冻水（冷机+冷却塔+水侧自然冷却）", family="air", icon="❄️",
      supply_c=24.0, return_c=36.0, cop_basis="wet", cop_pw=[[5, 8.0], [15, 6.5], [22, 5.5], [28, 4.3], [32, 3.6]],
      free_basis="wet", free_full_c=2.0, free_zero_c=10.0, free_cop=16.0, aux_kw_per_kw=0.045,
      wue_l_kwh=1.6, wue_dry_below_c=0.0, waste_heat_c=32.0, hr_max_frac=0.6,
      t_min_c=18.0, t_rec_max_c=27.0, t_allow_max_c=32.0, ramp_max_k_h=5.0, c_air_per_mw=0.010, c_mass_per_mw=0.08,
      chip_rise_k=None, coolant_limit_c=None, pue_typical="1.25-1.40", capex_cny_kw="8000-10000",
      src=["ASHRAE", "WUE"], note="冷冻水 12/18°C；冷却塔蒸发耗水；冬季板换自然冷却；余热取自冷凝器侧 30-35°C"),
  "air_iec": dict(cn="风冷-间接蒸发冷却（IEC，干/湿模式+机械补冷）", family="air", icon="🌬️",
      supply_c=24.0, return_c=37.0, cop_basis="dry", cop_pw=[[15, 8.0], [25, 6.0], [35, 4.2], [40, 3.5]],
      free_basis="wet", free_full_c=10.0, free_zero_c=19.0, free_cop=12.0, aux_kw_per_kw=0.06,
      wue_l_kwh=0.8, wue_dry_below_c=8.0, waste_heat_c=36.0, hr_max_frac=0.5,
      t_min_c=18.0, t_rec_max_c=27.0, t_allow_max_c=32.0, ramp_max_k_h=5.0, c_air_per_mw=0.010, c_mass_per_mw=0.08,
      chip_rise_k=None, coolant_limit_c=None, pue_typical="1.15-1.25", capex_cny_kw="7000-9000",
      src=["IEC_PUE", "ASHRAE"], note="室外空气与机房回风经换热芯体隔离换热；湿模式喷淋耗水；回风 35-38°C 为余热源"),
  "air_dec": dict(cn="风冷-直接蒸发/新风自然冷却", family="air", icon="💨",
      supply_c=24.0, return_c=36.0, cop_basis="dry", cop_pw=[[20, 5.0], [30, 4.0], [38, 3.0]],
      free_basis="dec", dec_eff=0.85, free_full_c=20.0, free_zero_c=26.0, free_cop=18.0, aux_kw_per_kw=0.07,
      wue_l_kwh=1.0, wue_dry_below_c=12.0, waste_heat_c=34.0, hr_max_frac=0.45,
      t_min_c=18.0, t_rec_max_c=27.0, t_allow_max_c=32.0, ramp_max_k_h=5.0, c_air_per_mw=0.008, c_mass_per_mw=0.06,
      chip_rise_k=None, coolant_limit_c=None, pue_typical="1.10-1.25", capex_cny_kw="5000-7000",
      src=["ASHRAE", "WUE", "DEC"], note="新风直接进入机房（需过滤/湿度控制，沙尘地区风险）；自然冷却按直接蒸发送风温度 T_db−ε(T_db−T_wb) 判定（≤20°C 满、≥26°C 无）；DX 机械补冷"),
  "liquid_cold_plate": dict(cn="液冷-冷板（高温水，干冷器为主，残余风冷）", family="liquid", icon="🧊",
      supply_c=40.0, return_c=50.0, cop_basis="dry", cop_pw=[[25, 9.0], [35, 7.0], [45, 5.0]],
      free_basis="dry", free_full_c=30.0, free_zero_c=37.0, free_cop=28.0, aux_kw_per_kw=0.03,
      wue_l_kwh=0.15, wue_dry_below_c=99.0, waste_heat_c=50.0, hr_max_frac=0.75,
      t_min_c=25.0, t_rec_max_c=42.0, t_allow_max_c=45.0, ramp_max_k_h=3.0, c_air_per_mw=0.004, c_mass_per_mw=0.03,
      chip_rise_k=30.0, coolant_limit_c=45.0, pue_typical="1.10-1.20", capex_cny_kw="10000-13000", default_liquid_frac=0.75,
      src=["ODCC", "ASHRAE_LIQ"], note="冷板带走 CPU/GPU 约 70-80% 发热，供液 35-45°C、回液 45-55°C；其余经残余风冷；绝大多数小时无需冷机"),
  "liquid_immersion": dict(cn="液冷-单相浸没", family="liquid", icon="🛢️",
      supply_c=40.0, return_c=55.0, cop_basis="dry", cop_pw=[[30, 9.0], [40, 7.0], [48, 5.0]],
      free_basis="dry", free_full_c=32.0, free_zero_c=40.0, free_cop=32.0, aux_kw_per_kw=0.02,
      wue_l_kwh=0.05, wue_dry_below_c=99.0, waste_heat_c=55.0, hr_max_frac=0.9,
      t_min_c=25.0, t_rec_max_c=45.0, t_allow_max_c=48.0, ramp_max_k_h=3.0, c_air_per_mw=0.02, c_mass_per_mw=0.05,
      chip_rise_k=25.0, coolant_limit_c=48.0, pue_typical="1.04-1.10", capex_cny_kw="12000-16000", default_liquid_frac=0.95,
      src=["IMM", "ASHRAE_LIQ"], note="服务器浸没于介电液，回液 45-60°C，几乎全部发热进入液体；冷却液热容大（惯性大）"),
}
MODES["hybrid"] = dict(MODES["liquid_cold_plate"], cn="混合（液冷比例可调 + 风冷）", icon="🔀", default_liquid_frac=0.5,
                       note="液冷部分按冷板参数，残余部分按 air_residual_mode；节点温度按风冷入口约束")

def wet_bulb(t, rh=0.35):
    """Stull 2011 湿球温度近似（°C）。rh 0-1。"""
    t = np.asarray(t, float); R = rh*100
    return (t*np.arctan(0.151977*np.sqrt(R + 8.313659)) + np.arctan(t + R) - np.arctan(R - 1.676331)
            + 0.00391838*R**1.5*np.arctan(0.023101*R) - 4.686035)

def _pw(points, x):
    p = np.asarray(points, float); return np.interp(x, p[:, 0], p[:, 1])

def _one(md, tout, rh):
    tw = wet_bulb(tout, rh)
    xc = tw if md["cop_basis"] == "wet" else np.asarray(tout, float)
    td = np.asarray(tout, float)
    xf = tw if md["free_basis"] == "wet" else (td - md.get("dec_eff", 0.85)*(td - tw) if md["free_basis"] == "dec" else td)
    cop = _pw(md["cop_pw"], xc)
    ff = np.clip((md["free_zero_c"] - xf)/max(md["free_zero_c"] - md["free_full_c"], 1e-6), 0, 1)
    wue = np.where(np.asarray(tout) < md["wue_dry_below_c"], 0.15*md["wue_l_kwh"], md["wue_l_kwh"])
    return cop, ff, md["free_cop"]*np.ones_like(cop), wue

def liquid_fraction(th):
    md = MODES.get(th.cooling_mode or "", {})
    if md.get("family") != "liquid": return 0.0
    if th.cooling_mode == "hybrid": return float(th.liquid_frac)
    return float(th.liquid_frac) if th.liquid_frac > 0 else md.get("default_liquid_frac", 1.0)

def hourly(th, tout, rh=0.35):
    """返回 dict(cop, ff, free_cop, wue, lf)。液冷/混合：按液冷比例加权（自然冷却比例线性加权，COP 按电耗调和加权）。"""
    if not th.cooling_mode or th.cooling_mode not in MODES:
        from .thermal import cop_curve, free_frac
        return dict(cop=cop_curve(th, tout), ff=free_frac(th, tout), free_cop=th.free_cop*np.ones(len(tout)),
                    wue=np.full(len(tout), th.wue_l_kwh if th.wue_l_kwh is not None else 1.2), lf=0.0)
    md = MODES[th.cooling_mode]; lf = liquid_fraction(th)
    c1, f1, fc1, w1 = _one(md, tout, rh)
    hr = getattr(th, "heat_rejection", None)
    if md["family"] == "liquid" and hr in ("wet", "hybrid"):   # 闭式冷却塔：按湿球 + 逼近度（塔 5K + CDU 板换 3K）判定液冷自然冷却
        tw = wet_bulb(tout, rh)
        fw = np.clip((md["free_zero_c"] - 8.0 - tw)/max(md["free_zero_c"] - md["free_full_c"], 1e-6), 0, 1)   # 等效：T_wb+8K 代入干球阈值
        fw_used = fw if hr == "wet" else np.maximum(f1, fw)
        w1 = w1 + 1.2*np.clip(fw_used - (f1 if hr == "hybrid" else 0), 0, 1)   # 湿工况耗水（≈冷却塔 1.2 L/kWh × 湿运行比例）
        f1 = fw_used
    if lf < 1.0 and md["family"] == "liquid":
        c2, f2, fc2, w2 = _one(MODES[th.air_residual_mode], tout, rh)
        cop = 1/(lf/c1 + (1 - lf)/c2); ff = lf*f1 + (1 - lf)*f2; fc = 1/(lf/fc1 + (1 - lf)/fc2); w = lf*w1 + (1 - lf)*w2
    else: cop, ff, fc, w = c1, f1, fc1, w1
    if th.wue_l_kwh is not None: w = np.full(len(tout), th.wue_l_kwh)
    return dict(cop=cop, ff=ff, free_cop=fc, wue=w, lf=lf)

def source_temp(th):
    """余热源温度（°C）：液冷按液冷比例与残余风冷回风加权的“可回收高品位部分”取液冷回液温度。"""
    if th.waste_heat_c is not None: return float(th.waste_heat_c)
    md = MODES.get(th.cooling_mode or "")
    if md is None: return 32.0
    return float(md["waste_heat_c"])

def apply_mode(th, mode, liquid_frac=None, keep_caps=True, cap_it=None):
    """把散热方式库的默认参数写入 DCThermal（温度边界、热容、辅机、回收比例等）。冷量装机保持（keep_caps）。"""
    md = MODES[mode]; th.cooling_mode = mode
    if liquid_frac is not None: th.liquid_frac = float(liquid_frac)
    elif mode == "hybrid": th.liquid_frac = md["default_liquid_frac"]
    else: th.liquid_frac = 0.0
    lf = liquid_fraction(th)
    node_liquid = md["family"] == "liquid" and lf >= 0.5 and mode != "hybrid"
    ref = md if node_liquid else MODES["air_iec" if md["family"] == "liquid" else mode]
    for k in ("t_min_c", "t_rec_max_c", "t_allow_max_c", "ramp_max_k_h"): setattr(th, k, ref[k])
    th.t0_c = md["supply_c"] if node_liquid else 24.0
    th.tower_pump_kw_per_kw = md["aux_kw_per_kw"]
    th.hr_max_frac = md["hr_max_frac"]*(lf if md["family"] == "liquid" else 1) + (MODES[th.air_residual_mode]["hr_max_frac"]*(1 - lf) if md["family"] == "liquid" else 0)
    if cap_it:
        th.c_air_mwh_k = round(ref["c_air_per_mw"]*cap_it, 4); th.c_mass_mwh_k = round(ref["c_mass_per_mw"]*cap_it, 4)
    if md["family"] == "liquid":   # 液冷几乎全年干冷器自然冷却 → 自然冷却能力按 IT 配满，冷机仅作补冷
        if cap_it: th.free_cap_mw_th = round(1.1*cap_it, 1)
    return th

def node_is_liquid(th):
    """RC 主节点是否代表液冷供液温度（冷板/浸没且液冷比例≥0.5，hybrid 除外）——此时风冷入口温度标准（ASHRAE A1 等）不适用。"""
    md = MODES.get(getattr(th, "cooling_mode", None) or "")
    return bool(md) and md["family"] == "liquid" and th.cooling_mode != "hybrid" and liquid_fraction(th) >= 0.5

def library():
    out = []
    for k, m in MODES.items():
        out.append(dict(key=k, **{x: m[x] for x in ("cn", "family", "icon", "supply_c", "return_c", "cop_basis", "cop_pw", "free_basis", "free_full_c", "free_zero_c",
                                                   "free_cop", "aux_kw_per_kw", "wue_l_kwh", "waste_heat_c", "hr_max_frac", "t_min_c", "t_rec_max_c", "t_allow_max_c",
                                                   "coolant_limit_c", "chip_rise_k", "pue_typical", "capex_cny_kw", "note")},
                        sources=[SRC[s] for s in m["src"]]))
    return out

def safety_report(th, it_series, tnode_series, cap_it):
    """液冷：芯片/壳温代理 = T_供液 + 温升×负载率 ≤ 85°C（典型 GPU/CPU Tcase 限值 85-95）；风冷：入口温度等级。"""
    md = MODES.get(th.cooling_mode or "")
    if not md: return {}
    load = np.asarray(it_series)/max(cap_it, 1e-9); tn = np.asarray(tnode_series)
    r = dict(mode=th.cooling_mode, mode_cn=md["cn"], family=md["family"], liquid_frac=round(liquid_fraction(th), 2))
    if md["family"] == "liquid" and th.cooling_mode != "hybrid":
        chip = tn + md["chip_rise_k"]*load
        r.update(coolant_supply_max_c=round(float(tn.max()), 2), coolant_limit_c=md["coolant_limit_c"], coolant_margin_k=round(float(md["coolant_limit_c"] - tn.max()), 2),
                 chip_proxy_max_c=round(float(chip.max()), 1), chip_limit_c=85.0, chip_margin_k=round(float(85.0 - chip.max()), 1),
                 coolant_return_c=round(float(tn.max() + (md["return_c"] - md["supply_c"])), 1))
    else:
        r.update(inlet_max_c=round(float(tn.max()), 2), ashrae_class="A1" if tn.max() <= 32 else ("A2" if tn.max() <= 35 else "超 A2"))
    return r
