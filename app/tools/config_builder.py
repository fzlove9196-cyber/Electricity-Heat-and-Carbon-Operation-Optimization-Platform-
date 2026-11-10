"""配置构建器：从模板（空白等值网络）或预设出发，用一个简洁的 spec 字典生成完整 Scenario；带校验。
spec 字段（全部可选，缺省见 TEMPLATE）：
  name, base("blank"|预设名), climate("zhongwei"), season("winter"|"summer"|"heatwave"), rh,
  dcs:[{name, cap_it_mw, racks, utilization, flex_share, cooling_mode, liquid_frac, air_residual_mode, chiller_ratio,
        tes_type("water"|"ice"), tes_mwh, tes_mw, hp_mw, hp_type("standard"|"high_temp"), waste_heat_c}],
  battery:{power_mw, energy_mwh, eta, soc_min, soc_max}, heat_storage:{mwh, mw},
  virtual:{precool, tes, heat, dr}（虚拟储冷/蓄冷/余热/DR 杠杆开关）,
  sources:{wind_mw, pv_mw, thermal_mw, hydro_mw, hydro_mwh_day, gas_chp_mw, grid_import_mw, grid_export_mw, ppa_price},
  heat:{enabled, terminal_type, pipe_length_km, pipe_dt_k_per_km, design_load_mw, price_cny_gj, booster, ref_heat_price_cny_gj, hp_max_out_c, eta},
  carbon_price, carbon_weight"""
from __future__ import annotations
import copy, json, os
import numpy as np
from ..scenario import Scenario, DCThermal, HeatNetwork, Storage, PV, DataCenter, CustomNetwork, NetBus, NetLine, NetTrafo, NetExtGrid, NetGen, load_preset
from . import cooling as CL
from .heat_grade import TERMINALS

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TEMPLATE = dict(name="自定义配置", base="blank", climate="zhongwei", season="winter", rh=0.35,
    dcs=[dict(name="DC1", cap_it_mw=50.0, racks=None, utilization=0.7, flex_share=0.3, cooling_mode="air_chw", liquid_frac=None,
              air_residual_mode="air_iec", chiller_ratio=None, tes_type="water", tes_mwh=0.0, tes_mw=0.0, hp_mw=15.0, hp_type="standard", waste_heat_c=None)],
    battery=dict(power_mw=0.0, energy_mwh=0.0, eta=0.95, soc_min=0.1, soc_max=0.95),
    heat_storage=dict(mwh=0.0, mw=0.0), virtual=dict(precool=True, tes=True, heat=True, dr=True),
    sources=dict(wind_mw=100.0, pv_mw=100.0, thermal_mw=0.0, hydro_mw=0.0, hydro_mwh_day=None, gas_chp_mw=0.0, grid_import_mw=1000.0, grid_export_mw=0.0, ppa_price=None),
    heat=dict(enabled=True, terminal_type="radiator", pipe_length_km=5.0, pipe_dt_k_per_km=0.3, design_load_mw=None, price_cny_gj=33.0, booster="gas_boiler",
              ref_heat_price_cny_gj=45.0, hp_max_out_c=80.0, eta=0.5),
    carbon_price=80.0, carbon_weight=1.0)
HP_TYPES = {"standard": 80.0, "high_temp": 95.0}

def _clim():
    import sys; sys.path.insert(0, os.path.join(ROOT, "cases", "common"))
    from thermal_params import CLIMATE
    zw = json.load(open(os.path.join(ROOT, "cases", "zhongwei", "zhongwei_winter_coupled_heat.json")))
    zs = json.load(open(os.path.join(ROOT, "cases", "zhongwei", "zhongwei_summer_coupled.json")))
    return CLIMATE, zw, zs

def merge(base, over):
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict): out[k] = merge(out[k], v)
        else: out[k] = copy.deepcopy(v)
    return out

def full_spec(spec):
    s = merge(TEMPLATE, {k: v for k, v in (spec or {}).items() if k != "dcs"})
    dcs = (spec or {}).get("dcs") or TEMPLATE["dcs"]
    s["dcs"] = [merge(TEMPLATE["dcs"][0], {**d, "name": d.get("name") or f"DC{i+1}"}) for i, d in enumerate(dcs)]
    return s

def validate_spec(spec):
    s = full_spec(spec); E, W = [], []
    if not s["dcs"]: E.append("至少需要 1 个数据中心")
    names = [d["name"] for d in s["dcs"]]
    if len(set(names)) != len(names): E.append("数据中心名称重复")
    for d in s["dcs"]:
        n = d["name"]
        if not d["cap_it_mw"] or d["cap_it_mw"] <= 0: E.append(f"{n}: IT 容量必须 > 0")
        if not 0 < d["utilization"] <= 1: E.append(f"{n}: 利用率应在 (0,1]")
        if not 0 <= d["flex_share"] <= 0.9: E.append(f"{n}: 可调(批处理)比例应在 [0,0.9]")
        if d["cooling_mode"] not in CL.MODES: E.append(f"{n}: 散热方式 {d['cooling_mode']} 不在库中 {list(CL.MODES)}")
        if d.get("liquid_frac") is not None and not 0 <= d["liquid_frac"] <= 1: E.append(f"{n}: 液冷比例应在 [0,1]")
        if d["tes_mwh"] < 0 or d["tes_mw"] < 0 or d["hp_mw"] < 0: E.append(f"{n}: 蓄冷/热泵容量不能为负")
        if d["tes_mwh"] > 0 and d["tes_mw"] <= 0: E.append(f"{n}: 蓄冷罐容量>0 时功率必须 >0")
        if d["hp_type"] not in HP_TYPES: E.append(f"{n}: 热泵类型应为 {list(HP_TYPES)}")
        if d["racks"]:
            dens = d["cap_it_mw"]*1000/d["racks"]
            if CL.MODES.get(d["cooling_mode"], {}).get("family") == "air" and dens > 25: W.append(f"{n}: 单柜 {dens:.0f} kW 超过风冷常规上限(~20-25 kW)，建议液冷")
    b = s["battery"]
    if b["energy_mwh"] > 0 and b["power_mw"] <= 0: E.append("储能容量>0 时功率必须 >0")
    if not 0 <= b["soc_min"] < b["soc_max"] <= 1: E.append("储能 SOC 上下限不合理")
    if not 0.5 <= b["eta"] <= 1: E.append("储能效率应在 [0.5,1]")
    src = s["sources"]
    if any((src.get(k) or 0) < 0 for k in ("wind_mw", "pv_mw", "thermal_mw", "hydro_mw", "gas_chp_mw", "grid_import_mw")): E.append("电源容量不能为负")
    peak = sum(d["cap_it_mw"]*1.5 for d in s["dcs"])
    firm = (src["grid_import_mw"] or 0) + (src["thermal_mw"] or 0) + (src["hydro_mw"] or 0) + (src["gas_chp_mw"] or 0) + b["power_mw"]
    if firm < peak: W.append(f"可靠电源(外网+火/水/气+储能 {firm:.0f} MW) < 数据中心峰值估计 {peak:.0f} MW：夜间无风时可能失负荷/不可行")
    h = s["heat"]
    if h["enabled"]:
        if h["terminal_type"] not in TERMINALS: E.append(f"供热末端应为 {list(TERMINALS)}")
        if h["pipe_length_km"] < 0: E.append("管线长度不能为负")
        if not any(d["hp_mw"] > 0 for d in s["dcs"]): W.append("启用供热但没有任何 DC 配置热泵/换热器 (hp_mw=0)")
        if h["booster"] not in ("gas_boiler", "electric", "none"): E.append("booster 应为 gas_boiler/electric/none")
    if s["season"] not in ("winter", "summer", "heatwave"): E.append("season 应为 winter/summer/heatwave")
    return dict(ok=not E, errors=E, warnings=W, spec=s)

def _shape(h):
    return 1 + 0.08*np.cos(2*np.pi*(np.arange(24) - 20)/24)

def build(spec) -> Scenario:
    V = validate_spec(spec)
    if not V["ok"]: raise ValueError("配置校验失败：" + "；".join(V["errors"]))
    s = V["spec"]; CLIMATE, zw, zs = _clim()
    ref = zw if s["season"] == "winter" else zs
    tout = CLIMATE[f"{s['climate']}_{s['season']}"] if f"{s['climate']}_{s['season']}" in CLIMATE else CLIMATE["zhongwei_winter"]
    wind_prof = next(p["profile"] for p in ref["pv"] if p["bus"] == 7); pv_prof = next(p["profile"] for p in ref["pv"] if p["bus"] == 4)
    src = s["sources"]
    nw = CustomNetwork(buses=[NetBus(name="电网接入330kV", vn_kv=330), NetBus(name="数据中心110kV", vn_kv=110), NetBus(name="新能源汇集110kV", vn_kv=110), NetBus(name="常规电源110kV", vn_kv=110)],
                       trafos=[NetTrafo(name="主变", hv_bus=0, lv_bus=1, sn_mva=max(500.0, 2*(src["grid_import_mw"] or 0)), parallel=1)],
                       lines=[NetLine(name="新能源送出", from_bus=2, to_bus=1, length_km=10, rating_mva=max(300.0, 1.2*((src["wind_mw"] or 0) + (src["pv_mw"] or 0)))),
                              NetLine(name="电源送出", from_bus=3, to_bus=1, length_km=10, rating_mva=max(300.0, 1.2*((src["thermal_mw"] or 0) + (src["hydro_mw"] or 0) + (src["gas_chp_mw"] or 0))))],
                       ext_grids=[NetExtGrid(bus=0, name="外部电网", import_max_mw=float(src["grid_import_mw"] or 0), price_cny_kwh=zw["price_cny_kwh"],
                                             export_max_mw=float(src["grid_export_mw"] or 0), export_price_cny_kwh=[round(p*0.75, 4) for p in zw["price_cny_kwh"]])],
                       note="配置构建器生成的 4 母线等值网络（【假设】）")
    nd = len(s["dcs"])
    for i, d in enumerate(s["dcs"]):   # 每个数据中心一条 110kV 母线（经专线接入数据中心汇集站）
        nw.buses.append(NetBus(name=f"{d['name']} 110kV", vn_kv=110))
        nw.lines.append(NetLine(name=f"{d['name']} 专线", from_bus=1, to_bus=4 + i, length_km=3, rating_mva=max(150.0, 2.0*d["cap_it_mw"]), parallel=2))
    if src["thermal_mw"]: nw.gens.append(NetGen(name="燃煤机组", bus=3, kind="thermal", pmax_mw=src["thermal_mw"], pmin_mw=0.3*src["thermal_mw"], cost_cny_mwh=330, emission_t_mwh=0.85))
    if src["hydro_mw"]: nw.gens.append(NetGen(name="水电", bus=3, kind="hydro", pmax_mw=src["hydro_mw"], cost_cny_mwh=150, emission_t_mwh=0.0, energy_mwh_day=src.get("hydro_mwh_day")))
    if src["gas_chp_mw"]: nw.gens.append(NetGen(name="燃气热电联产(电侧)", bus=3, kind="gas", pmax_mw=src["gas_chp_mw"], cost_cny_mwh=550, emission_t_mwh=0.40))
    pv = []
    if src["wind_mw"]: pv.append(PV(bus=2, cap_mw=src["wind_mw"], profile=wind_prof, kind="wind", name="风电", ppa_price_cny_kwh=src.get("ppa_price"), ppa_take_or_pay=False))
    if src["pv_mw"]: pv.append(PV(bus=2, cap_mw=src["pv_mw"], profile=pv_prof, kind="pv", name="光伏", ppa_price_cny_kwh=src.get("ppa_price"), ppa_take_or_pay=False))
    import sys; sys.path.insert(0, os.path.join(ROOT, "cases", "common"))
    from thermal_params import thermal_for
    dcs = []
    for d in s["dcs"]:
        cap = float(d["cap_it_mw"]); avg = cap*d["utilization"]
        inter = [round(float(x), 3) for x in avg*(1 - d["flex_share"])*_shape(0)]
        md = CL.MODES[d["cooling_mode"]]
        cr = d["chiller_ratio"] if d["chiller_ratio"] is not None else (1.3 if md["family"] == "air" else 0.6)
        th = DCThermal(**thermal_for(cap, units=5, cool_ratio=cr))
        th.air_residual_mode = d["air_residual_mode"]
        CL.apply_mode(th, d["cooling_mode"], d.get("liquid_frac"), cap_it=cap)
        th.tes_mwh_th = float(d["tes_mwh"]); th.tes_p_mw_th = float(d["tes_mw"])
        th.tes_loss_h = 0.005 if d["tes_type"] == "water" else 0.01
        th.hp_cap_mw_th = float(d["hp_mw"]); th.racks = d.get("racks"); th.utilization = d["utilization"]
        if d.get("waste_heat_c") is not None: th.waste_heat_c = float(d["waste_heat_c"])
        if th.tes_mwh_th > 0 and d["tes_type"] == "ice": th.cop_min = min(th.cop_min, 2.5)
        dcs.append(DataCenter(name=d["name"], bus=4 + len(dcs), cap_it_mw=cap, pue=1.25, interactive_mw=inter, batch_mwh=round(avg*d["flex_share"]*24, 2), thermal=th))
    b = s["battery"]
    sto = [Storage(name="ESS", bus=1, energy_mwh=b["energy_mwh"], power_mw=b["power_mw"], eta_ch=b["eta"], eta_dis=b["eta"], soc_min=b["soc_min"], soc_max=b["soc_max"], soc0=0.5)] if b["energy_mwh"] > 0 else []
    h = s["heat"]; hn = None
    hpd = [d for d in s["dcs"] if d["hp_mw"] > 0]
    if h["enabled"] and hpd:
        hs = s["heat_storage"]; dl = h["design_load_mw"] if h["design_load_mw"] else 1.2*sum(d["hp_mw"] for d in hpd)
        hn = HeatNetwork(name=f"区域供热（{TERMINALS[h['terminal_type']]['cn']}，{h['pipe_length_km']} km）", dcs=[d["name"] for d in hpd],
                         price_cny_mwh_th=round(h["price_cny_gj"]*3.6, 1), storage_mwh_th=hs["mwh"], storage_p_mw_th=hs["mw"], pipe_loss=0.02,
                         terminal_type=h["terminal_type"], pipe_length_km=h["pipe_length_km"], pipe_dt_k_per_km=h["pipe_dt_k_per_km"],
                         booster=h["booster"], ref_heat_price_cny_gj=h["ref_heat_price_cny_gj"], demand_mode="degree_hour", design_load_mw_th=dl,
                         hp_max_out_c=max(h["hp_max_out_c"], max(HP_TYPES[d["hp_type"]] for d in hpd)), hp_eta_carnot=h["eta"],
                         t_out_design_c=-12.0 if s["climate"] == "zhongwei" else -10.0)
        if s["season"] != "winter": hn.dhw_share = 1.0; hn.design_load_mw_th = 0.15*dl   # 非采暖季仅生活热水
    sc = Scenario(name=s["name"], synthetic=True, note=f"配置构建器生成：{s['name']}（{s['climate']}·{s['season']}）。拓扑/价格/出力曲线取自中卫案例，其余为【假设】。",
                  network_case="custom", network=nw, price_kind="ningxia_tou_110kV", price_cny_kwh=zw["price_cny_kwh"], grid_markup_cny_mwh=0.0,
                  data_centers=dcs, storage=sto, pv=pv, mig_max_mw=20.0, pv_curtail_penalty=50.0,
                  carbon_profiles={"northwest": zw["carbon_profiles"]["northwest"]}, bus_region={i: "northwest" for i in range(4 + nd)},
                  carbon_price_cny_t=s["carbon_price"], carbon_weight=s["carbon_weight"], thermal_mode="coupled",
                  outdoor_temp_c=list(tout), outdoor_rh=float(s.get("rh") or 0.35), heat_network=hn,
                  sources={"散热方式库": "app/tools/cooling.py（ASHRAE TC9.9 / ODCC 液冷白皮书 / TGG WUE）", "余热品位": "app/tools/heat_grade.py（卡诺效率法 / CJJ 34）",
                           "配置": json.dumps(s, ensure_ascii=False)[:2000]})
    L = {"b0": [0.88, 0.12], "b1": [0.5, 0.3], "b2": [0.12, 0.3], "b3": [0.5, 0.06]}
    for i in range(nd): L[f"b{4 + i}"] = [0.15 + 0.7*(i + 0.5)/nd, 0.58]
    sc.layout = L
    return sc

def levers(spec):
    return dict(full_spec(spec)["virtual"])

def set_path(spec, path, value):
    """点路径赋值：'dcs.*.cooling_mode'、'dcs.0.hp_mw'、'battery.energy_mwh'、'heat.pipe_length_km'。"""
    s = full_spec(spec); keys = path.split(".")
    def rec(o, ks):
        k = ks[0]
        if len(ks) == 1:
            if isinstance(o, list): 
                for x in (o if k == "*" else [o[int(k)]]): pass
            o[k if not isinstance(o, list) else int(k)] = value; return
        if isinstance(o, list):
            for x in (o if k == "*" else [o[int(k)]]): rec(x, ks[1:])
        else: rec(o[k], ks[1:])
    rec(s, keys); return s
