"""Explicit DC market/compute feedback experiment; never replaces daily carbon accounting.
Cost-optimal DC clearing -> endogenous nodal/region signals -> conserved work -> clearing.
Finite directional sensitivities are NOT a claim of globally optimal coupled dispatch.
"""
from __future__ import annotations
import csv,io,json,math,time,zipfile,hashlib
from datetime import datetime,timedelta
from typing import Literal
import numpy as np
import scipy.linalg as la
import pyomo.environ as pyo
from pydantic import BaseModel,ConfigDict,Field,model_validator
from .solver_execution import serialized_pyomo,checked_solve

class Strict(BaseModel):
    model_config=ConfigDict(extra='forbid',allow_inf_nan=False)
class Bus(Strict):
    id:str
    region:str
    background_load_mw:list[float]
class Line(Strict):
    id:str
    from_bus:str
    to_bus:str
    b_mw_per_rad:float=Field(gt=0)
    limit_mw:float=Field(gt=0)
    source:dict=Field(default_factory=dict)
class Generator(Strict):
    id:str
    bus:str
    available_mw:list[float]
    pmin_mw:float=Field(default=0,ge=0)
    cost_usd_mwh:float=Field(ge=0)
    operational_tco2_mwh:float=Field(ge=0)
    lifecycle_extra_tco2_mwh:float=Field(default=0,ge=0)
    low_carbon:bool=False
    source:dict=Field(default_factory=dict)
class ComputeSite(Strict):
    id:str
    bus:str
    baseline_work_mw:list[float]
    pue:float=Field(default=1,ge=1)
    capacity_work_mw:float=Field(gt=0)
class GridFeedbackModel(Strict):
    model_kind:Literal['opt_grid_feedback']='opt_grid_feedback'
    name:str='DC grid feedback'
    horizon_mode:Literal['benchmark','original_data_subset']
    start:str
    dt_hours:Literal[1.0]=1.0
    buses:list[Bus]
    lines:list[Line]
    generators:list[Generator]
    sites:list[ComputeSite]
    slack_bus:str
    max_abs_angle_rad:float=Field(default=math.pi,gt=0,le=math.pi)
    flexibility:float=Field(default=.2,ge=0,le=1)
    trust_fraction_per_iteration:float=Field(default=.2,ge=0,le=1)
    signals:list[Literal['lmce','lmp','average','excess']]=Field(default_factory=lambda:['lmce','lmp','average','excess'])
    selected_signal:Literal['lmce','lmp','average','excess']='lmce'
    max_iterations:int=Field(default=3,ge=1,le=8)
    max_backtracks:int=Field(default=4,ge=0,le=8)
    convergence_mw:float=Field(default=1e-6,gt=0)
    fd_step_mw:float=Field(default=.01,gt=0,le=10)
    sensitivity_tolerance:float=Field(default=1e-4,gt=0)
    signal_method:Literal['forward_fd','validated_basis']='forward_fd'
    unstable_signal_policy:Literal['fail','allow_directional']='fail'
    iso_carbon_price_usd_t:float=Field(default=0,ge=0)
    scheduler_primary_tolerance:float=Field(default=0,ge=0)
    require_convergence:bool=False
    source:dict
    @property
    def n_steps(self):return len(self.buses[0].background_load_mw)
    @model_validator(mode='after')
    def valid(self):
        if not self.buses or not self.generators or not self.sites:raise ValueError('grid/compute must be nonempty')
        n=self.n_steps
        if not 1<=n<=168:raise ValueError('Phase6 limited to explicitly labelled <=168h subset/benchmark; full8784 not implemented, never truncate')
        dt=datetime.fromisoformat(self.start)
        if dt.tzinfo is None or dt.utcoffset()!=timedelta(0) or dt.minute or dt.second or dt.microsecond:raise ValueError('source time must be UTC whole hour')
        if self.selected_signal not in self.signals or len(set(self.signals))!=len(self.signals):raise ValueError('signals unique and selected signal included')
        ids=[b.id for b in self.buses]
        if len(set(ids))!=len(ids) or self.slack_bus not in ids:raise ValueError('unique buses/slack required')
        for group in [self.lines,self.generators,self.sites]:
            if len({x.id for x in group})!=len(group):raise ValueError('duplicate device id')
        for b in self.buses:
            if len(b.background_load_mw)!=n or min(b.background_load_mw)<0:raise ValueError('background nonnegative, matching time length')
        adj={b:set() for b in ids}
        for e in self.lines:
            if e.from_bus not in adj or e.to_bus not in adj or e.from_bus==e.to_bus:raise ValueError('invalid line endpoint')
            adj[e.from_bus].add(e.to_bus);adj[e.to_bus].add(e.from_bus)
        seen={self.slack_bus};pending=[self.slack_bus]
        while pending:
            for b in adj[pending.pop()]-seen:seen.add(b);pending.append(b)
        if len(seen)!=len(ids):raise ValueError('this mode requires connected grid; no implicit island slack')
        for g in self.generators:
            if g.bus not in adj or len(g.available_mw)!=n or min(g.available_mw)<g.pmin_mw:raise ValueError('generator bus/bounds/time length invalid')
        for s in self.sites:
            if s.bus not in adj or len(s.baseline_work_mw)!=n or min(s.baseline_work_mw)<0 or max(s.baseline_work_mw)>s.capacity_work_mw:raise ValueError('compute capacity/baseline/time invalid')
        if self.horizon_mode=='original_data_subset':
            idx=self.source.get('source_hour_indices',[])
            if len(idx)!=n or self.source.get('source_total_hours')!=8784 or any(not isinstance(i,int) or not 0<=i<8784 for i in idx):raise ValueError('subset must retain exact indices into original8784; no deleted leap day')
            import calendar
            try:origin=datetime.fromisoformat(self.source.get('source_start',''))
            except (ValueError,TypeError):raise ValueError('original source_start must identify the complete UTC leap year')
            if origin.tzinfo is None or origin.utcoffset().total_seconds()!=0 or (origin.month,origin.day,origin.hour,origin.minute,origin.second)!=(1,1,0,0,0) or not calendar.isleap(origin.year):raise ValueError('original8784 source axis must start UTC Jan1 of a leap year')
            if any(origin+timedelta(hours=i)!=dt+timedelta(hours=k) for k,i in enumerate(idx)):raise ValueError('subset timestamps/indices disagree; no relabelling')
        return self

def check_axis(axis,sc):
    if axis.get('timezone')!='UTC' or axis.get('step_minutes')!=60 or axis.get('length')!=sc.n_steps or datetime.fromisoformat(axis['start'])!=datetime.fromisoformat(sc.start) or axis.get('year')!=datetime.fromisoformat(sc.start).year:raise ValueError('grid feedback axis must exactly match source UTC hours/subset')

def _opt(model,seconds):
    opt=pyo.SolverFactory('appsi_highs');opt.config.time_limit=float(seconds)
    opt.highs_options.update(solver='simplex',parallel='off',primal_feasibility_tolerance=1e-8,dual_feasibility_tolerance=1e-8)
    r=checked_solve(opt,model,load_solutions=False)
    if str(r.solver.termination_condition)!='optimal':raise RuntimeError('DC/compute LP not optimal: '+str(r.solver.termination_condition)+'; no fallback/accepted approximate solution')
    opt.load_vars();return opt

@serialized_pyomo('grid_clearing')
def clear(sc:GridFeedbackModel,step:int,loads:dict,seconds=60):
    """Lossless DC OPF, no load shedding/export balancing slack or hidden spill."""
    m=pyo.ConcreteModel();bs=[b.id for b in sc.buses];gs=sc.generators;es=sc.lines
    m.theta=pyo.Var(bs,bounds=(-sc.max_abs_angle_rad,sc.max_abs_angle_rad));m.theta[sc.slack_bus].fix(0)
    m.p=pyo.Var(range(len(gs)),bounds=lambda _,j:(gs[j].pmin_mw,gs[j].available_mw[step]))
    flow={e.id:e.b_mw_per_rad*(m.theta[e.from_bus]-m.theta[e.to_bus]) for e in es}
    m.balance=pyo.Constraint(bs,rule=lambda _,b:sum(m.p[j] for j,g in enumerate(gs) if g.bus==b)-sum(flow[e.id] for e in es if e.from_bus==b)+sum(flow[e.id] for e in es if e.to_bus==b)==float(loads[b]))
    m.line=pyo.ConstraintList()
    for e in es:m.line.add(flow[e.id]<=e.limit_mw);m.line.add(flow[e.id]>=-e.limit_mw)
    coeff=[g.cost_usd_mwh+sc.iso_carbon_price_usd_t*g.operational_tco2_mwh for g in gs]
    m.obj=pyo.Objective(expr=sum(coeff[j]*m.p[j] for j in range(len(gs))));m.dual=pyo.Suffix(direction=pyo.Suffix.IMPORT)
    opt=_opt(m,seconds);pg=np.array([pyo.value(m.p[j]) for j in range(len(gs))]);th={b:float(pyo.value(m.theta[b])) for b in bs};fl={e.id:float(pyo.value(flow[e.id])) for e in es}
    active=[];tol=1e-6
    for j,g in enumerate(gs):
        if abs(pg[j]-g.pmin_mw)<=tol:active.append('glo:'+g.id)
        if abs(pg[j]-g.available_mw[step])<=tol:active.append('ghi:'+g.id)
    for e in es:
        if abs(fl[e.id]-e.limit_mw)<=tol:active.append('line+:'+e.id)
        if abs(fl[e.id]+e.limit_mw)<=tol:active.append('line-:'+e.id)
    for b in bs:
        if b!=sc.slack_bus and abs(abs(th[b])-sc.max_abs_angle_rad)<=tol:active.append('theta:'+b)
    balance={b:sum(pg[j] for j,g in enumerate(gs) if g.bus==b)-loads[b]-sum(fl[e.id] for e in es if e.from_bus==b)+sum(fl[e.id] for e in es if e.to_bus==b) for b in bs}
    maxres=max(abs(v) for v in balance.values());violation=max([0.]+[abs(fl[e.id])-e.limit_mw for e in es]+[g.pmin_mw-pg[j] for j,g in enumerate(gs)]+[pg[j]-g.available_mw[step] for j,g in enumerate(gs)])
    if maxres>1e-5 or violation>1e-5:raise RuntimeError('post-clear physical audit failed')
    return dict(step=step,loads_mw=loads,pg_mw=pg.tolist(),theta_rad=th,flows_mw=fl,lmp_usd_mwh={b:float(opt.get_duals([m.balance[b]])[m.balance[b]]) for b in bs},cost_usd=float(sum(g.cost_usd_mwh*pg[j] for j,g in enumerate(gs))),operational_tco2=float(sum(g.operational_tco2_mwh*pg[j] for j,g in enumerate(gs))),lifecycle_extra_tco2=float(sum(g.lifecycle_extra_tco2_mwh*pg[j] for j,g in enumerate(gs))),iso_objective_usd=float(pyo.value(m.obj)),active_set=active,max_balance_residual_mw=maxres,max_bound_violation_mw=max(0.,violation),solver=dict(termination='optimal',primal_tolerance=1e-8,soft_limit_s=seconds,algorithm='dual_simplex'))

def _basis(sc,grid):
    """Paper(5)(6) independent binding-row subset, explicitly diagnose degeneracy."""
    non=[b.id for b in sc.buses if b.id!=sc.slack_bus];ti={b:i for i,b in enumerate(non)};nt=len(non);nv=nt+len(sc.generators);bs=[b.id for b in sc.buses];eq=[]
    for b in bs:
        a=np.zeros(nv)
        for j,g in enumerate(sc.generators):
            if g.bus==b:a[nt+j]=1
        for e in sc.lines:
            sign=1 if e.from_bus==b else (-1 if e.to_bus==b else 0)
            if sign:
                if e.from_bus in ti:a[ti[e.from_bus]]-=sign*e.b_mw_per_rad
                if e.to_bus in ti:a[ti[e.to_bus]]+=sign*e.b_mw_per_rad
        eq.append(a)
    rows=list(eq);names=['balance:'+b for b in bs]
    for name in grid['active_set']:
        a=np.zeros(nv)
        if name.startswith(('glo:','ghi:')):a[nt+next(i for i,g in enumerate(sc.generators) if g.id==name.split(':',1)[1])]=1
        elif name.startswith('line'):
            e=next(e for e in sc.lines if e.id==name.split(':',1)[1])
            if e.from_bus in ti:a[ti[e.from_bus]]=e.b_mw_per_rad
            if e.to_bus in ti:a[ti[e.to_bus]]=-e.b_mw_per_rad
        else:a[ti[name.split(':',1)[1]]]=1
        rows.append(a);names.append(name)
    A=np.asarray(rows);_,R,piv=la.qr(A.T,pivoting=True,mode='economic');diag=np.abs(np.diag(R));rank=int(np.sum(diag>1e-9));chosen=list(piv[:nv]);report=dict(variables=nv,binding_rows=len(rows),rank=rank,degenerate_binding_excess=max(0,len(rows)-nv),basis_rows=[names[i] for i in chosen],condition=None,analytic_lmce={},analytic_objective_gradient={})
    if rank<nv:return report
    B=A[chosen];condition=float(np.linalg.cond(B));report['condition']=condition if np.isfinite(condition) else None;
    if not np.isfinite(condition):return report
    rhs=np.zeros((nv,len(sc.sites)))
    for j,s in enumerate(sc.sites):
        bidx=bs.index(s.bus)
        if bidx in chosen:rhs[chosen.index(bidx),j]=1
    dx=la.solve(B,rhs);g=np.array([x.operational_tco2_mwh for x in sc.generators]);c=np.array([x.cost_usd_mwh+sc.iso_carbon_price_usd_t*x.operational_tco2_mwh for x in sc.generators]);report['analytic_lmce']={s.id:float(g@dx[nt:,j]) for j,s in enumerate(sc.sites)};report['analytic_objective_gradient']={s.id:float(c@dx[nt:,j]) for j,s in enumerate(sc.sites)};return report

def _signals(sc,grids,seconds):
    rows=[];basis=[]
    for t,grid in enumerate(grids):
        bas=_basis(sc,grid);basis.append(dict(step=t,**bas));region={}
        for b in sc.buses:
            if b.region in region:continue
            jj=[j for j,g in enumerate(sc.generators) if next(x for x in sc.buses if x.id==g.bus).region==b.region];total=sum(grid['pg_mw'][j] for j in jj);region[b.region]=(None if total<=1e-12 else sum(grid['pg_mw'][j]*sc.generators[j].operational_tco2_mwh for j in jj)/total,-sum(sc.generators[j].available_mw[t]-grid['pg_mw'][j] for j in jj if sc.generators[j].low_carbon))
        for s in sc.sites:
            slopes={};errors={};changed={};fdcost={};fdiso={}
            for label,h in [('plus',sc.fd_step_mw),('minus',-sc.fd_step_mw),('half',sc.fd_step_mw/2)]:
                load=dict(grid['loads_mw']);load[s.bus]+=h
                if load[s.bus]<0:errors[label]='negative perturbed load';continue
                try:
                    p=clear(sc,t,load,seconds);slopes[label]=(p['operational_tco2']-grid['operational_tco2'])/h;fdcost[label]=(p['cost_usd']-grid['cost_usd'])/h;fdiso[label]=(p['iso_objective_usd']-grid['iso_objective_usd'])/h;changed[label]=p['active_set']!=grid['active_set']
                except RuntimeError as e:errors[label]=str(e)
            analytic=bas['analytic_lmce'].get(s.id);spread=max(slopes.values())-min(slopes.values()) if len(slopes)==3 else None
            stable=spread is not None and spread<=sc.sensitivity_tolerance and analytic is not None and max(abs(v-analytic) for v in slopes.values())<=sc.sensitivity_tolerance
            average,excess=region[next(b.region for b in sc.buses if b.id==s.bus)]
            value=analytic if sc.signal_method=='validated_basis' else slopes.get('plus')
            rows.append(dict(step=t,site=s.id,bus=s.bus,lmce_tco2_mwh=value,lmp_usd_mwh=grid['lmp_usd_mwh'][s.bus],average_tco2_mwh=average,excess_mw=excess,analytic_lmce=analytic,fd_plus=slopes.get('plus'),fd_minus=slopes.get('minus'),fd_half=slopes.get('half'),fd_cost_plus=fdcost.get('plus'),fd_cost_minus=fdcost.get('minus'),fd_iso_objective_plus=fdiso.get('plus'),fd_step_mw=sc.fd_step_mw,stable=stable,negative_lmce=value is not None and value<0,active_set_changed=changed,fd_errors=errors,basis_rank=bas['rank'],basis_variables=bas['variables'],basis_condition=bas['condition'],basis_degenerate_excess=bas['degenerate_binding_excess'],method=sc.signal_method))
    return rows,basis

@serialized_pyomo('compute_signal_scheduler')
def schedule(sc,work,signals,policy,seconds):
    m=pyo.ConcreteModel();S=range(len(sc.sites));T=range(sc.n_steps);lookup={(r['site'],r['step']):r for r in signals};key={'lmce':'lmce_tco2_mwh','lmp':'lmp_usd_mwh','average':'average_tco2_mwh','excess':'excess_mw'}[policy]
    coeff={(i,t):lookup[(s.id,t)][key]*s.pue for i,s in enumerate(sc.sites) for t in T}
    def bounds(_,i,t):
        s=sc.sites[i];b=s.baseline_work_mw[t];h=b*sc.trust_fraction_per_iteration;return max(0,b*(1-sc.flexibility),work[i][t]-h),min(s.capacity_work_mw,b*(1+sc.flexibility),work[i][t]+h)
    m.w=pyo.Var(S,T,bounds=bounds);m.u=pyo.Var(S,T,bounds=(0,None));m.c=pyo.ConstraintList()
    for t in T:m.c.add(sum(m.w[i,t] for i in S)==sum(s.baseline_work_mw[t] for s in sc.sites))
    for i in S:
        for t in T:m.c.add(m.u[i,t]>=m.w[i,t]-work[i][t]);m.c.add(m.u[i,t]>=work[i][t]-m.w[i,t])
    expr=sum(coeff[i,t]*m.w[i,t] for i in S for t in T);m.primary=pyo.Objective(expr=expr);_opt(m,seconds);best=float(pyo.value(expr));m.c.add(expr<=best+sc.scheduler_primary_tolerance);m.primary.deactivate();m.second=pyo.Objective(expr=sum(m.u[i,t] for i in S for t in T)/2);_opt(m,seconds);out=[[float(pyo.value(m.w[i,t])) for t in T] for i in S]
    return dict(work=out,primary_optimum=best,primary_after=float(pyo.value(expr)),primary_tolerance=sc.scheduler_primary_tolerance,gross_moved_work_mwh=float(pyo.value(m.second)),status='optimal',units={'lmce':'tCO2','lmp':'USD ISO objective including explicit carbon price, not pure operating cost','average':'tCO2 proxy, NOT system emissions','excess':'MW^2 proxy, NOT tonnes or money'}[policy])

class FeedbackFailure(RuntimeError):
    def __init__(self,message,result):super().__init__(message);self.partial_result=result

def _totals(grids):
    return {k:float(sum(r[k] for r in grids)) for k in ['cost_usd','operational_tco2','lifecycle_extra_tco2','iso_objective_usd']}

def _loads(sc,w):return [{b.id:b.background_load_mw[t]+sum(w[i][t]*s.pue for i,s in enumerate(sc.sites) if s.bus==b.id) for b in sc.buses} for t in range(sc.n_steps)]

@serialized_pyomo('grid_feedback')
def solve(raw,config=None):
    start=time.monotonic();sc=GridFeedbackModel.model_validate(raw);seconds=float((config or {}).get('time_limit_s',60));w0=[list(s.baseline_work_mw) for s in sc.sites];cache={};clear_count=0
    def evaluate(w):
        nonlocal clear_count
        key=json.dumps(w,separators=(',',':'))
        if key not in cache:
            ll=_loads(sc,w);gg=[clear(sc,t,ll[t],seconds) for t in range(sc.n_steps)];sig,bas=_signals(sc,gg,seconds);cache[key]=(gg,sig,bas);clear_count+=sc.n_steps*(1+3*len(sc.sites))
        return cache[key]
    base,initial_sig,initial_basis=evaluate(w0);bt=_totals(base);policies=[];all_signal_rows=[];all_basis_rows=[];grid_rows=[];work_rows=[];flow_rows=[];iterations=[];migration_rows=[]
    def record_grid(policy,iteration,grids,work):
        for t,r in enumerate(grids):
            timestamp=(datetime.fromisoformat(sc.start)+timedelta(hours=t)).isoformat()
            for j,g in enumerate(sc.generators):grid_rows.append(dict(policy=policy,iteration=iteration,step=t,timestamp=timestamp,generator=g.id,bus=g.bus,p_mw=r['pg_mw'][j],available_mw=g.available_mw[t],cost_usd_mwh=g.cost_usd_mwh,operational_tco2_mwh=g.operational_tco2_mwh,lifecycle_extra_tco2_mwh=g.lifecycle_extra_tco2_mwh,duration_h=1))
            for e in sc.lines:flow_rows.append(dict(policy=policy,iteration=iteration,step=t,line=e.id,from_bus=e.from_bus,to_bus=e.to_bus,flow_mw=r['flows_mw'][e.id],limit_mw=e.limit_mw,b_mw_per_rad=e.b_mw_per_rad,theta_from_rad=r['theta_rad'][e.from_bus],theta_to_rad=r['theta_rad'][e.to_bus],duration_h=1))
            for i,s in enumerate(sc.sites):work_rows.append(dict(policy=policy,iteration=iteration,step=t,site=s.id,bus=s.bus,baseline_work_mw=s.baseline_work_mw[t],work_mw=work[i][t],pue=s.pue,electrical_load_mw=work[i][t]*s.pue,duration_h=1))
    record_grid('baseline',0,base,w0)
    for policy in sc.signals:
        work=[r[:] for r in w0];seen={json.dumps(work)};status='iteration_limit';error=None;current=base
        for k in range(sc.max_iterations):
            current,sig,bas=evaluate(work);all_signal_rows += [dict(policy=policy,iteration=k,**r) for r in sig];all_basis_rows += [dict(policy=policy,iteration=k,**r) for r in bas]
            relevant=[r for r in sig if (r['lmce_tco2_mwh'] is None or (not r['stable'] and sc.unstable_signal_policy=='fail'))] if policy=='lmce' else [r for r in sig if r[{'lmp':'lmp_usd_mwh','average':'average_tco2_mwh','excess':'excess_mw'}[policy]] is None]
            if relevant:status='signal_unstable';error='undefined/unstable signal; no surrogate/fixed-factor fallback';break
            try:plan=schedule(sc,work,sig,policy,seconds)
            except RuntimeError as e:status='scheduler_failed';error=str(e);break
            proposal=plan['work'];maxchange=max(abs(proposal[i][t]-work[i][t]) for i in range(len(work)) for t in range(sc.n_steps));before=_totals(current)
            if maxchange<=sc.convergence_mw:status='fixed_point';iterations.append(dict(policy=policy,iteration=k,status=status,max_change_mw=maxchange,scheduler=plan));break
            accepted=None;attempts=[];factor=1.
            for attempt in range(sc.max_backtracks+1):
                candidate=[[work[i][t]+factor*(proposal[i][t]-work[i][t]) for t in range(sc.n_steps)] for i in range(len(work))]
                try:
                    ll=_loads(sc,candidate);gg=[clear(sc,t,ll[t],seconds) for t in range(sc.n_steps)];clear_count+=sc.n_steps;accepted=(candidate,gg);break
                except RuntimeError as e:attempts.append(dict(factor=factor,error=str(e)));factor*=.5
            if accepted is None:status='reclear_infeasible';error='all explicitly audited backtracks failed';iterations.append(dict(policy=policy,iteration=k,status=status,attempts=attempts));break
            candidate,gg=accepted;after=_totals(gg);lookup={(r['site'],r['step']):r for r in sig};pred_e=0.;pred_c=0.;pred_iso=0.;gross=0.
            for t in range(sc.n_steps):
                supply=[];demand=[]
                for i,s in enumerate(sc.sites):
                    delta=candidate[i][t]-work[i][t];r=lookup[s.id,t];pred_e=None if pred_e is None or r['lmce_tco2_mwh'] is None else pred_e+r['lmce_tco2_mwh']*delta*s.pue;pred_c=None if pred_c is None or r['fd_cost_plus'] is None else pred_c+r['fd_cost_plus']*delta*s.pue;pred_iso+=r['lmp_usd_mwh']*delta*s.pue
                    if delta< -1e-8:supply.append([s.id,-delta])
                    if delta>1e-8:demand.append([s.id,delta])
                for src in supply:
                    for dst in demand:
                        q=min(src[1],dst[1])
                        if q>1e-8:migration_rows.append(dict(policy=policy,iteration=k,step=t,from_site=src[0],to_site=dst[0],work_mwh=q,duration_h=1));gross+=q;src[1]-=q;dst[1]-=q
            activechanged=sum(a['active_set']!=b['active_set'] for a,b in zip(current,gg));row=dict(policy=policy,iteration=k,status='recleared_optimal',accepted_fraction=factor,max_change_mw=maxchange*factor,predicted_operational_delta_tco2=pred_e,actual_operational_delta_tco2=after['operational_tco2']-before['operational_tco2'],predicted_cost_delta_usd=pred_c,actual_cost_delta_usd=after['cost_usd']-before['cost_usd'],predicted_iso_objective_delta_usd=pred_iso,actual_iso_objective_delta_usd=after['iso_objective_usd']-before['iso_objective_usd'],active_set_changed_hours=activechanged,failed_backtracks=attempts,gross_moved_work_mwh=gross,scheduler=plan);iterations.append(row);record_grid(policy,k+1,gg,candidate);key=json.dumps(candidate);work=candidate;current=gg
            if key in seen:status='cycle_detected';break
            seen.add(key)
        final=_totals(current);delta=[[(work[i][t]-w0[i][t])*s.pue for t in range(sc.n_steps)] for i,s in enumerate(sc.sites)];initial_lookup={(r['site'],r['step']):r for r in initial_sig};initial_prediction=None if any(r['lmce_tco2_mwh'] is None for r in initial_sig) else sum(initial_lookup[s.id,t]['lmce_tco2_mwh']*delta[i][t] for i,s in enumerate(sc.sites) for t in range(sc.n_steps));workres=max(abs(sum(work[i][t] for i in range(len(work)))-sum(s.baseline_work_mw[t] for s in sc.sites)) for t in range(sc.n_steps));finalgross=sum(abs(work[i][t]-w0[i][t]) for i in range(len(work)) for t in range(sc.n_steps))/2;allowed=sum(s.baseline_work_mw[t]*sc.flexibility for s in sc.sites for t in range(sc.n_steps));actual_delta=final['operational_tco2']-bt['operational_tco2']
        if workres>1e-5:raise RuntimeError('work conservation violated; no dropped work allowed')
        policies.append(dict(signal=policy,status=status,error=error,converged=status=='fixed_point',global_optimality_claimed=False,final_totals=final,predicted_operational_delta_from_initial_tco2=initial_prediction,actual_operational_delta_tco2=actual_delta,actual_operational_reduction_tco2=-actual_delta,actual_cost_delta_usd=final['cost_usd']-bt['cost_usd'],actual_iso_objective_delta_usd=final['iso_objective_usd']-bt['iso_objective_usd'],final_net_work_moved_mwh=finalgross,allowed_work_mwh=allowed,reduction_per_allowed_work_mwh=None if allowed==0 else -actual_delta/allowed,reduction_per_actual_work_mwh=None if finalgross==0 else -actual_delta/finalgross,max_work_residual_mw=workres,final_work_mw=work))
    result=dict(model_kind=sc.model_kind,name=sc.name,status='experiment_evaluated_NOT_global_optimum',source=sc.source,horizon=dict(mode=sc.horizon_mode,start=sc.start,steps=sc.n_steps,dt_hours=1),baseline_totals=bt,policies=policies,selected_signal=sc.selected_signal,selected_policy=next(p for p in policies if p['signal']==sc.selected_signal),signals=all_signal_rows,basis=all_basis_rows,iterations=iterations,generation=grid_rows,lines=flow_rows,work=work_rows,migrations=migration_rows,solver=dict(each_LP_must_be_optimal=True,global_optimality_claimed=False,estimated_clear_LP_attempts=clear_count,seconds=time.monotonic()-start,soft_limit_per_LP_s=seconds,not_end_to_end_deadline=True),boundaries=dict(emissions='system operational metric tonnes; LCA-extra separately reported, not fed to operational LMCE',compute='spatial fluid work conserved EACH hour; no cancellation/shedding, no temporal/multihop/GPU model',iso='USD objective=operating cost + explicit USD/tCO2 operational price; LMP is this monetized objective derivative, separate operating cost FD/audit; lossless DC, connected grid, explicit anglebox; no AC/ramping/unit commitment/storage intertemporal model',prediction='initial LMCE dot net electrical load change; actual=full system emissions after ISO reclear',tie='solver-basis cost LP; dispatch/emission degeneracy may make sensitivities nonunique; FD/basis discrepancies retained',feedback='feasible-only acceptance, not guaranteed descent; cycle/iteration-limit not convergence; no global coupled optimum',normalization='t/MWh of IT-equivalent migrated/allowed work for this1h mode; not annual paper TableI values'))
    if sc.require_convergence and any(not p['converged'] for p in policies):raise FeedbackFailure('required convergence not achieved; partial experiment preserved, not optimal',result)
    return result

def export_task(t):
    buf=io.BytesIO()
    with zipfile.ZipFile(buf,'w',zipfile.ZIP_DEFLATED) as z:
        def put(n,x):z.writestr(n,json.dumps(x,ensure_ascii=False,indent=2,allow_nan=False))
        put('input_snapshot.json',t['snapshot']);put('model.json',t['snapshot']['model']);put('task_metadata.json',{k:v for k,v in t.items() if k not in ('snapshot','full_result','partial_result')});r=t.get('full_result') or t.get('partial_result')
        if r:
            tables=['signals','basis','iterations','generation','lines','work','migrations'];put('results.json' if t['status']=='completed' else 'partial_NOT_ACCEPTED.json',{k:v for k,v in r.items() if k not in tables})
            for name in tables:
                rows=r[name]
                if not rows:z.writestr(name+'.csv','');continue
                fields=list(dict.fromkeys(k for row in rows for k in row));s=io.StringIO();w=csv.DictWriter(s,fields);w.writeheader();w.writerows({k:json.dumps(v,ensure_ascii=False) if isinstance(v,(dict,list)) else v for k,v in row.items()} for row in rows);z.writestr(name+'.csv',s.getvalue())
        put('README.json',dict(mode='explicit_grid_feedback',accepted=t['status']=='completed',not_global_optimum=True,source_and_units='model.json gen/line source; per-LP objective/cost/operational/LCA and FDstep/basis/switch/errors inCSV',failed_runs='no results.json forfailed; partial tables ifpresent clearly not accepted',history='input/code hashes frozen separately from execution hash; old tasks not mutated'))
    return buf.getvalue()
