"""Explicit physical hours vs interval indices; power is MW, integrated amounts use dt."""
import copy

def boundary(sc, hour):
    value=float(hour)/sc.dt_hours
    if abs(value-round(value))>1e-8: raise ValueError(f"时刻 {hour}h 必须对齐 dt={sc.dt_hours}h")
    return int(round(value))

def window(sc, item):
    return range(boundary(sc,item.release),boundary(sc,item.deadline))

def event_steps(sc,event):
    return range(boundary(sc,event.start),boundary(sc,event.end))

def require_hourly(sc,path):
    if sc.dt_hours!=1 or any(j.execution_mode!="energy" for j in sc.jobs):
        raise ValueError(f"{path} 尚不支持15min/整数连续任务；不能默默当作1h能量任务。请使用常规日调度/版本化任务。")

def resample_hourly(raw):
    """Explicit public conversion: rates are held, energy/deadline/physical hours unchanged."""
    if raw.get('dt_hours',1)!=1 or raw.get('hours',24)!=24: raise ValueError('仅显式转换24h/1h到15min；禁止重复转换')
    d=copy.deepcopy(raw)
    keys={'price_cny_kwh','export_price_cny_kwh','interactive_mw','profile','outdoor_temp_c','demand_mw_th','baseline_mw','lifecycle_tco2e_mwh_profile'}
    profiles={'carbon_profiles','carbon_marginal_profiles','outdoor_temp_profiles','outdoor_rh_profiles'}
    def walk(o):
        if isinstance(o,dict):
            for k,v in list(o.items()):
                if k in keys and isinstance(v,list):
                    if len(v)!=24: raise ValueError(k+' 需24点才能sample-and-hold')
                    o[k]=[x for x in v for _ in range(4)]
                elif k in profiles:
                    for region,vals in v.items():
                        if len(vals)!=24: raise ValueError(k+' 需24点')
                        v[region]=[x for x in vals for _ in range(4)]
                else: walk(v)
        elif isinstance(o,list):
            for v in o: walk(v)
    walk(d);d['dt_hours']=.25
    d.setdefault('sources',{})['时间步转换']='用户显式sample-and-hold：MW/价格/强度保持；MWh、物理小时截止期不变；策略最优值不保证与1h相同'
    return d
