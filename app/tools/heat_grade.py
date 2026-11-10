"""余热品位与供热末端：热泵 COP（卡诺效率法，逐时预计算）、直接换热判据、管网温降/热损、末端供水温度要求（质调节曲线）、
调峰补热比例，以及“余热供暖可行性”判定（技术/经济/碳）。全部为逐时参数 → 进入 LP 仍为线性。"""
from __future__ import annotations
import numpy as np

TERMINALS = {   # (要求供水 min@T_out≥15°C, max@设计温度, 回水)
    "floor": dict(cn="地暖", t_min=35.0, t_max=45.0, t_ret=30.0),
    "fcu": dict(cn="风机盘管", t_min=45.0, t_max=55.0, t_ret=40.0),
    "radiator": dict(cn="散热器", t_min=60.0, t_max=75.0, t_ret=50.0),
    "primary": dict(cn="城市一次网", t_min=70.0, t_max=110.0, t_ret=50.0),
}

def terminal(hn):
    T = TERMINALS.get(hn.terminal_type or "", TERMINALS["radiator"])
    return dict(cn=T["cn"], t_min=hn.t_supply_min_c if hn.t_supply_min_c is not None else T["t_min"],
                t_max=hn.t_supply_max_c if hn.t_supply_max_c is not None else T["t_max"],
                t_ret=hn.t_return_c if hn.t_return_c is not None else T["t_ret"])

def supply_curve(hn, tout):
    """质调节：室外越冷要求供水越高（线性：T_out≥15°C→t_min；T_out≤设计温度→t_max）。"""
    T = terminal(hn); x = np.clip((15.0 - np.asarray(tout, float))/(15.0 - hn.t_out_design_c), 0, 1)
    return T["t_min"] + (T["t_max"] - T["t_min"])*x

def degree_hour_demand(hn, tout):
    x = np.clip((18.0 - np.asarray(tout, float))/(18.0 - hn.t_out_design_c), 0, None)
    return hn.design_load_mw_th*(hn.dhw_share + (1 - hn.dhw_share)*x)

def pipe(hn):
    return hn.pipe_length_km*hn.pipe_dt_k_per_km, min(0.6, hn.pipe_loss + hn.pipe_loss_per_km*hn.pipe_length_km)

def hp_cop(eta, t_sink, t_evap, lo=1.3, hi=9.0):
    ts = np.asarray(t_sink, float) + 273.15; te = np.asarray(t_evap, float) + 273.15
    return np.clip(eta*ts/np.maximum(ts - te, 3.0), lo, hi)

def hourly(hn, t_src, tout):
    """逐时：要求末端供水 T_req、站出口要求 T_plant、可达出口温度、方式(direct/hp/hp+booster)、COP、补热比例 f、末端温度裕度。"""
    tout = np.asarray(tout, float); T = terminal(hn); dT, loss = pipe(hn)
    treq = supply_curve(hn, tout); tplant = treq + dT
    direct = (t_src - hn.hx_approach_k) >= tplant
    t_hp_out = np.minimum(tplant, hn.hp_max_out_c)
    cop = hp_cop(hn.hp_eta_carnot, t_hp_out, t_src - hn.hp_evap_approach_k)
    cop = np.where(direct, 40.0, cop)          # 直接换热：仅循环泵电耗（≈1/40）
    ach = np.where(direct, t_src - hn.hx_approach_k, hn.hp_max_out_c)   # 不补热时站出口可达温度
    f = np.where(direct, 0.0, np.clip((tplant - hn.hp_max_out_c)/np.maximum(tplant - T["t_ret"], 1e-6), 0, 0.95))
    if hn.booster == "none": f = np.zeros_like(f)
    margin = ach - dT - treq                     # 无补热时末端供水温度裕度
    mode = np.where(direct, "direct", np.where(f > 1e-9, "hp+booster", "hp"))
    return dict(t_req=treq, t_plant=tplant, t_ach=ach, cop=cop, f_boost=f, margin=margin, mode=mode, dT_pipe=dT, loss=loss,
                t_ret=T["t_ret"], t_deliver=np.minimum(ach, tplant) - dT + np.where(f > 0, tplant - ach, 0), terminal_cn=T["cn"])

def verdict(hn, H, delivered_mwh, hp_elec_mwh, hp_elec_cost, boost_mwh, boost_cost, boost_ef_t, elec_ci_avg, hp_heat_mwh):
    """余热供暖可行性：技术/经济/碳。"""
    gj = max(delivered_mwh*3.6, 1e-9)
    heat_cost = (hp_elec_cost + boost_cost)/gj
    tech_ok_nb = bool((H["margin"] >= -1e-6).all())
    tech_ok = tech_ok_nb or hn.booster != "none"
    car_off = hn.boiler_ef_t_mwh_th*delivered_mwh; car_hp = hp_elec_mwh*elec_ci_avg; car_b = boost_ef_t
    net = car_off - car_hp - car_b
    econ_ok = heat_cost <= hn.ref_heat_price_cny_gj
    lvl = "可行" if (tech_ok_nb and econ_ok and net > 0) else ("有条件可行" if (tech_ok and net > 0) else "不可行")
    why = []
    fb = 100*float(H["f_boost"].max())
    tip = "无需补热" if tech_ok_nb else (f"需调峰补热（峰值时段 {fb:.0f}% 热量由{'燃气锅炉' if hn.booster == 'gas_boiler' else '电加热'}补足）" if hn.booster != "none" else "温度不足且无补热 → 末端不达标")
    why.append(f"技术：无补热时末端供水最低裕度 {float(H['margin'].min()):+.1f} K，{tip}")
    why.append(f"经济：供热成本 {heat_cost:.1f} 元/GJ vs 对标 {hn.ref_heat_price_cny_gj} 元/GJ")
    why.append(f"碳：净减排 {net:.1f} tCO2/日（替代锅炉 {car_off:.1f} − 热泵用电 {car_hp:.1f} − 补热 {car_b:.1f}）")
    return dict(level=lvl, technical_ok_without_booster=tech_ok_nb, technical_ok=tech_ok, economic_ok=bool(econ_ok), carbon_ok=bool(net > 0),
                heat_cost_cny_gj=round(heat_cost, 1), ref_heat_price_cny_gj=hn.ref_heat_price_cny_gj, net_carbon_t=round(net, 2),
                carbon_offset_t=round(car_off, 2), carbon_hp_t=round(car_hp, 2), carbon_booster_t=round(car_b, 2),
                min_margin_k=round(float(H["margin"].min()), 2), mode_hours={m: int((H["mode"] == m).sum()) for m in ("direct", "hp", "hp+booster")},
                cop_min=round(float(H["cop"].min()), 2), cop_max=round(float(H["cop"].max()), 2), boost_mwh=round(boost_mwh, 2),
                t_req_max=round(float(H["t_req"].max()), 1), t_plant_max=round(float(H["t_plant"].max()), 1), dT_pipe_k=round(H["dT_pipe"], 2), pipe_loss=round(H["loss"], 3),
                terminal=H["terminal_cn"], reasons=why)
