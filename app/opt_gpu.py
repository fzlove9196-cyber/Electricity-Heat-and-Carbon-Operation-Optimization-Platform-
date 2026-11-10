"""Discrete fixed-gang GPU scheduling. Explicit isolated subsystem, not DC PUE/thermal replacement."""
from __future__ import annotations
import math,json,io,csv,zipfile,time
from datetime import datetime,timedelta
import pyomo.environ as p
from pydantic import BaseModel,ConfigDict,Field,model_validator
from .solver_execution import serialized_pyomo,checked_solve
FLOORS={0:1.,1:.9,2:.75,3:.5}
class Strict(BaseModel):model_config=ConfigDict(extra='forbid',allow_inf_nan=False)
class GPU(Strict):
 id:str
 idle_power_w:float=Field(ge=0)
 source:dict
class Action(Strict):
 id:str
 cap_w:float=Field(gt=0)
 power_w_per_gpu:float=Field(ge=0)
 normalized_rate:float=Field(gt=0,le=2)
 validation_power_w_per_gpu:float|None=Field(default=None,ge=0)
 validation_normalized_rate:float|None=Field(default=None,gt=0,le=2)
 source:dict
class Window(Strict):
 start_h:float=Field(ge=0)
 end_h:float=Field(gt=0)
class Job(Strict):
 id:str
 gpu_ids:list[str]
 actions:list[Action]
 reference_action:str
 baseline_rate:list[float]
 required_work_h:float=Field(ge=1e-5)
 release_h:float=Field(default=0,ge=0)
 deadline_h:float=Field(gt=0)
 flex:int=Field(ge=0,le=3)
 sla_windows:list[Window]
 allow_pause:bool=False
 pause_power_w_per_gpu:float|None=Field(default=None,ge=0)
 source:dict
class GpuModel(Strict):
 model_kind:str='opt_gpu'
 name:str='GPU scheduling'
 start:str='2025-05-03T07:00:00+08:00'
 dt_hours:float=Field(default=1,gt=0)
 n_steps:int=Field(ge=1,le=96)
 gpus:list[GPU]
 jobs:list[Job]
 price_usd_kwh:list[float]
 power_limit_kw:list[float|None]
 non_gpu_fixed_kw:float=Field(default=0,ge=0)
 power_boundary:str='GPU subtotal plus explicitly fixed overhead; NOT whole DC/PUE/thermal certified'
 policy:str='energy_cost'
 fairness_definition:str='explicit_variant_minimax_fraction_of_Flex_allowance; author README separately publishes power-headroom Fair pseudocode, NOT equated'
 sla_window_semantics:str='paper_3_to_6_hours'
 mip_relative_gap:float=Field(default=0,ge=0,le=.01)
 lex_tolerance:float=Field(default=1e-7,ge=0,le=1e-3)
 require_validation_feasible:bool=True
 source:dict
 @model_validator(mode='after')
 def valid(self):
  if self.model_kind!='opt_gpu' or self.dt_hours not in (.25,1.) or self.policy not in ('energy_cost','fair_minimax','author_dvfs_headroom_discrete'):raise ValueError('explicit opt_gpu,15min/1h,energy_cost/fair_minimax/author_dvfs_headroom_discrete only')
  if self.sla_window_semantics not in ('paper_3_to_6_hours','synthetic_short_window'):raise ValueError('declare actual SLA window scope')
  d=datetime.fromisoformat(self.start)
  if d.tzinfo is None or d.second or d.microsecond or d.minute%(int(self.dt_hours*60)):raise ValueError('start needs explicit timezone and aligned slot')
  if len(self.price_usd_kwh)!=self.n_steps or len(self.power_limit_kw)!=self.n_steps or min(self.price_usd_kwh)<0 or any(v is not None and v<0 for v in self.power_limit_kw):raise ValueError('price/power length/units invalid; no implicit resampling')
  if not self.gpus or not self.jobs or len({g.id for g in self.gpus})!=len(self.gpus) or len({j.id for j in self.jobs})!=len(self.jobs):raise ValueError('unique nonempty GPU/job lists required')
  gs={g.id for g in self.gpus};used=set();H=self.n_steps*self.dt_hours
  def aligned(h):return abs(h/self.dt_hours-round(h/self.dt_hours))<1e-8
  for j in self.jobs:
   if not j.gpu_ids or len(set(j.gpu_ids))!=len(j.gpu_ids) or not set(j.gpu_ids)<=gs or used&set(j.gpu_ids):raise ValueError('fixed disjoint calibrated GPU gangs; sharing/resizing not supported')
   used.update(j.gpu_ids)
   if not 0<=j.release_h<j.deadline_h<=H or not aligned(j.release_h) or not aligned(j.deadline_h):raise ValueError('release/deadline physical hours must align')
   if len(j.baseline_rate)!=self.n_steps or any(not 0<=v<=1 for v in j.baseline_rate) or abs(sum(j.baseline_rate)*self.dt_hours-j.required_work_h)>1e-7:raise ValueError('same required work = integral of explicit baseline rate, in baseline-gang-hours')
   if any(v>0 and not j.release_h<=t*self.dt_hours<j.deadline_h for t,v in enumerate(j.baseline_rate)):raise ValueError('baseline work outside lifetime')
   if len({a.id for a in j.actions})!=len(j.actions) or not j.actions or j.reference_action not in [a.id for a in j.actions]:raise ValueError('unique actions and explicit reference required')
   ref=next(a for a in j.actions if a.id==j.reference_action)
   if abs(ref.normalized_rate-1)>1e-8:raise ValueError('reference action must be normalized1')
   if j.allow_pause and j.pause_power_w_per_gpu is None:raise ValueError('pause power is mandatory explicit input; not guessed from DVFS')
   if not j.sla_windows:raise ValueError('explicit SLA windows required; no guessed rolling semantics')
   for w in j.sla_windows:
    if not j.release_h<=w.start_h<w.end_h<=j.deadline_h or not aligned(w.start_h) or not aligned(w.end_h):raise ValueError('SLA window boundaries invalid')
    if self.sla_window_semantics=='paper_3_to_6_hours' and not 3<=w.end_h-w.start_h<=6:raise ValueError('paper Flex average-throughput windows must be3–6h; short controls explicitly synthetic')
    if sum(j.baseline_rate[int(round(w.start_h/self.dt_hours)):int(round(w.end_h/self.dt_hours))])<=0:raise ValueError('undefined zero-baseline SLA window')
  if self.policy=='author_dvfs_headroom_discrete':
   events=[t for t,v in enumerate(self.power_limit_kw) if v is not None]
   if not events:raise ValueError('author headroom mode needs an explicit event budget')
   for j in self.jobs:
    if len(j.sla_windows)!=1 or any(not j.sla_windows[0].start_h<=t*self.dt_hours<j.sla_windows[0].end_h for t in events):raise ValueError('headroom pseudocode realization currently needs one declared SLA window covering all event slots')
  return self

def check_axis(a,m):
 if a.get('year')!=datetime.fromisoformat(m.start).year or a.get('step_minutes')!=m.dt_hours*60 or a.get('length')!=m.n_steps or datetime.fromisoformat(a['start'])!=datetime.fromisoformat(m.start):raise ValueError('GPU axis must exactly match dt/physical start/length; no silent 1h')
class GPUValidationFailure(RuntimeError):
 def __init__(self,message,result):super().__init__(message);self.partial_result=result

def _milp(m,sc,seconds,label):
 opt=p.SolverFactory('appsi_highs');opt.config.time_limit=seconds;opt.highs_options.update(mip_rel_gap=sc.mip_relative_gap,parallel='off',primal_feasibility_tolerance=1e-8);r=checked_solve(opt,m,load_solutions=False);info=opt._solver_model.getInfo();report=dict(phase=label,objective_units='dimensionless fraction' if label.startswith('minimax') else 'kWh' if label.startswith('maximize_event_energy') else 'USD',termination=str(r.solver.termination_condition),requested_relative_gap=sc.mip_relative_gap,incumbent=float(info.objective_function_value),dual_bound=float(info.mip_dual_bound),relative_gap=float(info.mip_gap),nodes=int(info.mip_node_count),limit_s=seconds)
 if report['termination']!='optimal':raise RuntimeError('GPU MILP not optimal/accepted: '+json.dumps(report)+'; no fallback or fabricated task completion')
 opt.load_vars();return report

@serialized_pyomo('gpu_discrete_scheduler')
def solve(raw,config=None):
 st=time.monotonic();s=GpuModel.model_validate(raw);dt=s.dt_hours;T=range(s.n_steps);J=range(len(s.jobs));gp={g.id:g for g in s.gpus};seconds=float((config or {}).get('time_limit_s',60));m=p.ConcreteModel();keys=[(i,t,a) for i,j in enumerate(s.jobs) for t in T for a in range(len(j.actions)+2)];m.K=p.Set(initialize=keys,dimen=3);m.x=p.Var(m.K,domain=p.Binary);m.q=p.Var(J,T,bounds=(0,None));m.done=p.Var(J,T,domain=p.Binary);m.rho=p.Var(bounds=(0,1));m.c=p.ConstraintList();power={t:s.non_gpu_fixed_kw+sum(g.idle_power_w for g in s.gpus)/1000 for t in T};energy=0;cost=0;window_data=[]
 for i,j in enumerate(s.jobs):
  n=len(j.actions);idle=sum(gp[g].idle_power_w for g in j.gpu_ids)/len(j.gpu_ids);N=len(j.gpu_ids);maxrate=max(a.normalized_rate for a in j.actions)
  for t in T:
   inside=j.release_h<=t*dt<j.deadline_h;prev=m.done[i,t-1] if t else 0;cum=sum(m.q[i,k] for k in range(t+1));m.c.add(sum(m.x[i,t,a] for a in range(n+2))==1);m.c.add(m.q[i,t]<=sum(j.actions[a].normalized_rate*dt*m.x[i,t,a] for a in range(n)));m.c.add(m.q[i,t]<=j.required_work_h);m.c.add(cum<=j.required_work_h);m.c.add(cum>=j.required_work_h*m.done[i,t]);m.c.add(cum<=j.required_work_h-1e-7+j.required_work_h*m.done[i,t]);m.c.add(m.done[i,t]>=prev)
   if inside:
    m.c.add(m.x[i,t,n+1]==prev)
    if not j.allow_pause:m.x[i,t,n].fix(0)
    if j.flex==0 and j.baseline_rate[t]>0:
     m.c.add(m.q[i,t]>=j.baseline_rate[t]*dt)
     for a in range(n):
      if j.actions[a].id!=j.reference_action:m.x[i,t,a].fix(0)
     m.x[i,t,n].fix(0)
   else:
    m.q[i,t].fix(0);m.x[i,t,n+1].fix(1)
   actual=sum(a.power_w_per_gpu*m.x[i,t,k] for k,a in enumerate(j.actions))+(j.pause_power_w_per_gpu or 0)*m.x[i,t,n]+idle*m.x[i,t,n+1];power[t]+=N*(actual-idle)/1000
  deadline=int(round(j.deadline_h/dt))-1;m.c.add(sum(m.q[i,t] for t in T)==j.required_work_h);m.done[i,deadline].fix(1)
  for widx,w in enumerate(j.sla_windows):
   ts=list(range(round(w.start_h/dt),round(w.end_h/dt)));B=sum(j.baseline_rate[t]*dt for t in ts);Q=sum(m.q[i,t] for t in ts);floor=FLOORS[j.flex];m.c.add(Q>=floor*B)
   if floor<1:m.c.add(B-Q<=m.rho*(1-floor)*B)
   window_data.append((i,widx,ts,B,floor))
 for t in T:
  if s.power_limit_kw[t] is not None:m.c.add(power[t]<=s.power_limit_kw[t])
  energy+=power[t]*dt;cost+=power[t]*dt*s.price_usd_kwh[t]
 headroom=[]
 if s.policy=='author_dvfs_headroom_discrete':
  m.power_rho=p.Var(bounds=(0,1));events=[t for t in T if s.power_limit_kw[t] is not None]
  for i,j in enumerate(s.jobs):
   ref=next(a for a in j.actions if a.id==j.reference_action);w=j.sla_windows[0];ts=list(range(round(w.start_h/dt),round(w.end_h/dt)));outside=sum(j.baseline_rate[t]*dt for t in ts if t not in events);B=sum(j.baseline_rate[t]*dt for t in ts);minimum=max(0,(FLOORS[j.flex]*B-outside)/(len(events)*dt));eligible=[k for k,a in enumerate(j.actions) if a.normalized_rate>=minimum-1e-9 and a.power_w_per_gpu<=ref.power_w_per_gpu+1e-9];lo=min(j.actions[k].power_w_per_gpu for k in eligible);H=ref.power_w_per_gpu-lo
   headroom.append(dict(job=j.id,event_minimum_rate=minimum,reference_w_per_gpu=ref.power_w_per_gpu,minimum_w_per_gpu=lo,headroom_w_per_gpu=H,source='author README dvfs_fair pseudocode; event minimum from explicit window assuming baseline service outside event; discrete minimax realization, not author exact command trace'))
   for t in T:
    if not j.release_h<=t*dt<j.deadline_h:continue
    m.x[i,t,len(j.actions)].fix(0)
    for k,a in enumerate(j.actions):
     if (t in events and (k not in eligible or j.flex==0 and a.id!=j.reference_action)) or (t not in events and a.id!=j.reference_action):m.x[i,t,k].fix(0)
    if t in events and H>1e-9:m.c.add(ref.power_w_per_gpu-sum(a.power_w_per_gpu*m.x[i,t,k] for k,a in enumerate(j.actions))<=m.power_rho*H)
 m.obj=p.Objective(expr=m.power_rho if s.policy=='author_dvfs_headroom_discrete' else m.rho if s.policy=='fair_minimax' else cost);phases=[_milp(m,s,seconds,'minimax_power_headroom_fraction_from_author_pseudocode' if s.policy=='author_dvfs_headroom_discrete' else 'minimax_normalized_allowance' if s.policy=='fair_minimax' else 'energy_cost')];best=float(p.value(m.obj))
 if s.policy=='fair_minimax':m.c.add(m.rho<=best+s.lex_tolerance);m.obj.deactivate();m.obj2=p.Objective(expr=cost);phases.append(_milp(m,s,seconds,'energy_cost_locked_fairness'))
 if s.policy=='author_dvfs_headroom_discrete':
  m.c.add(m.power_rho<=best+s.lex_tolerance);m.obj.deactivate();event_energy=sum(power[t]*dt for t in events);m.obj2=p.Objective(expr=event_energy,sense=p.maximize);phases.append(_milp(m,s,seconds,'maximize_event_energy_with_locked_headroom_fairness'));event_best=float(p.value(event_energy));m.c.add(event_energy>=event_best-s.lex_tolerance);m.obj2.deactivate();m.obj3=p.Objective(expr=cost);phases.append(_milp(m,s,seconds,'minimize_full_cost_locked_headroom_and_event_energy'))
 slots=[];jobslots=[];jobs=[];windows=[];totenergy=actualenergy=baseenergy=totcost=0.;val_deadline=0.;val_sla=0.;val_power=0.;workres=0.;dt0=datetime.fromisoformat(s.start);actual_work={};planned_work={}
 for i,j in enumerate(s.jobs):
  cum=vcum=0.;n=len(j.actions);N=len(j.gpu_ids);idle=sum(gp[g].idle_power_w for g in j.gpu_ids)/N;ref=next(a for a in j.actions if a.id==j.reference_action);qq=[];vq=[]
  for t in T:
   aidx=max(range(n+2),key=lambda a:p.value(m.x[i,t,a]));q=float(p.value(m.q[i,t]));a=j.actions[aidx] if aidx<n else None;poww=a.power_w_per_gpu if a else (j.pause_power_w_per_gpu if aidx==n else idle);rate=a.normalized_rate if a else 0.;vpow=a.validation_power_w_per_gpu if a and a.validation_power_w_per_gpu is not None else poww;vrate=a.validation_normalized_rate if a and a.validation_normalized_rate is not None else rate;v=min(max(0,j.required_work_h-vcum),q*vrate/rate if rate else 0.);potential=rate*dt;cum+=q;vcum+=v;qq.append(q);vq.append(v);state='completed_idle' if aidx==n+1 and cum>=j.required_work_h-1e-6 else 'unreleased_idle' if aidx==n+1 else 'paused' if aidx==n else 'running';timestamp=(dt0+timedelta(hours=t*dt)).isoformat()
   row=dict(job=j.id,step=t,timestamp=timestamp,duration_h=dt,action=a.id if a else state,cap_w=a.cap_w if a else None,gpu_count=N,normalized_rate=rate,power_w_per_gpu=poww,validation_power_w_per_gpu=vpow,potential_work_h=potential,useful_work_h=q,wasted_capacity_work_h=max(0,potential-q),cumulative_work_h=cum,validation_useful_work_h=v,validation_cumulative_work_h=vcum,state=state,flex=j.flex);jobslots.append(row)
   for gid in j.gpu_ids:slots.append(dict(gpu=gid,job=j.id,step=t,timestamp=timestamp,duration_h=dt,state=state,action=row['action'],cap_w=row['cap_w'],power_w=gp[gid].idle_power_w if aidx==n+1 else poww,energy_kwh=(gp[gid].idle_power_w if aidx==n+1 else poww)*dt/1000,validation_power_w=gp[gid].idle_power_w if aidx==n+1 else vpow,gang_work_share_h=q/N,warning='gang_work_share is accounting only, NOT independently scalable perGPU throughput'))
   baseenergy+=N*(ref.power_w_per_gpu if j.baseline_rate[t]>0 else idle)*dt/1000
  actual_work[i]=vq;planned_work[i]=qq;missing=max(0,j.required_work_h-vcum);workres=max(workres,abs(cum-j.required_work_h));val_deadline=max(val_deadline,missing);jobs.append(dict(job=j.id,gpu_count=N,flex=j.flex,required_work_h=j.required_work_h,completed_work_h=cum,unfinished_work_h=max(0,j.required_work_h-cum),validation_completed_work_h=vcum,validation_unfinished_work_h=missing,deadline_h=j.deadline_h,initial_progress_h=0,work_unit='unthrottled fixed-gang equivalent hours',model_completed=abs(cum-j.required_work_h)<1e-6,validation_completed=missing<1e-6))
 hourly=[]
 for t in T:
  rows=[x for x in jobslots if x['step']==t];used={g for j in s.jobs for g in j.gpu_ids};unused=sum(g.idle_power_w for g in s.gpus if g.id not in used)/1000;P=s.non_gpu_fixed_kw+unused+sum(r['gpu_count']*r['power_w_per_gpu']/1000 for r in rows);V=s.non_gpu_fixed_kw+unused+sum(r['gpu_count']*r['validation_power_w_per_gpu']/1000 for r in rows);totenergy+=P*dt;actualenergy+=V*dt;totcost+=P*dt*s.price_usd_kwh[t];limit=s.power_limit_kw[t];val_power=max(val_power,0 if limit is None else max(0,V-limit));hourly.append(dict(step=t,timestamp=(dt0+timedelta(hours=t*dt)).isoformat(),duration_h=dt,planning_power_kw=P,validation_power_kw=V,power_limit_kw=limit,energy_kwh=P*dt,validation_energy_kwh=V*dt,price_usd_kwh=s.price_usd_kwh[t],cost_usd=P*dt*s.price_usd_kwh[t],fixed_non_gpu_kw=s.non_gpu_fixed_kw))
 unused={g.id for g in s.gpus}-{g for j in s.jobs for g in j.gpu_ids};baseenergy+=sum(gp[g].idle_power_w for g in unused)*dt*s.n_steps/1000+s.non_gpu_fixed_kw*dt*s.n_steps
 for gid in unused:
  for t in T:slots.append(dict(gpu=gid,job='',step=t,timestamp=(dt0+timedelta(hours=t*dt)).isoformat(),duration_h=dt,state='unallocated_idle',action='idle',cap_w=None,power_w=gp[gid].idle_power_w,energy_kwh=gp[gid].idle_power_w*dt/1000,validation_power_w=gp[gid].idle_power_w,gang_work_share_h=0,warning='no task assigned'))
 for i,widx,ts,B,floor in window_data:
  j=s.jobs[i];Q=sum(planned_work[i][t] for t in ts);V=sum(actual_work[i][t] for t in ts);loss=max(0,1-Q/B);vf=max(0,floor*B-V);val_sla=max(val_sla,vf);windows.append(dict(job=j.id,window=widx,flex=j.flex,start_h=ts[0]*dt,end_h=(ts[-1]+1)*dt,baseline_work_h=B,planned_work_h=Q,planning_performance=Q/B,validation_work_h=V,validation_performance=V/B,minimum_performance=floor,normalized_allowance_used=loss/(1-floor) if floor<1 else 0,planning_shortfall_h=max(0,floor*B-Q),validation_shortfall_h=vf,gpu_count=len(j.gpu_ids)))
 if workres>1e-6 or any(w['planning_shortfall_h']>1e-6 for w in windows) or any(h['power_limit_kw'] is not None and h['planning_power_kw']>h['power_limit_kw']+1e-6 for h in hourly):raise RuntimeError('GPU model audit failed; no accepted result')
 result=dict(model_kind='opt_gpu',name=s.name,status='optimal_with_reported_MILP_tolerances',objective_policy=s.policy,objective_value=totcost,currency='USD',energy_kwh=totenergy,validation_energy_kwh=actualenergy,reference_energy_kwh=baseenergy,energy_saving_kwh=baseenergy-totenergy,required_work_h=sum(j.required_work_h for j in s.jobs),completed_work_h=sum(j['completed_work_h'] for j in jobs),validation_unfinished_work_h=sum(j['validation_unfinished_work_h'] for j in jobs),max_work_residual_h=workres,validation_accepted=max(val_deadline,val_sla,val_power)<=1e-6,validation_max_deadline_shortfall_h=val_deadline,validation_max_sla_shortfall_h=val_sla,validation_max_power_violation_kw=val_power,fairness_rho=max((w['normalized_allowance_used'] for w in windows),default=0),gpu_weighted_window_performance=sum(w['gpu_count']*w['planned_work_h'] for w in windows)/sum(w['gpu_count']*w['baseline_work_h'] for w in windows),unweighted_window_performance=sum(w['planning_performance'] for w in windows)/len(windows),source=s.source,horizon=dict(start=s.start,steps=s.n_steps,dt_hours=dt),gpu_slots=slots,job_slots=jobslots,jobs=jobs,sla_windows=windows,hourly=hourly,solver_phases=phases,headroom_definition=headroom,solver=dict(seconds=time.monotonic()-st,each_phase_soft_limit_s=seconds,mip_relative_gap_requested=s.mip_relative_gap,global_claim='MILP model optimum within exported bounds/gap; NOT author controller optimality'),boundaries=dict(scope=s.power_boundary,work='sum of job-specific normalized ganghours is bookkeeping, NOT interchangeable absolute compute; active perGPU watts uniformly allocated from measured gang average, NOT individual measured telemetry; same fixed-gang total work exact by deadline; full horizon/recovery/idle energy included; partial-slot useful service may be less than capacity and wasted capacity exported',fairness='author README equal fraction of power headroom; discrete minimax + closest-to-budget realization; not exact hybrid pause enumeration' if headroom else s.fairness_definition,flex='0:unmodified reference + per-slot baseline;1/2/3:window average>=90/75/50%; windows explicit, no invented rolling SLA',validation='heldout fields NEVER enter optimization; static counterfactual realization uses productive fraction, no extra unplanned recovery; NOT measured closed-loop field control',not_supported='gang resizing/migration, checkpoint/restart loss, DC PUE/thermal/network coupling; no real nvidia-smi or external execution',reference='full reference-action reservation in each slot with positive baseline rate, idle elsewhere, NOT an optimized same-SLA baseline',weighted='explicit GPU-weighted metric; NOT presumed author unpublished Weighted Performance formula'))
 if s.require_validation_feasible and not result['validation_accepted']:raise GPUValidationFailure('heldout counterfactual SLA/deadline/power validation failed; model plan is not field-valid',result)
 return result

def export_task(t):
 b=io.BytesIO()
 with zipfile.ZipFile(b,'w',zipfile.ZIP_DEFLATED) as z:
  def put(n,v):z.writestr(n,json.dumps(v,ensure_ascii=False,indent=2,allow_nan=False))
  put('input_snapshot.json',t['snapshot']);put('model.json',t['snapshot']['model']);put('task_metadata.json',{k:v for k,v in t.items() if k not in ('snapshot','full_result','partial_result')});r=t.get('full_result') or t.get('partial_result');tables=['gpu_slots','job_slots','jobs','sla_windows','hourly','solver_phases']
  if r:
   put('results.json' if t['status']=='completed' else 'partial_NOT_ACCEPTED.json',{k:v for k,v in r.items() if k not in tables})
   for n in tables:
    rows=r[n];s=io.StringIO();fields=list(dict.fromkeys(k for row in rows for k in row));w=csv.DictWriter(s,fields);w.writeheader();w.writerows(rows);z.writestr(n+'.csv',s.getvalue())
  put('README.json',dict(scope='isolated GPU planning; no PUE/thermal certificate, no actual device commands',accepted=t['status']=='completed',failed='partial_NOT_ACCEPTED is not a successful field reproduction'))
 return b.getvalue()
