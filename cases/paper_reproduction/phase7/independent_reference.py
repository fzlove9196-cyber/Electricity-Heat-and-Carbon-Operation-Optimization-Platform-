"""Independent sparse SciPy MILP and exhaustive controls; NO product imports.
Shares HiGHS optimization backend, not model construction. Enumeration is backend-independent.
"""
import json,csv,zipfile,io,itertools,math
from pathlib import Path
import numpy as np
from scipy.optimize import milp,Bounds,LinearConstraint
from scipy.sparse import coo_matrix
FLOOR={0:1,1:.9,2:.75,3:.5}
def reference(m):
 dt=m['dt_hours'];T=range(m['n_steps']);jobs=m['jobs'];gpu={g['id']:g for g in m['gpus']};N=0;xx={};qq={};dd={};integral=[];lo=[];hi=[]
 def var(lb=0,ub=np.inf,binary=False):
  nonlocal N
  k=N;N+=1;lo.append(lb);hi.append(ub);integral.append(int(binary));return k
 for i,j in enumerate(jobs):
  for t in T:
   for a in range(len(j['actions'])+2):xx[i,t,a]=var(0,1,True)
   qq[i,t]=var();dd[i,t]=var(0,1,True)
 rho=var(0,1);prho=var(0,1);rows=[];lb=[];ub=[]
 def row(d,l=-np.inf,u=np.inf):rows.append(d);lb.append(l);ub.append(u)
 def fix(k,x):lo[k]=hi[k]=x
 unused=set(gpu)-{g for j in jobs for g in j['gpu_ids']};const=m.get('non_gpu_fixed_kw',0)+sum(gpu[g]['idle_power_w'] for g in unused)/1000;power=[{} for t in T];cost=np.zeros(N);energy=np.zeros(N);events=[t for t in T if m['power_limit_kw'][t] is not None];event=np.zeros(N)
 for i,j in enumerate(jobs):
  A=j['actions'];n=len(A);G=len(j['gpu_ids']);idle=sum(gpu[g]['idle_power_w'] for g in j['gpu_ids'])/G
  for t in T:
   row({xx[i,t,a]:1 for a in range(n+2)},1,1);row({qq[i,t]:1,**{xx[i,t,a]:-dt*A[a]['normalized_rate'] for a in range(n)}},u=0);cum={qq[i,k]:1 for k in range(t+1)};row({**cum,dd[i,t]:-j['required_work_h']},l=0);row({**cum,dd[i,t]:-j['required_work_h']},u=j['required_work_h']-1e-7);row(cum,u=j['required_work_h']);row({dd[i,t]:1,**({dd[i,t-1]:-1} if t else {})},l=0)
   if j.get('release_h',0)<=t*dt<j['deadline_h']:
    row({xx[i,t,n+1]:1,**({dd[i,t-1]:-1} if t else {})},0,0)
    if not j.get('allow_pause',False):fix(xx[i,t,n],0)
    if j['flex']==0 and j['baseline_rate'][t]>0:
     row({qq[i,t]:1},l=j['baseline_rate'][t]*dt);fix(xx[i,t,n],0)
     for a in range(n):
      if A[a]['id']!=j['reference_action']:fix(xx[i,t,a],0)
   else:fix(xx[i,t,n+1],1);fix(qq[i,t],0)
   for a in range(n+2):
    w=A[a]['power_w_per_gpu'] if a<n else j.get('pause_power_w_per_gpu',0) if a==n else idle;k=xx[i,t,a];power[t][k]=G*w/1000;energy[k]=G*w*dt/1000;cost[k]=energy[k]*m['price_usd_kwh'][t]
    if t in events:event[k]=energy[k]
  row({qq[i,t]:1 for t in T},j['required_work_h'],j['required_work_h']);fix(dd[i,round(j['deadline_h']/dt)-1],1)
  for w in j['sla_windows']:
   ts=range(round(w['start_h']/dt),round(w['end_h']/dt));B=sum(j['baseline_rate'][t]*dt for t in ts);floor=FLOOR[j['flex']];row({qq[i,t]:1 for t in ts},l=floor*B)
   if floor<1:row({**{qq[i,t]:-1 for t in ts},rho:-(1-floor)*B},u=-B)
  if m['policy']=='author_dvfs_headroom_discrete':
   w=j['sla_windows'][0];ts=range(round(w['start_h']/dt),round(w['end_h']/dt));outside=sum(j['baseline_rate'][t]*dt for t in ts if t not in events);B=sum(j['baseline_rate'][t]*dt for t in ts);rmin=max(0,(FLOOR[j['flex']]*B-outside)/(len(events)*dt));ref=next(a for a in A if a['id']==j['reference_action']);eligible=[a for a in range(n) if A[a]['normalized_rate']>=rmin-1e-9 and A[a]['power_w_per_gpu']<=ref['power_w_per_gpu']+1e-9];H=ref['power_w_per_gpu']-min(A[a]['power_w_per_gpu'] for a in eligible)
   for t in T:
    if not j.get('release_h',0)<=t*dt<j['deadline_h']:continue
    fix(xx[i,t,n],0)
    for a in range(n):
     if t in events and (a not in eligible or j['flex']==0 and A[a]['id']!=j['reference_action']) or t not in events and A[a]['id']!=j['reference_action']:fix(xx[i,t,a],0)
    if t in events and H>1e-9:row({**{xx[i,t,a]:-A[a]['power_w_per_gpu'] for a in range(n)},prho:-H},u=-ref['power_w_per_gpu'])
 for t in T:
  if m['power_limit_kw'][t] is not None:row(power[t],u=m['power_limit_kw'][t]-const)
 def run(c):
  ii=[];jj=[];vv=[]
  for r,d in enumerate(rows):
   for k,v in d.items():ii.append(r);jj.append(k);vv.append(v)
  mat=coo_matrix((vv,(ii,jj)),shape=(len(rows),N)).tocsr();z=milp(c,integrality=np.array(integral),bounds=Bounds(lo,hi),constraints=LinearConstraint(mat,lb,ub),options={'mip_rel_gap':0,'time_limit':120});assert z.success,(z.message,z.fun);return z
 policy=m['policy'];primary=cost.copy() if policy=='energy_cost' else np.eye(1,N,prho if policy=='author_dvfs_headroom_discrete' else rho).ravel();z=run(primary);first=float(z.fun);phases=[first];tol=m.get('lex_tolerance',1e-7)
 if policy!='energy_cost':row({prho if policy=='author_dvfs_headroom_discrete' else rho:1},u=first+tol)
 if policy=='fair_minimax':z=run(cost);phases.append(float(z.fun))
 if policy=='author_dvfs_headroom_discrete':z=run(-event);phases.append(float(-z.fun+const*len(events)*dt));row({k:-v for k,v in enumerate(event) if v},u=z.fun+tol);z=run(cost);phases.append(float(z.fun))
 out=dict(cost_usd=float(cost@z.x+sum(const*dt*v for v in m['price_usd_kwh'])),energy_kwh=float(energy@z.x+const*dt*m['n_steps']),phase_objectives=phases,relative_gap=float(z.mip_gap),backend='independent SciPy sparse model; same HiGHS backend, no product imports');return out

def enumerate_small(m):
 assert len(m['jobs'])<=2 and m['n_steps']<=4
 dt=m['dt_hours'];jobs=m['jobs'];T=range(m['n_steps']);choices=[];best=None;count=0
 for j in jobs:
  idle=sum(g['idle_power_w'] for g in m['gpus'] if g['id'] in j['gpu_ids'])/len(j['gpu_ids']);assert idle==j['pause_power_w_per_gpu'];choices.append([(a['normalized_rate'],a['power_w_per_gpu'],a['id']) for a in j['actions']]+[(0,idle,'pause')])
 for sequence in itertools.product(list(itertools.product(*choices)),repeat=len(T)):
  count+=1;P=[sum(len(j['gpu_ids'])*sequence[t][i][1]/1000 for i,j in enumerate(jobs))+m.get('non_gpu_fixed_kw',0) for t in T]
  if any(v is not None and P[t]>v+1e-9 for t,v in enumerate(m['power_limit_kw'])):continue
  rhos=[];valid=True
  for i,j in enumerate(jobs):
   capacities=[sequence[t][i][0]*dt for t in T]
   if sum(capacities)<j['required_work_h']-1e-9:valid=False;break
   assert len(j['sla_windows'])==1;w=j['sla_windows'][0];ts=list(range(round(w['start_h']/dt),round(w['end_h']/dt)));B=sum(j['baseline_rate'][t]*dt for t in ts);Q=min(j['required_work_h'],sum(capacities[t] for t in ts));floor=FLOOR[j['flex']]
   if Q<floor*B-1e-9:valid=False;break
   if floor<1:rhos.append(max(0,1-Q/B)/(1-floor))
  if not valid:continue
  cost=sum(P[t]*dt*m['price_usd_kwh'][t] for t in T);rho=max(rhos,default=0);key=(rho,cost) if m['policy']=='fair_minimax' else (cost,)
  if best is None or key<best:best=key
 assert best is not None;return dict(examined_sequences=count,primary=best[0],cost_usd=best[-1])
def load_zip(path):
 with zipfile.ZipFile(path) as z:
  m=json.loads(z.read('model.json'));r=json.loads(z.read('results.json') if 'results.json' in z.namelist() else z.read('partial_NOT_ACCEPTED.json'))
  for n in ['gpu_slots','job_slots','jobs','sla_windows','hourly','solver_phases']:
   rr=list(csv.DictReader(io.StringIO(z.read(n+'.csv').decode())))
   for a in rr:
    for k,v in a.items():
     if k in {'gpu','job','timestamp','action','state','warning','work_unit','phase','termination','objective_units'}:continue
     if v=='':a[k]=None
     elif v in ('True','False'):a[k]=v=='True'
     else:
      try:a[k]=json.loads(v)
      except ValueError:pass
   r[n]=rr
 return m,r

def audit(m,r):
 dt=m['dt_hours'];N=m['n_steps'];gp={g['id']:g for g in m['gpus']};assert len(r['gpu_slots'])==len(gp)*N and len({(g['gpu'],g['step']) for g in r['gpu_slots']})==len(gp)*N;cost=energy=0.;maxwork=0.;maxpower=0.;valmissing=0.;slaerr=0.;maxcapacity=0.;feas_tol=1e-6
 for h in r['hourly']:
  t=h['step'];gg=[x for x in r['gpu_slots'] if x['step']==t];power=sum(x['power_w'] for x in gg)/1000+m.get('non_gpu_fixed_kw',0);maxpower=max(maxpower,abs(power-h['planning_power_kw']));assert abs(h['energy_kwh']-power*dt)<1e-7;cost+=power*dt*m['price_usd_kwh'][t];energy+=power*dt
 for j in m['jobs']:
  ss=sorted([x for x in r['job_slots'] if x['job']==j['id']],key=lambda x:x['step']);assert len(ss)==N;cum=0.;vcum=0.
  for row in ss:
   q=row['useful_work_h'];a=next((a for a in j['actions'] if a['id']==row['action']),None);rate=a['normalized_rate'] if a else 0;vrate=a.get('validation_normalized_rate',rate) if a else 0;vrate=rate if vrate is None else vrate;maxcapacity=max(maxcapacity,max(0,-q,q-rate*dt));assert -feas_tol<=q<=rate*dt+feas_tol;assert abs(row['potential_work_h']-rate*dt)<1e-7;cum+=q;v=min(j['required_work_h']-vcum,q*vrate/rate if rate else 0);vcum+=v;assert abs(v-row['validation_useful_work_h'])<1e-7
   if row['step']*dt>=j['deadline_h']:assert abs(q)<1e-7
   gg=[g for g in r['gpu_slots'] if g['job']==j['id'] and g['step']==row['step']];assert len(gg)==len(j['gpu_ids']);assert abs(sum(x['gang_work_share_h'] for x in gg)-q)<1e-7
  maxwork=max(maxwork,abs(cum-j['required_work_h']));valmissing+=max(0,j['required_work_h']-vcum)
  for wi,w in enumerate(j['sla_windows']):
   ts=range(round(w['start_h']/dt),round(w['end_h']/dt));B=sum(j['baseline_rate'][t]*dt for t in ts);Q=sum(ss[t]['useful_work_h'] for t in ts);out=next(v for v in r['sla_windows'] if v['job']==j['id'] and v['window']==wi);slaerr=max(slaerr,abs(Q/B-out['planning_performance']));assert Q>=FLOOR[j['flex']]*B-1e-6
 assert maxwork<1e-6 and maxpower<1e-7 and slaerr<1e-7 and abs(cost-r['objective_value'])<1e-6 and abs(energy-r['energy_kwh'])<1e-6 and abs(valmissing-r['validation_unfinished_work_h'])<1e-6
 return dict(declared_feasibility_tolerance=feas_tol,max_capacity_residual_h=maxcapacity,gpu_slot_rows=len(r['gpu_slots']),max_work_residual_h=maxwork,max_power_audit_error_kw=maxpower,max_sla_ratio_error=slaerr,cost_usd_recomputed=cost,energy_kwh_recomputed=energy,validation_unfinished_work_h=valmissing)
