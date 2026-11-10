"""Explicit annual CFE procurement/dispatch LP, separate from the 24h Scenario engine.
Currency is declared (author data EUR), capacity costs annualized and charged once.
Grid CFE is exogenous; this is NOT endogenous ISO/LMCE or GPU/job scheduling.
"""
from __future__ import annotations
from .solver_execution import serialized_pyomo, checked_solve
from typing import Literal
from datetime import datetime, timedelta
import calendar, math, hashlib, json, time, io, csv, zipfile
from pydantic import BaseModel, ConfigDict, Field, model_validator
import pyomo.environ as pyo

class Strict(BaseModel):
    model_config=ConfigDict(extra='forbid',allow_inf_nan=False)
class Resource(Strict):
    id:str
    technology:Literal['wind','solar']
    region:str
    additional:bool=True
    availability:list[float]
    capital_per_mw_year:float=Field(ge=0)
    marginal_per_mwh:float=Field(0,ge=0)
    max_mw:float|None=Field(None,ge=0)
class Battery(Strict):
    capital_power_per_mw_year:float=Field(ge=0)
    capital_energy_per_mwh_year:float=Field(ge=0)
    eta_charge:float=Field(.95,gt=0,le=1)
    eta_discharge:float=Field(.95,gt=0,le=1)
    loss_per_hour:float=Field(0,ge=0,lt=1)
    discharge_cost_internal_per_mwh:float=Field(0,ge=0)
    max_power_mw:float|None=Field(None,ge=0)
    max_energy_mwh:float|None=Field(None,ge=0)
class Site(Strict):
    id:str
    region:str
    load_mw:list[float]
    generators:list[Resource]
    battery:Battery
    grid_price_per_mwh:list[float]
    grid_cfe:list[float]
    import_limit_mw:float=Field(1e6,ge=0)
class CfeModel(Strict):
    model_kind:Literal['opt_cfe']='opt_cfe'
    name:str='年度CFE采购与运行'
    currency:Literal['EUR','CNY','USD']='EUR'
    planning_year:int=2025
    weather_year:int=2013
    timezone:Literal['UTC']='UTC'
    start:str='2013-01-01T00:00:00+00:00'
    dt_hours:Literal[1.0]=1.0
    horizon_mode:Literal['year','benchmark']='year'
    matching:Literal['paper_cfe_score','hourly_cfe_floor','annual_res_share']='paper_cfe_score'
    target:float=Field(1,ge=0,le=1)
    flexibility:float=Field(0,ge=0,le=1)
    spatial_shifting:bool=False
    temporal_shifting:bool=False
    spatial_fee_per_mwh:float=Field(1e-5,ge=0)
    temporal_fee_per_mwh:float=Field(1e-5,ge=0)
    max_excess_share:float=Field(0,ge=0,le=1)
    storage_boundary:Literal['cyclic','empty']='cyclic'
    sites:list[Site]
    source:dict=Field(default_factory=dict)
    @property
    def n_steps(self):return len(self.sites[0].load_mw)
    @model_validator(mode='after')
    def valid(self):
        if not 1<=len(self.sites)<=8:raise ValueError('opt-cfe当前支持1~8站；不缩减或截断原输入')
        if len({x.id for x in self.sites})!=len(self.sites):raise ValueError('站点id重复')
        try:start=datetime.fromisoformat(self.start)
        except ValueError:raise ValueError('CFE start需ISO时间')
        if start.utcoffset() is None or start.utcoffset().total_seconds()!=0 or start.year!=self.weather_year or start.minute or start.second or start.microsecond:raise ValueError('CFE时间轴须明确UTC整点且weather_year与start一致')
        n=self.n_steps
        if self.horizon_mode=='year':
            expected=8784 if calendar.isleap(self.weather_year) else 8760
            if n!=expected or (start.month,start.day,start.hour)!=(1,1,0):raise ValueError(f'全年CFE须完整UTC年{expected}点/1h从1月1日零点开始，不能填充/截断/分日重设容量')
        elif not 1<=n<=168:raise ValueError('benchmark只允许1~168小时，必须标注非全年解析控制')
        for s in self.sites:
            if not s.generators or len({r.id for r in s.generators})!=len(s.generators):raise ValueError('每站发电资产须存在且id唯一')
            for label,values in [('load',s.load_mw),('grid_price',s.grid_price_per_mwh),('grid_cfe',s.grid_cfe)]+[(r.id,r.availability) for r in s.generators]:
                if len(values)!=n or any(not math.isfinite(x) for x in values):raise ValueError(f'{s.id}/{label}点数必须{n}且有限')
            if min(s.load_mw)<0 or max(s.load_mw)>1e4 or sum(s.load_mw)<=0:raise ValueError('负荷须非负、各站总量正且单站峰值不超过当前明确上限10000MW')
            if min(s.grid_price_per_mwh)<0:raise ValueError('当前CFE模式不支持负电价套利；请明确另建模型，禁止隐式放松')
            if min(s.grid_cfe)<0 or max(s.grid_cfe)>1:raise ValueError('grid_cfe须0~1，不能把排放强度误作清洁份额')
            for r in s.generators:
                if min(r.availability)<0 or max(r.availability)>1:raise ValueError('风光availability须0~1')
                if r.region!=s.region or not r.additional:raise ValueError('本模式采购资产必须新增且处于用电站点同一竞价区；跨区/存量证书不能冒充本地新增CFE')
        return self

def check_axis(a,sc):
    from .foundation.service import required
    if set(a)!={'location','year','timezone','start','step_minutes','length'}:raise ValueError('CFE时间轴字段不完整或有未知字段')
    required(a,['location','year','timezone','start','step_minutes','length'])
    if a['timezone']!='UTC' or int(a['year'])!=sc.weather_year or a['step_minutes']!=60 or a['length']!=sc.n_steps or datetime.fromisoformat(a['start'])!=datetime.fromisoformat(sc.start):raise ValueError('CFE完整输入与项目axis必须同一UTC起点/气象年/1h/长度；不支持隐式重采样或24h假冒8760')
    return a

@serialized_pyomo('annual_cfe')
def solve(raw,solver_cfg=None):
    sc=raw if isinstance(raw,CfeModel) else CfeModel.model_validate(raw);cfg=solver_cfg or {};started=time.monotonic();sites={s.id:s for s in sc.sites};I=list(sites);N=sc.n_steps;T=range(N);assets=[(s.id,r.id) for s in sc.sites for r in s.generators];R={(s.id,r.id):r for s in sc.sites for r in s.generators};edges=[(i,j) for i in I for j in I if i!=j] if sc.spatial_shifting else []
    m=pyo.ConcreteModel();m.cap=pyo.Var(assets,domain=pyo.NonNegativeReals);m.power=pyo.Var(I,domain=pyo.NonNegativeReals);m.energy=pyo.Var(I,domain=pyo.NonNegativeReals);m.gen=pyo.Var([(i,r,t) for i,r in assets for t in T],domain=pyo.NonNegativeReals)
    for name in ['actual','local_direct','local_charge','grid_direct','grid_charge','green_discharge','brown_discharge','green_soc','brown_soc','excess','defer','recover']:
        setattr(m,name,pyo.Var(I,T,domain=pyo.NonNegativeReals))
    m.flow=pyo.Var([(i,j,t) for i,j in edges for t in T],domain=pyo.NonNegativeReals,bounds=(0,1e6));c=m.constraints=pyo.ConstraintList()
    for i,r in assets:
        if R[i,r].max_mw is not None:m.cap[i,r].setub(R[i,r].max_mw)
    for i in I:
        s=sites[i];b=s.battery
        if b.max_power_mw is not None:m.power[i].setub(b.max_power_mw)
        if b.max_energy_mwh is not None:m.energy[i].setub(b.max_energy_mwh)
        for t in T:
            load=m.actual[i,t];g=sum(m.gen[i,r.id,t] for r in s.generators);imp=m.grid_direct[i,t]+m.grid_charge[i,t];ch=m.local_charge[i,t]+m.grid_charge[i,t];dis=m.green_discharge[i,t]+m.brown_discharge[i,t]
            sp=sum(m.flow[j,i,t]-m.flow[i,j,t] for j in I if j!=i) if edges else 0
            if not sc.temporal_shifting:m.defer[i,t].fix(0);m.recover[i,t].fix(0)
            else:m.defer[i,t].setub(1e6);m.recover[i,t].setub(1e6)
            c.add(load==s.load_mw[t]+sp+m.recover[i,t]-m.defer[i,t]);load.setlb((1-sc.flexibility)*s.load_mw[t]);load.setub((1+sc.flexibility)*s.load_mw[t])
            c.add(load==m.local_direct[i,t]+m.grid_direct[i,t]+dis);c.add(g==m.local_direct[i,t]+m.local_charge[i,t]+m.excess[i,t]);c.add(imp<=s.import_limit_mw)
            for r in s.generators:c.add(m.gen[i,r.id,t]<=r.availability[t]*m.cap[i,r.id])
            prev=(t-1)%N
            for cohort in ['green','brown']:
                state=getattr(m,cohort+'_soc');prev_state=state[i,prev] if t>0 or sc.storage_boundary=='cyclic' else 0
                q=(m.local_charge[i,t]+s.grid_cfe[t]*m.grid_charge[i,t]) if cohort=='green' else (1-s.grid_cfe[t])*m.grid_charge[i,t]
                c.add(state[i,t]==(1-b.loss_per_hour)*prev_state+b.eta_charge*q-getattr(m,cohort+'_discharge')[i,t]/b.eta_discharge)
                if t==N-1 and sc.storage_boundary=='empty':state[i,t].fix(0)
            c.add(ch<=m.power[i]);c.add(dis<=m.power[i]);c.add(m.green_soc[i,t]+m.brown_soc[i,t]<=m.energy[i])
            # Algebraic tightening of perfect matching; not a relaxation or a shifted target.
            if sc.matching!='annual_res_share' and sc.target==1 and s.grid_cfe[t]<1:m.grid_direct[i,t].fix(0);m.grid_charge[i,t].fix(0)
            credit=load-(1-s.grid_cfe[t])*imp
            if sc.matching=='hourly_cfe_floor':c.add(credit>=sc.target*load)
        if sc.temporal_shifting:
            for d in range(0,N,24):c.add(sum(m.recover[i,t]-m.defer[i,t] for t in range(d,min(N,d+24)))==0)
        actual=sum(m.actual[i,t] for t in T)
        if sc.matching=='paper_cfe_score':c.add(sum(m.actual[i,t]-(1-s.grid_cfe[t])*(m.grid_direct[i,t]+m.grid_charge[i,t]) for t in T)>=sc.target*actual)
        elif sc.matching=='annual_res_share':c.add(sum(m.gen[i,r.id,t] for r in s.generators for t in T)==sc.target*actual)
        c.add(sum(m.excess[i,t] for t in T)<=sc.max_excess_share*sum(s.load_mw))
    capital=sum(R[i,r].capital_per_mw_year*m.cap[i,r] for i,r in assets)+sum(sites[i].battery.capital_power_per_mw_year*m.power[i]+sites[i].battery.capital_energy_per_mwh_year*m.energy[i] for i in I)
    generation=sum(R[i,r].marginal_per_mwh*m.gen[i,r,t] for i,r in assets for t in T)
    imports=sum(sites[i].grid_price_per_mwh[t]*(m.grid_direct[i,t]+m.grid_charge[i,t]) for i in I for t in T)
    storage=sum(sites[i].battery.discharge_cost_internal_per_mwh/sites[i].battery.eta_discharge*(m.green_discharge[i,t]+m.brown_discharge[i,t]) for i in I for t in T)
    shift=sc.spatial_fee_per_mwh*sum(m.flow[i,j,t] for i,j in edges for t in T)+sc.temporal_fee_per_mwh*sum(m.defer[i,t]+m.recover[i,t] for i in I for t in T)
    m.objective=pyo.Objective(expr=capital+generation+imports+storage+shift)
    build_s=time.monotonic()-started;opt=pyo.SolverFactory('appsi_highs');opt.config.time_limit=float(cfg.get('time_limit_s',120));opt.highs_options.update(solver='simplex',simplex_strategy=1,parallel='off',primal_feasibility_tolerance=1e-7,dual_feasibility_tolerance=1e-7,ipm_optimality_tolerance=1e-9)
    solved=checked_solve(opt,m,load_solutions=False);status=str(solved.solver.termination_condition)
    if status!='optimal':raise RuntimeError(f'年度CFE LP求解未成功：{status}；不把超时/不可行写成最优。检查本地新增资源、逐时缺口、容量上限/储能来源及年度约束')
    opt.load_vars();v=lambda x:float(pyo.value(x));rows=[];caps=[];flows=[];days=[];residual=0.
    for i in I:
        s=sites[i];b=s.battery;previousG=v(m.green_soc[i,N-1]) if sc.storage_boundary=='cyclic' else 0.;previousB=v(m.brown_soc[i,N-1]) if sc.storage_boundary=='cyclic' else 0.;period=[]
        for t in T:
            load=v(m.actual[i,t]);rl=v(m.local_direct[i,t]);rc=v(m.local_charge[i,t]);gd=v(m.grid_direct[i,t]);gc=v(m.grid_charge[i,t]);dg=v(m.green_discharge[i,t]);db=v(m.brown_discharge[i,t]);sg=v(m.green_soc[i,t]);sb=v(m.brown_soc[i,t]);ex=v(m.excess[i,t]);generation_mw=sum(v(m.gen[i,r.id,t]) for r in s.generators);available=sum(r.availability[t]*v(m.cap[i,r.id]) for r in s.generators);sp=sum(v(m.flow[j,i,t])-v(m.flow[i,j,t]) for j in I if j!=i) if edges else 0.;defer=v(m.defer[i,t]);recover=v(m.recover[i,t]);clean=rl+s.grid_cfe[t]*gd+dg;credit=load-(1-s.grid_cfe[t])*(gd+gc)
            rG=sg-(1-b.loss_per_hour)*previousG-b.eta_charge*(rc+s.grid_cfe[t]*gc)+dg/b.eta_discharge;rB=sb-(1-b.loss_per_hour)*previousB-b.eta_charge*(1-s.grid_cfe[t])*gc+db/b.eta_discharge
            residual=max(residual,abs(load-rl-gd-dg-db),abs(generation_mw-rl-rc-ex),abs(rG),abs(rB),abs(load-s.load_mw[t]-sp-recover+defer),max(0,rc+gc-v(m.power[i])),max(0,dg+db-v(m.power[i])),max(0,sg+sb-v(m.energy[i])))
            row=dict(site=i,step=t,hour=t,duration_h=1.,timestamp=(datetime.fromisoformat(sc.start)+timedelta(hours=t)).isoformat(),requested_load_mw=s.load_mw[t],actual_load_mw=load,local_generation_mw=generation_mw,available_generation_mw=available,curtailed_before_generation_mw=available-generation_mw,excess_excluded_mw=ex,local_direct_mw=rl,local_charge_mw=rc,grid_direct_mw=gd,grid_charge_mw=gc,grid_import_mw=gd+gc,grid_cfe=s.grid_cfe[t],grid_price_per_mwh=s.grid_price_per_mwh[t],green_discharge_mw=dg,brown_discharge_mw=db,green_soc_mwh=sg,brown_soc_mwh=sb,previous_green_soc_mwh=previousG,previous_brown_soc_mwh=previousB,green_storage_residual_mwh=rG,brown_storage_residual_mwh=rB,physical_clean_served_mwh=clean,paper_cfe_credit_mwh=credit,unmatched_load_mwh=max(0,load-clean),spatial_net_in_mw=sp,temporal_defer_mw=defer,temporal_recover_mw=recover)
            for r in s.generators:row['gen_'+r.id+'_mw']=v(m.gen[i,r.id,t])
            rows.append(row);period.append(row);previousG,previousB=sg,sb
        actual=sum(r['actual_load_mw'] for r in period);gen=sum(r['local_generation_mw'] for r in period);clean=sum(r['physical_clean_served_mwh'] for r in period);score=sum(r['paper_cfe_credit_mwh'] for r in period)
        caps.append(dict(site=i,region=s.region,generators=[dict(id=r.id,technology=r.technology,region=r.region,additional=r.additional,capacity_mw=v(m.cap[i,r.id]),capital_per_mw_year=r.capital_per_mw_year,marginal_per_mwh=r.marginal_per_mwh) for r in s.generators],battery_power_mw=v(m.power[i]),battery_energy_mwh=v(m.energy[i]),battery=b.model_dump(),load_mwh=actual,annual_generation_share=gen/actual if actual>0 else None,physical_clean_fraction=clean/actual if actual>0 else None,paper_cfe_score=score/actual if actual>0 else None,max_hourly_unmatched_mwh=max(r['unmatched_load_mwh'] for r in period),max_hourly_paper_gap_mwh=max(max(0,r['actual_load_mw']-r['paper_cfe_credit_mwh']) for r in period),initial_green_soc_mwh=period[0]['previous_green_soc_mwh'],initial_brown_soc_mwh=period[0]['previous_brown_soc_mwh'],final_green_soc_mwh=previousG,final_brown_soc_mwh=previousB))
        for d in range(0,N,24):
            p=period[d:d+24];days.append(dict(site=i,day_index=d//24,requested_mwh=sum(r['requested_load_mw'] for r in p),actual_mwh=sum(r['actual_load_mw'] for r in p),temporal_conservation_residual_mwh=sum(r['temporal_recover_mw']-r['temporal_defer_mw'] for r in p)))
    for i,j in edges:
        for t in T:
            q=v(m.flow[i,j,t])
            if abs(q)>1e-8:flows.append(dict(origin=i,destination=j,step=t,hour=t,duration_h=1.,shift_mwh=q,cost=sc.spatial_fee_per_mwh*q))
    terms=dict(annualized_capacity=v(capital),renewable_dispatch=v(generation),grid_import=v(imports),storage_dispatch=v(storage),load_shifting=v(shift));objective=v(m.objective)
    from .foundation.service import code_identity
    model=sc.model_dump();digest=lambda x:hashlib.sha256(json.dumps(x,sort_keys=True,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode()).hexdigest()
    return dict(model_kind='opt_cfe',schema='opt_cfe_v1',name=sc.name,currency=sc.currency,horizon=dict(mode=sc.horizon_mode,weather_year=sc.weather_year,planning_year=sc.planning_year,start=sc.start,timezone='UTC',dt_hours=1.,steps=N),objective=objective,cost_terms=terms,investments=caps,hourly=rows,spatial_flows=flows,daily_work=days,matching=dict(mode=sc.matching,target=sc.target,annual_res_share='annual dispatched eligible generation / actual load, includes separately discarded excess; NOT hourly CFE',paper_cfe_score='eq(2)/(7): sum(generation+discharge-charge-excess+grid_cfe*imports)/sum(actual load); no over-credit above load; partial target is annual score NOT floor every hour',hourly_cfe_floor='stricter optional per-hour paper-credit floor; target1 agrees with perfect score',undefined_rates='site with assigned load0 has null annual shares (not0 or100%); allocation and objective still valid',storage_origin='separate green/brown SOC; grid charge split by given CFE factor; no grid energy relabelled local renewable',capacity_sharing='one generation/power/energy investment per site for every supplied hour; never independently re-optimized by day',additionality='contract assets new and in local bidding zone; workload shifts do NOT move electricity',grid_factor='exogenous input, not endogenous electricity-system redispatch/LMCE',excess='curtailment before generation and dispatched discarded excess distinct; no sale revenue, excess subtracted from CFE',scope='portfolio procurement plus supplied operating horizon; no background European OPF, real power markets, individual jobs or GPU controls',objective_scope='annualized capacity charge ONCE plus all supplied interval operating fees; short benchmark is NOT an annual outcome',spatial_table='sparse; omitted zero flows (threshold1e-8MW) are0; complete virtual graph, no physical power transfer'),audit=dict(max_physical_residual=residual,cost_terms_residual=sum(terms.values())-objective),solver=dict(name='Pyomo/HiGHS LP serial dual simplex',lp_algorithm='dual_simplex',termination=status,optimal=True,primal_tolerance=1e-7,dual_tolerance=1e-7,ipm_optimality_tolerance=None,time_limit_s=opt.config.time_limit,build_seconds=build_s,total_seconds=time.monotonic()-started,n_variables=m.nvariables(),n_constraints=m.nconstraints(),bound=float(solved.problem.lower_bound)),execution_context=dict(code_hash=code_identity(),input_model_hash=digest(model)),source=sc.source)

def export_task(task):
    """Saved annual results, not a new solve; no daily session or 24h conversion."""
    snap=task['snapshot'];result=task.get('full_result');buf=io.BytesIO()
    with zipfile.ZipFile(buf,'w',zipfile.ZIP_DEFLATED) as z:
        write=lambda name,data:z.writestr(name,json.dumps(data,ensure_ascii=False,indent=2,allow_nan=False))
        write('input_snapshot.json',snap);write('model.json',snap['model']);write('task_metadata.json',{**{k:task.get(k) for k in ['id','name','status','input_hash','execution_code_hash','execution_solver_identity','created','completed','error']},**({'error_traceback':task['error_traceback']} if task.get('error_traceback') else {})})
        if result:
            write('results.json',{k:v for k,v in result.items() if k not in ['hourly','spatial_flows','daily_work']})
            for key in ['hourly','spatial_flows','daily_work']:
                rows=result[key];out=io.StringIO();fields=list(rows[0]) if rows else (['origin','destination','step','hour','duration_h','shift_mwh','cost'] if key=='spatial_flows' else [])
                w=csv.DictWriter(out,fieldnames=fields);w.writeheader();w.writerows(rows);z.writestr(key+'.csv',out.getvalue())
        write('README.json',dict(engine='opt_cfe, NOT daily Scenario',units='powerMW, intervalMWh(dt1), storageMWh, capacity cost currency/year, operating currency/MWh',freeze='input_snapshot authoritative and input_hash immutable; export replays stored result, not new solve',matching='annual renewable share vs paper annual CFE score vs optional per-hour floor explicitly distinct',calendar='full source UTC year8760/8784, never truncated or padded; benchmark separately marked non-annual'))
    return buf.getvalue()
