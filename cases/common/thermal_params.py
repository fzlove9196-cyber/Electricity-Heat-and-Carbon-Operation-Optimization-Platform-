"""算-电-热-碳耦合参数生成（典型日室外温度/供热负荷/DR 事件）。标注：除注明来源外均为【假设】值。"""
import numpy as np
H = np.arange(24)

def diurnal(tmin, tmax, peak_h=15):
    """正弦日变化：最高温在 peak_h 时，最低温在 peak_h-12（近似；【假设】）"""
    return [round(float((tmin + tmax)/2 + (tmax - tmin)/2*np.cos(2*np.pi*(h - peak_h)/24)), 2) for h in H]

# 中卫（沙坡头区）气候：7 月平均最高≈30°C/最低≈17°C；1 月平均最高≈1°C/最低≈-12°C（中国气象局气候平均值量级，取整【假设】）
CLIMATE = {
    "zhongwei_summer": diurnal(17, 30), "zhongwei_heatwave": diurnal(25, 39), "zhongwei_winter": diurnal(-12, 1),
    "shanghai_summer": diurnal(26, 34), "shanghai_heatwave": diurnal(29, 38), "shanghai_winter": diurnal(2, 9),
    "hohhot_winter": diurnal(-19, -6), "hohhot_summer": diurnal(17, 29), "beijing_winter": diurnal(-8, 3),
}

def thermal_for(cap_it, tes_mwh=0.0, tes_p=0.0, hp_cap=0.0, units=5, cool_ratio=1.30, free_ratio=0.9):
    """按 IT 规模缩放的热参数（量级参考 ASHRAE TC9.9 / 文献，【假设】）"""
    return dict(c_air_mwh_k=round(0.01*cap_it, 3), c_mass_mwh_k=round(0.08*cap_it, 3), ua_am_mw_k=round(0.05*cap_it, 3),
                ua_env_mw_k=round(0.002*cap_it, 4), t0_c=24.0, t_min_c=18.0, t_rec_max_c=27.0, t_allow_max_c=32.0, ramp_max_k_h=5.0,
                chiller_cap_mw_th=round(cool_ratio*cap_it, 1), chiller_units=units, redundancy_n1=True, crah_cap_mw_th=round(1.25*cap_it, 1),
                cop_ref=5.5, cop_t_ref_c=25.0, cop_slope_per_k=0.12, cop_min=2.5, cop_max=8.0, tower_pump_kw_per_kw=0.025,
                free_cap_mw_th=round(free_ratio*cap_it, 1), free_t_full_c=8.0, free_t_zero_c=18.0, free_cop=20.0, other_frac=0.05,
                tes_mwh_th=tes_mwh, tes_p_mw_th=tes_p, tes_loss_h=0.005, tes_soc0=0.5, hp_cap_mw_th=hp_cap, hp_cop=4.0, hr_max_frac=0.6)

def heat_demand(peak, base_share=0.6):
    """区域供热逐时可接纳负荷：夜间/清晨高、午后低（【假设】）"""
    sh = base_share + (1 - base_share)*(0.5 + 0.5*np.cos(2*np.pi*(H - 6)/24))
    return [round(float(peak*x), 2) for x in sh]
